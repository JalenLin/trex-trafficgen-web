"""Protocol catalog, packet building and field-engine compilation.

Runs inside worker processes only. Scapy is imported lazily: in a TRex worker it
must be the copy bundled with that TRex release, which becomes importable only
after the TRex client has been loaded. Works with Scapy 2.4.3 (TRex v3.x) and 2.6.

Stream specs are plain JSON shared with the frontend:

    packet = {"layers": [{"proto": "Ether", "fields": {"dst": "..."}}, ...],
              "frame_size": 64}            # optional, bytes on the wire incl. FCS
    vm     = [{"layer": 1, "field": "src", "op": "inc",
               "start": "16.0.0.1", "end": "16.0.0.254", "step": 1}, ...]

Field values: str / int / bool as typed by the user, {"hex": "..."} for raw bytes,
or {"py": "..."} for a Python literal (lists, option fields).
"""
from __future__ import annotations  # Catalog.list() would shadow `list` in annotations

import ast
import contextlib
import importlib
import io
import ipaddress
import logging
import pkgutil
import re

FCS_LEN = 4

# Shown first in the protocol picker. Missing names (older Scapy) are skipped.
COMMON = [
    "Ether", "Dot1Q", "Dot1AD", "ARP", "IP", "IPv6",
    "IPv6ExtHdrHopByHop", "IPv6ExtHdrRouting", "IPv6ExtHdrFragment", "IPv6ExtHdrDestOpt",
    "UDP", "TCP", "ICMP", "ICMPv6EchoRequest", "ICMPv6EchoReply",
    "GRE", "VXLAN", "MPLS", "GTP_U_Header", "GENEVE", "Raw",
]

_INT_RE = re.compile(r"[+-]?(0[xX][0-9a-fA-F]+|0[bB][01]+|\d+)")

# Fields Scapy computes when left empty; setting them by hand usually breaks the packet.
_AUTO_FIELD_RE = re.compile(r"len|length|chksum|cksum|checksum|ihl|dataofs|crc", re.I)
# Layers TRex's flow-stats parser walks through before it expects IPv4/IPv6.
_L2_TUNNEL = ("Ether", "Dot1Q", "Dot1AD", "MPLS")
_L4 = ("UDP", "TCP", "ICMP", "ICMPv6EchoRequest", "ICMPv6EchoReply", "SCTP", "GRE")
LATENCY_PAYLOAD = 16  # TRex's flow_stat_payload_header: magic, flow_seq, hw_id, seq, timestamp
ETH_MIN_FRAME = 64
ETH_MAX_FRAME = 1518


class PacketError(ValueError):
    pass


class Catalog:
    """Every Scapy layer available in this process, core and contrib."""

    def __init__(self):
        logging.getLogger("scapy").setLevel(logging.ERROR)
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            import scapy.all  # noqa: F401  (loads core layers)
            import scapy.contrib

            self.failed_contrib = []
            for mod in pkgutil.iter_modules(scapy.contrib.__path__):
                try:
                    importlib.import_module("scapy.contrib." + mod.name)
                except Exception as e:
                    self.failed_contrib.append(f"{mod.name}: {type(e).__name__}")

        from scapy import fields as F
        from scapy.config import conf
        from scapy.packet import Packet, Raw

        self.F = F
        import scapy

        self.scapy_version = scapy.VERSION

        classes = [c for c in conf.layers if isinstance(c, type) and issubclass(c, Packet)]
        if Raw not in classes:
            classes.append(Raw)
        names = {}
        for c in classes:
            names.setdefault(c.__name__, []).append(c)

        self.by_id: dict[str, type] = {}
        self.id_of: dict[type, str] = {}
        for name, group in names.items():
            if name.startswith("_"):
                continue
            for c in group:
                pid = name if len(group) == 1 else f"{_short_module(c)}.{name}"
                self.by_id[pid] = c
                self.id_of[c] = pid

    # --- listing -----------------------------------------------------------

    def list(self) -> dict:
        protos = [
            {"id": pid, "name": c.__name__, "desc": _desc(c), "module": _short_module(c)}
            for pid, c in sorted(self.by_id.items(), key=lambda kv: kv[0].lower())
        ]
        return {
            "scapy_version": self.scapy_version,
            "common": [p for p in COMMON if p in self.by_id],
            "protocols": protos,
            "failed_contrib": self.failed_contrib,
        }

    def get(self, pid: str) -> type:
        try:
            return self.by_id[pid]
        except KeyError:
            raise PacketError(f"unknown protocol '{pid}'")

    def schema(self, pid: str) -> dict:
        cls = self.get(pid)
        nxt = []
        for _, c in getattr(cls, "payload_guess", []) or []:
            i = self.id_of.get(c)
            if i and i not in nxt:
                nxt.append(i)
        return {
            "id": pid,
            "name": cls.__name__,
            "desc": _desc(cls),
            "module": _short_module(cls),
            "fields": [self._safe_field_info(f) for f in cls.fields_desc],
            "next": nxt[:60],
        }

    # --- fields ------------------------------------------------------------

    def _unwrap(self, fld):
        # Wrappers (ConditionalField, Emph, ActionField, ...) hold the real field
        # in .fld; MultipleTypeField picks one at build time, .dflt is the default.
        F = self.F
        conditional = False
        while True:
            if isinstance(fld, F.ConditionalField):
                fld, conditional = fld.fld, True
            elif hasattr(F, "MultipleTypeField") and isinstance(fld, F.MultipleTypeField):
                fld = fld.dflt
            elif type(fld).__name__ in ("Emph", "ActionField", "_FieldContainer") and hasattr(fld, "fld"):
                fld = fld.fld
            else:
                return fld, conditional

    def kind(self, fld) -> str:
        F = self.F
        f, _ = self._unwrap(fld)
        if isinstance(f, (F.IP6Field,)):
            return "ip6"
        if isinstance(f, (F.IPField,)):
            return "ip"
        if isinstance(f, F.MACField):
            return "mac"
        if isinstance(f, F.FlagsField):
            return "flags"
        if isinstance(f, (F.PacketField, F.PacketListField)):
            return "packet"
        if isinstance(f, F.FieldListField):
            return "list"
        if isinstance(f, F.StrField):
            return "bytes"
        if hasattr(f, "i2s") and isinstance(getattr(f, "i2s"), dict) and f.i2s:
            return "enum"
        if isinstance(f, F.BitField) or getattr(f, "fmt", "")[-1:] in tuple("bBhHiIlLqQ"):
            return "int"
        return "other"

    def _safe_field_info(self, fld) -> dict:
        # A few contrib fields break on introspection; keep the rest of the layer usable.
        try:
            return self._field_info(fld)
        except Exception:
            return {"name": fld.name, "kind": "other", "type": type(fld).__name__, "conditional": False, "default": None}

    def _field_info(self, fld) -> dict:
        f, conditional = self._unwrap(fld)
        kind = self.kind(fld)
        info = {"name": fld.name, "kind": kind, "type": type(f).__name__, "conditional": conditional}
        try:
            info["default"] = None if fld.default is None else str(f.i2repr(None, fld.default))
        except Exception:
            info["default"] = None if fld.default is None else repr(fld.default)
        if kind == "enum":
            items = list(f.i2s.items())[:512]
            info["enum"] = [{"value": k, "label": str(v)} for k, v in items if isinstance(k, int)]
        if kind == "flags":
            names = f.names
            if isinstance(names, str):
                names = list(names)
            info["flags"] = [str(n) for n in names]
        if kind not in ("int", "enum", "flags", "ip", "ip6", "mac"):
            pass  # variable-length; size depends on the value
        elif isinstance(getattr(f, "size", None), int):  # bit fields, incl. FlagsField
            info["bits"] = f.size
        elif getattr(f, "sz", None):
            info["bits"] = int(f.sz * 8)
        return info

    def convert(self, cls, name: str, value):
        fld = next((f for f in cls.fields_desc if f.name == name), None)
        if fld is None:
            raise PacketError(f"{cls.__name__} has no field '{name}'")
        if isinstance(value, dict):
            if "hex" in value:
                try:
                    return bytes.fromhex(value["hex"].replace(" ", ""))
                except ValueError:
                    raise PacketError(f"{cls.__name__}.{name}: invalid hex")
            if "py" in value:
                try:
                    return ast.literal_eval(value["py"])
                except (ValueError, SyntaxError) as e:
                    raise PacketError(f"{cls.__name__}.{name}: {e}")
            raise PacketError(f"{cls.__name__}.{name}: unsupported value {value!r}")
        if isinstance(value, str) and self.kind(fld) in ("int", "enum", "flags") and _INT_RE.fullmatch(value.strip()):
            return int(value.strip(), 0)
        return value

    # --- packets -----------------------------------------------------------

    def build(self, spec: dict):
        """Build a Scapy packet from a spec, padded to frame_size if given."""
        from scapy.packet import Raw

        layers = spec.get("layers") or []
        if not layers:
            raise PacketError("packet has no layers")
        pkt = None
        for i, layer in enumerate(layers):
            cls = self.get(layer["proto"])
            try:
                obj = cls()
            except Exception as e:  # some contrib classes are abstract
                raise PacketError(f"layer {i + 1} {cls.__name__} cannot be used directly: {type(e).__name__}: {e}")
            for name, value in (layer.get("fields") or {}).items():
                if value is None or value == "":
                    continue
                try:
                    setattr(obj, name, self.convert(cls, name, value))
                except PacketError:
                    raise
                except Exception as e:
                    raise PacketError(f"layer {i + 1} {cls.__name__}.{name}: {e}")
            try:
                pkt = obj if pkt is None else pkt / obj
            except Exception as e:  # a few contrib layers recurse forever when stacked
                raise PacketError(f"layer {i + 1} {cls.__name__} cannot follow layer {i}: {type(e).__name__}")
        try:
            length = len(bytes(pkt))
        except Exception as e:
            # Scapy appends multi-line hints (e.g. about RawVal); the first lines carry the cause.
            msg = " ".join(str(e).splitlines()[:2]) or type(e).__name__
            raise PacketError(f"cannot build packet: {msg}")
        frame_size = spec.get("frame_size")
        if frame_size:
            pad = int(frame_size) - FCS_LEN - length
            if pad > 0:
                pkt = pkt / Raw(load=payload_bytes(spec.get("payload"), pad))
        return pkt

    def describe(self, pkt, user_layers: int | None = None) -> dict:
        """Hex dump plus per-layer field values and bit positions.

        Each header is re-dissected from its own bytes, so checksums and lengths
        show their final values while the layer stack stays exactly as built.
        """
        from scapy.packet import NoPayload

        try:
            data = bytes(pkt)
        except Exception as e:  # e.g. a contrib post_build that breaks once padding is added
            raise PacketError(f"cannot build packet: {type(e).__name__}: {e}")
        layers = []
        seen: dict[type, int] = {}
        cur = pkt
        while cur is not None and not isinstance(cur, NoPayload):
            cls = type(cur)
            payload = cur.payload
            try:
                tail = len(bytes(cur))
                plen = 0 if isinstance(payload, NoPayload) else len(bytes(payload))
            except Exception as e:  # layer can't be built on its own (needs its underlayer)
                raise PacketError(f"cannot analyse {cls.__name__}: {type(e).__name__}: {e}")
            off = len(data) - tail
            hlen = tail - plen
            index = seen.get(cls, 0)
            seen[cls] = index + 1
            try:
                shown = cls(data[off:off + hlen])
            except Exception:
                shown = cur
            layers.append({
                "proto": self.id_of.get(cls, cls.__name__),
                "name": cls.__name__,
                "desc": _desc(cls),
                "index": index,
                "offset": off,
                "length": hlen,
                "padding": user_layers is not None and len(layers) >= user_layers,
                "fields": self._layout(shown, off * 8),
            })
            cur = payload
        return {"hex": data.hex(), "length": len(data), "frame_length": len(data) + FCS_LEN, "layers": layers}

    def _layout(self, layer, base_bit: int) -> list:
        out = []
        s = b""
        for fld in layer.fields_desc:
            before = _bits(s)
            val = layer.getfieldval(fld.name)
            try:
                s = fld.addfield(layer, s, val)
            except Exception:
                break
            size = _bits(s) - before
            try:
                text = str(fld.i2repr(layer, val))
            except Exception:
                text = repr(val)
            out.append({
                "name": fld.name,
                "repr": text,
                "bit_offset": base_bit + before,
                "bits": size,
                "kind": self.kind(fld),
                "writable": size > 0 and _writable(self.kind(fld), size),
            })
        return out

    # --- importing captured frames -----------------------------------------

    def packet_to_spec(self, data: bytes) -> dict:
        """Dissect a captured Ethernet frame into an editable layer spec.

        Length/checksum fields are left empty so they recompute after edits. The
        spec is rebuilt and compared byte for byte; if it doesn't reproduce the
        frame (odd options, unknown protocols, deliberately broken checksums),
        progressively more is kept as raw bytes, so what TRex sends always equals
        the capture.
        """
        from scapy.layers.l2 import Ether

        pkt = Ether(data)
        for keep_auto in (False, True):
            layers = self._layers_from(pkt, data, keep_auto)
            if layers and self._rebuilds(layers, data):
                if keep_auto is False:
                    return {"layers": layers, "note": None, "note_code": None}
                return {"layers": layers, "note_code": "pcapKeptAuto",
                        "note": "Length/checksum fields keep the values from the pcap (recomputing them would differ from the capture)"}
        return {"layers": [{"proto": "Raw", "fields": {"load": {"hex": data.hex()}}}], "note_code": "pcapRawOnly",
                "note": "Could not split into protocol fields; imported as raw bytes"}

    def _layers_from(self, pkt, data: bytes, keep_auto: bool) -> list:
        from scapy.packet import NoPayload, Padding, Raw

        layers, offset, cur = [], 0, pkt
        while cur is not None and not isinstance(cur, NoPayload):
            cls = type(cur)
            rest = data[offset:]
            if isinstance(cur, Padding) and "Padding" in self.by_id:
                # Ethernet trailer padding: Scapy keeps it out of IP/UDP lengths,
                # unlike frame_size padding, which is added as payload.
                layers.append({"proto": "Padding", "fields": {"load": {"hex": rest.hex()}}})
                break
            if isinstance(cur, (Raw, Padding)) or cls not in self.id_of:
                if rest:
                    layers.append({"proto": "Raw", "fields": {"load": {"hex": rest.hex()}}})
                break
            fields = {}
            try:
                for name, val in cur.fields.items():
                    fld = self._field(cls, name)
                    if fld is None or val is None or val == fld.default:
                        continue
                    if not keep_auto and fld.default is None and _AUTO_FIELD_RE.search(name):
                        continue  # let Scapy recompute it
                    fields[name] = self._to_json(fld, val)
            except ValueError:
                # A field we can't express: keep this layer and the rest as raw bytes.
                if rest:
                    layers.append({"proto": "Raw", "fields": {"load": {"hex": rest.hex()}}})
                break
            layers.append({"proto": self.id_of[cls], "fields": fields})
            try:
                offset += len(cur) - len(cur.payload)
            except Exception:
                break
            cur = cur.payload
        return layers

    def _to_json(self, fld, val):
        kind = self.kind(fld)
        if kind in ("int", "enum", "flags") and not isinstance(val, (list, str, bytes)):
            return int(val)
        if kind in ("ip", "ip6", "mac") or isinstance(val, str):
            return str(val)
        if isinstance(val, bytes):
            return {"hex": val.hex()}
        if isinstance(val, (bool, int, float)):
            return val
        text = repr(val)  # e.g. TCP options [('MSS', 1460), ('SAckOK', b'')]
        try:
            if ast.literal_eval(text) == val:
                return {"py": text}
        except (ValueError, SyntaxError):
            pass
        raise ValueError(f"cannot represent {fld.name}")

    def _rebuilds(self, layers: list, data: bytes) -> bool:
        try:
            return bytes(self.build({"layers": layers})) == data
        except Exception:
            return False

    # --- sanity checks -----------------------------------------------------
    #
    # Warnings only: deliberately malformed packets are a normal negative test.
    # Each item: {"level": "warning" | "info", "layer": index | None, "field": name | None, "message": str}

    def _bindings(self, a: type, b: type) -> list[dict]:
        """Field values layer a takes when b follows it, per Scapy's bind_layers.
        The first entry is what Scapy fills in automatically; empty list = not bound."""
        out = []
        # A layer may bind as another one: Dot1Q has aliastypes = [Ether], so
        # Ether's bindings (e.g. IP -> type 0x800) apply after a VLAN tag too.
        unders = [a, *(getattr(a, "aliastypes", None) or [])]
        # Class-level table is `overload_fields` in Scapy 2.4, `_overload_fields` in 2.5+
        # (where `overload_fields` became a per-instance slot).
        table = next((t for t in (getattr(b, "_overload_fields", None), getattr(b, "overload_fields", None)) if isinstance(t, dict)), {})
        for under, fields in table.items():
            if isinstance(under, type) and any(issubclass(u, under) for u in unders):
                out.append(dict(fields))
        for u in unders:
            for fields, cls in getattr(u, "payload_guess", None) or []:
                if isinstance(cls, type) and issubclass(b, cls):
                    out.append(dict(fields))
        return out

    def _internal(self, cls: type, name: str, value):
        fld = next((f for f in cls.fields_desc if f.name == name), None)
        f, _ = self._unwrap(fld)
        try:
            return f.any2i(None, self.convert(cls, name, value))
        except Exception:
            return value

    def _field(self, cls: type, name: str):
        return next((f for f in cls.fields_desc if f.name == name), None)

    def lint_packet(self, spec: dict, desc: dict) -> list:
        from scapy.packet import Packet, Padding, Raw

        warn = []
        layers = spec.get("layers") or []
        classes = [self.get(l["proto"]) for l in layers]

        for i in range(len(classes) - 1):
            a, b = classes[i], classes[i + 1]
            if issubclass(b, (Raw, Padding)):
                continue
            if issubclass(a, (Raw, Padding)):
                warn.append(_w("warning", i + 1, None, "afterRaw", f"{a.__name__} is raw data; {b.__name__} after it is just more data",
                               prev=a.__name__, next=b.__name__))
                continue
            alternatives = self._bindings(a, b)
            if not alternatives:
                if a.guess_payload_class is not Packet.guess_payload_class:
                    # Next layer chosen by custom code (IPv6 extension headers, ...);
                    # the binding table can't tell, so stay quiet rather than guess.
                    continue
                # Which of a's fields would normally say what comes next (e.g. Ether.type)?
                dispatch = sorted({k for fields, _ in getattr(a, "payload_guess", None) or [] for k in fields
                                   if "port" not in k and self.kind(self._field(a, k)) not in ("mac", "ip", "ip6")})
                shown = {f["name"]: f["repr"] for f in desc["layers"][i]["fields"]} if i < len(desc["layers"]) else {}
                hint = ", ".join(f"{a.__name__}.{k} = {shown[k]}" for k in dispatch if k in shown)
                warn.append(_w("warning", i + 1, None, "unusualNext" if not hint else "unusualNextHint",
                               f"{b.__name__} doesn't normally follow {a.__name__}; Scapy can't fill in the next-layer type"
                               + (f" ({hint})" if hint else ""), prev=a.__name__, next=b.__name__, hint=hint))
                continue
            user = (layers[i].get("fields") or {})
            set_keys = {k for alt in alternatives for k in alt if user.get(k) not in (None, "")}
            if not set_keys:
                continue
            if any(all(self._internal(a, k, user[k]) == alt[k] for k in set_keys if k in alt) for alt in alternatives):
                continue
            for k in sorted(set_keys):
                expected = alternatives[0].get(k)
                if expected is None:
                    continue
                port_like = "port" in k
                std = self._repr(a, k, expected)
                warn.append(_w("info" if port_like else "warning", i, k, "dispatchPort" if port_like else "dispatchField",
                               f"{a.__name__}.{k} is set to {user[k]} but the next layer is {b.__name__} (standard value {std})"
                               + (f"; the receiver may not parse it as {b.__name__}" if port_like else ""),
                               name=f"{a.__name__}.{k}", value=str(user[k]), next=b.__name__, std=std))

        for i, (cls, layer) in enumerate(zip(classes, layers)):
            for name, value in (layer.get("fields") or {}).items():
                fld = next((f for f in cls.fields_desc if f.name == name), None)
                if fld is None or value in (None, "") or fld.default is not None or not _AUTO_FIELD_RE.search(name):
                    continue
                warn.append(_w("info", i, name, "autoField",
                               f"{cls.__name__}.{name} is computed automatically; a manual value makes an invalid packet "
                               "(fine for deliberate negative tests)", name=f"{cls.__name__}.{name}"))

        content = desc["length"] - sum(l["length"] for l in desc["layers"] if l["padding"])
        size = spec.get("size") or {}
        if size.get("mode", "fixed") != "fixed":
            # The template is built at the largest size; judge by the range actually sent.
            smallest, largest = int(size.get("min") or 0), int(size.get("max") or 0)
            if size["mode"] in ("inc", "dec") and largest > smallest:
                vmin, vmax, init = _size_var(size)
                count = (vmax - vmin + 1) // int(size.get("step") or 1)
                last = init + (count - 1) * int(size.get("step") or 1) * (1 if size["mode"] == "inc" else -1)
                first, last = init + FCS_LEN, last + FCS_LEN
                if (first, last) != ((smallest, largest) if size["mode"] == "inc" else (largest, smallest)):
                    second = first + (last - first) // max(count - 1, 1)
                    warn.append(_w("info", None, None, "sizeGrid",
                                   f"With this step {count} sizes are sent: {first}, {second} … {last} bytes",
                                   count=count, first=first, second=second, last=last))
        else:
            frame_size = spec.get("frame_size")
            if frame_size and content + FCS_LEN > int(frame_size):
                warn.append(_w("warning", None, None, "contentOverSize",
                               f"The packet content is already {content + FCS_LEN} bytes (with FCS), more than the frame size "
                               f"{frame_size}; the setting is ignored", content=content + FCS_LEN, size=frame_size))
            smallest = largest = desc["frame_length"]
        if smallest < ETH_MIN_FRAME:
            warn.append(_w("warning", None, None, "belowMinFrame",
                           f"Smallest frame is {smallest} bytes (with FCS), below Ethernet's minimum of {ETH_MIN_FRAME}; "
                           "it may be padded or dropped", size=smallest, min=ETH_MIN_FRAME))
        if largest > ETH_MAX_FRAME:
            warn.append(_w("info", None, None, "jumbo",
                           f"Largest frame is {largest} bytes, over standard Ethernet's {ETH_MAX_FRAME}; every device on the "
                           "path must support jumbo frames", size=largest, max=ETH_MAX_FRAME))
        return warn

    def _repr(self, cls: type, name: str, value) -> str:
        fld = next((f for f in cls.fields_desc if f.name == name), None)
        try:
            return f"{fld.i2repr(None, value)} ({value:#x})" if isinstance(value, int) and self.kind(fld) == "enum" else str(fld.i2repr(None, value))
        except Exception:
            return str(value)

    def lint_stream(self, stream: dict, desc: dict) -> list:
        """Requirements TRex enforces only when traffic starts."""
        warn = []
        size = (stream.get("packet") or {}).get("size") or {}
        if size.get("mode", "fixed") != "fixed" and sum(1 for l in desc["layers"] if l["name"] == "UDP") > 1:
            warn.append(_w("info", None, None, "innerUdpChecksum",
                           "With a varying size only the outermost UDP checksum is fixed; inner (tunnelled) UDP checksums will "
                           "be wrong. If the receiver checks them, set the inner UDP chksum to 0 (allowed over IPv4)"))
        fs = (stream.get("flow_stats") or {}).get("type", "none")
        if fs == "none":
            return warn
        kind = "latency" if fs == "latency" else "flow"
        label = "Latency" if fs == "latency" else "Flow stats"
        layers = [l for l in desc["layers"] if not l["padding"]]
        i = 0
        while i < len(layers) and layers[i]["name"] in _L2_TUNNEL:
            i += 1
        if i >= len(layers) or layers[i]["name"] not in ("IP", "IPv6"):
            warn.append(_w("warning", i if i < len(layers) else None, None, f"{kind}NeedsIp",
                           f"{label} needs IPv4 or IPv6 (only Ethernet, VLAN, MPLS before it), or TRex rejects the start"))
            return warn
        between = sorted({l["name"] for l in layers[:i]} & {"Dot1Q", "Dot1AD", "MPLS"})
        if between:
            warn.append(_w("info", None, None, f"{kind}NicSupport",
                           f"{label} with {'/'.join(between)} needs NIC support; without it starting traffic fails",
                           tags="/".join(between)))
        if fs == "latency" and size.get("mode", "fixed") != "fixed" and int(size.get("min") or 0) < 60 + LATENCY_PAYLOAD + FCS_LEN:
            warn.append(_w("warning", None, None, "latencyMinVarying",
                           f"Latency with a varying size needs a minimum frame of at least {60 + LATENCY_PAYLOAD + FCS_LEN} bytes, "
                           "or TRex rejects the start", min=60 + LATENCY_PAYLOAD + FCS_LEN))
        if fs == "latency":
            l4 = next((l for l in layers[i + 1:] if l["name"] in _L4), None)
            header_end = (l4 or layers[i])["offset"] + (l4 or layers[i])["length"]
            payload = desc["length"] - header_end
            if payload < LATENCY_PAYLOAD:
                need = desc["frame_length"] + LATENCY_PAYLOAD - payload
                after = (l4 or layers[i])["name"]
                warn.append(_w("warning", None, None, "latencyPayload",
                               f"Latency needs at least {LATENCY_PAYLOAD} bytes of data after {after}, there are {payload}; "
                               f"the frame must be at least {need} bytes, or TRex rejects the start",
                               after=after, need_payload=LATENCY_PAYLOAD, payload=payload, need=need))
        return warn

    # --- field engine ------------------------------------------------------

    def compile_vm(self, desc: dict, vm: list, size: dict | None = None) -> list:
        """Turn VM rows (and a varying packet size) into a neutral instruction list."""
        if not vm and not size:
            return []
        layers = desc["layers"]
        plan = self._size_plan(desc, size) if size else []
        for n, row in enumerate(vm):
            where = f"field engine row {n + 1}"
            li = row.get("layer")
            if not isinstance(li, int) or not 0 <= li < len(layers) or layers[li]["padding"]:
                raise PacketError(f"{where}: layer {li} is not in the packet")
            layer = layers[li]
            fld = next((f for f in layer["fields"] if f["name"] == row.get("field")), None)
            if fld is None:
                raise PacketError(f"{where}: {layer['name']} has no field '{row.get('field')}'")
            if not fld["writable"]:
                raise PacketError(f"{where}: {layer['name']}.{fld['name']} cannot be changed by the field engine")
            label = f"{where} ({layer['name']}.{fld['name']})"

            kind, bit_off, bits = fld["kind"], fld["bit_offset"], fld["bits"]
            if kind in ("ip6", "mac"):
                # Only the low 32 bits vary; the rest stays as in the packet.
                bit_off, bits = bit_off + bits - 32, 32
            start = _parse_value(kind, row.get("start"), label)
            end = _parse_value(kind, row.get("end", row.get("start")), label)
            lo, hi = min(start, end), max(start, end)
            if hi >= 1 << bits:
                raise PacketError(f"{label}: value does not fit in {bits} bits")
            step = int(row.get("step") or 1)
            op = row.get("op", "inc")
            if op not in ("inc", "dec", "random"):
                raise PacketError(f"{label}: op must be inc, dec or random")
            if step < 1:
                raise PacketError(f"{label}: step must be >= 1")
            if lo == hi:
                step = 1
            elif op != "random" and step > hi - lo:
                raise PacketError(f"{label}: step is larger than the start-end range")

            if op != "random":
                lo, hi, start = _true_cycle(lo, hi, step, op, (1 << bits) - 1)
            var = f"fv{n}"
            if bit_off % 8 == 0 and bits in (8, 16, 32, 64):
                size = bits // 8
                plan.append({"type": "var", "name": var, "size": size, "op": op, "min": lo, "max": hi, "step": step, "init": start})
                plan.append({"type": "write", "var": var, "offset": bit_off // 8})
            elif bits <= 32:
                first = bit_off // 8
                span = (bit_off + bits + 7) // 8 - first
                cast = next(c for c in (1, 2, 4) if c >= span)
                if first + cast > desc["length"]:
                    raise PacketError(f"{label}: field too close to the end of the packet")
                shift = cast * 8 - (bit_off - first * 8) - bits
                size = next(c for c in (1, 2, 4) if c * 8 >= bits)
                plan.append({"type": "var", "name": var, "size": size, "op": op, "min": lo, "max": hi, "step": step, "init": start})
                plan.append({"type": "write_mask", "var": var, "offset": first, "cast": cast,
                             "mask": ((1 << bits) - 1) << shift, "shift": shift})
            else:
                raise PacketError(f"{label}: fields wider than 32 bits are not supported")

        plan.extend(self._checksum_fixes(layers))
        return plan

    def _size_plan(self, desc: dict, size: dict) -> list:
        """Varying frame size: the packet is built at the largest size and TRex trims
        each copy to a flow-var length, then rewrites every length field that covers
        the end of the packet (IPv4 total length, IPv6 payload length, UDP length)."""
        lo, hi, init = _size_var(size)
        var = "fv_size"
        # TRex's default split: core k starts k steps in and jumps step*cores. The range
        # from _size_var is a whole number of steps, so the wrap stays on the grid. (Not
        # splitting makes every core repeat the same sequence: a burst then gets the
        # first sizes many times and never the last ones.)
        plan = [{"type": "var", "name": var, "size": 2, "op": size["mode"], "min": lo, "max": hi,
                 "step": int(size.get("step") or 1), "init": init},
                {"type": "trim", "var": var}]
        for layer in desc["layers"]:
            field = {"IP": "len", "IPv6": "plen", "UDP": "len"}.get(layer["name"])
            if layer["padding"] or not field:
                continue
            f = next((x for x in layer["fields"] if x["name"] == field), None)
            if f is None or f["bit_offset"] % 8 or f["bits"] != 16:
                continue
            # value written = packet length + add, i.e. the bytes from this header's start
            # (IPv6 payload length excludes its own 40-byte header)
            add = -(layer["offset"] + (40 if layer["name"] == "IPv6" else 0))
            plan.append({"type": "write", "var": var, "offset": f["bit_offset"] // 8, "add": add})
        return plan

    def _checksum_fixes(self, layers: list) -> list:
        # Outermost L3/L4 pair: hardware checksum offload covers both headers.
        # Inner IPv4 headers (tunnels) get a software IPv4 header fix.
        fixes = []
        l3 = [i for i, l in enumerate(layers) if l["name"] in ("IP", "IPv6")]
        if not l3:
            return fixes
        first = l3[0]
        nxt = layers[first + 1]["name"] if first + 1 < len(layers) else None
        if nxt in ("UDP", "TCP"):
            fixes.append({"type": "fix_hw", "l3": layers[first]["offset"], "l4": layers[first + 1]["offset"], "l4_type": nxt.lower()})
        elif layers[first]["name"] == "IP":
            fixes.append({"type": "fix_ipv4", "offset": layers[first]["offset"]})
        for i in l3[1:]:
            if layers[i]["name"] == "IP":
                fixes.append({"type": "fix_ipv4", "offset": layers[i]["offset"]})
        return fixes


def _desc(cls) -> str:
    # Packet.name is normally a class-level string, but on some classes it is a
    # __slots__ descriptor.
    name = getattr(cls, "name", None)
    return name if isinstance(name, str) and name else cls.__name__


PAYLOAD_TYPES = ("zeros", "byte", "inc", "dec", "random", "text", "hex")


def payload_bytes(payload: dict | None, n: int) -> bytes:
    """Fill for the bytes that pad a packet up to its frame size.

    payload = {"type": zeros|byte|inc|dec|random|text|hex, "value": str}. The fill is
    part of the stream's template, so every packet carries the same bytes; "random"
    is seeded by `value` so the preview and what TRex sends match.
    """
    payload = payload or {}
    kind = payload.get("type") or "zeros"
    value = str(payload.get("value") or "").strip()
    if kind not in PAYLOAD_TYPES:
        raise PacketError(f"unknown payload type {kind!r}")
    if kind == "zeros":
        return b"\x00" * n
    if kind in ("byte", "inc", "dec"):
        try:
            start = int(value, 0) if value else (0 if kind != "dec" else 0xFF)
        except ValueError:
            raise PacketError(f"payload: {value!r} is not a byte value (e.g. 0xAA or 170)")
        if not 0 <= start <= 0xFF:
            raise PacketError("payload: a byte value must be 0..255 (0x00..0xFF)")
        if kind == "byte":
            return bytes([start]) * n
        sign = 1 if kind == "inc" else -1
        return bytes((start + sign * i) & 0xFF for i in range(n))
    if kind == "random":
        import random

        try:
            seed = int(value, 0) if value else 0
        except ValueError:
            raise PacketError(f"payload: random seed {value!r} must be a number")
        return random.Random(seed).randbytes(n)
    if kind == "text":
        unit = value.encode()
        if not unit:
            raise PacketError("payload: enter the text to repeat")
    else:
        try:
            unit = bytes.fromhex(value.replace(" ", "").replace(":", ""))
        except ValueError:
            raise PacketError(f"payload: {value!r} is not hex (e.g. DEADBEEF or de:ad:be:ef)")
        if not unit:
            raise PacketError("payload: enter the hex bytes to repeat")
    return (unit * (n // len(unit) + 1))[:n]


def _w(level: str, layer, field, code: str, message: str, **params) -> dict:
    """A lint warning. The UI shows `code` translated with `params` (frontend
    locales/lint.ts); `message` is the English fallback for API users."""
    return {"level": level, "layer": layer, "field": field, "code": code, "params": params, "message": message}


def _true_cycle(lo: int, hi: int, step: int, op: str, cap: int, floor: int = 0) -> tuple[int, int, int]:
    """(min, max, init) of a TRex variable that cycles exactly through lo, lo+step, ...
    (inc) or hi, hi-step, ... (dec), staying within the user's [lo, hi].

    TRex wraps a variable past its bound carrying the remainder (inc_mod/dec_mod), so
    unless (max - min + 1) is a multiple of step the values drift between the steps
    after the first round (64,164,...,1464 then 69,79,...). The step-1 bytes of
    padding go above the last grid point when they fit under `cap`, else below the
    first one; the padding itself is never reached. `floor` is a minimum TRex
    enforces on the variable itself (60 for packet size).
    """
    lo = max(lo, floor)
    if step <= 1 or hi - lo < step:
        return lo, hi, lo if op == "inc" else hi
    k = (hi - lo) // step  # whole steps that fit in the user's range
    while True:
        bottom, top = (lo, lo + k * step) if op == "inc" else (hi - k * step, hi)
        below = max(0, top + step - 1 - cap)  # padding that doesn't fit above
        if bottom - below >= floor or k == 0:
            return bottom - below, top + step - 1 - below, bottom if op == "inc" else top
        k -= 1


def _short_module(cls) -> str:
    mod = cls.__module__
    for prefix in ("scapy.layers.", "scapy."):
        if mod.startswith(prefix):
            return mod[len(prefix):]
    return mod


def _bits(s) -> int:
    # Field.addfield returns bytes, or (bytes, bits_done, value) mid bit-field.
    if isinstance(s, tuple):
        return len(s[0]) * 8 + s[1]
    return len(s) * 8


def _writable(kind: str, bits: int) -> bool:
    if kind in ("ip6", "mac"):
        return True
    return kind in ("int", "enum", "flags", "ip") and bits <= 64 and (bits <= 32 or bits == 64)


def _parse_value(kind: str, value, label: str) -> int:
    if value is None or value == "":
        raise PacketError(f"{label}: start value is required")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        if kind == "ip":
            return int(ipaddress.IPv4Address(text))
        if kind == "ip6":
            return int(ipaddress.IPv6Address(text)) & 0xFFFFFFFF
        if kind == "mac" and ":" in text:
            return int(text.replace(":", "")[-8:], 16)
        return int(text, 0)
    except ValueError:
        raise PacketError(f"{label}: invalid value '{text}'")


# --- streams ---------------------------------------------------------------

def frame_bits(desc: dict) -> int:
    """L1 bits per packet: frame incl. FCS + preamble/SFD (8) + IFG (12)."""
    return (desc["frame_length"] + 8 + 12) * 8


def compile_stream(catalog: Catalog, stream: dict) -> dict:
    """Validate a stream spec; returns the built packet, its description and VM plan."""
    packet = stream.get("packet") or {}
    size = _varying_size(packet)
    if size:
        # Built at the largest size the variable can hold, trimmed per packet. For an
        # inc/dec cycle that can be up to step-1 bytes over the user's max, never sent.
        packet = dict(packet, frame_size=_size_var(size)[1] + FCS_LEN)
    pkt = catalog.build(packet)
    desc = catalog.describe(pkt, user_layers=len(packet.get("layers") or []))
    if size:
        content = desc["length"] - sum(l["length"] for l in desc["layers"] if l["padding"]) + FCS_LEN
        if size["min"] < content:
            raise PacketError(f"minimum frame size {size['min']} is smaller than the headers ({content} bytes incl. FCS)")
    plan = catalog.compile_vm(desc, stream.get("vm") or [], size)
    packet = stream.get("packet") or {}  # lint the user's spec, not the enlarged template

    mode = stream.get("mode") or {}
    if mode.get("type", "continuous") not in ("continuous", "single_burst", "multi_burst"):
        raise PacketError(f"unknown mode {mode.get('type')!r}")
    rate = stream.get("rate") or {}
    if rate.get("unit", "pps") not in ("pps", "bps_L1", "bps_L2", "percentage"):
        raise PacketError(f"unknown rate unit {rate.get('unit')!r}")
    if float(rate.get("value", 0)) <= 0:
        raise PacketError("rate must be greater than 0")
    fs = stream.get("flow_stats") or {}
    if fs.get("type", "none") not in ("none", "stats", "latency"):
        raise PacketError(f"unknown flow stats type {fs.get('type')!r}")
    warnings = catalog.lint_packet(packet, desc) + catalog.lint_stream(stream, desc)
    return {"pkt": pkt, "describe": desc, "vm": plan, "warnings": warnings}


MAX_FRAME = 9216
TRIM_FLOOR = 60  # TRex raises a packet-size variable's minimum to 60 bytes (no FCS)


def _size_var(size: dict) -> tuple[int, int, int]:
    """(min, max, init) of the packet-size variable, in bytes without FCS."""
    lo, hi = int(size["min"]) - FCS_LEN, int(size["max"]) - FCS_LEN
    if size["mode"] == "random":
        return max(lo, TRIM_FLOOR), hi, max(lo, TRIM_FLOOR)
    # TRex raising the min to 60 on its own would break the cycle, so plan around it.
    return _true_cycle(lo, hi, int(size.get("step") or 1), size["mode"], MAX_FRAME - FCS_LEN, floor=TRIM_FLOOR)


def _varying_size(packet: dict) -> dict | None:
    """packet["size"] = {"mode": fixed|inc|dec|random, "min", "max", "step"} in frame bytes incl. FCS."""
    size = packet.get("size") or {}
    mode = size.get("mode", "fixed")
    if mode == "fixed":
        return None
    if mode not in ("inc", "dec", "random"):
        raise PacketError(f"unknown size mode {mode!r}")
    try:
        lo, hi, step = int(size["min"]), int(size["max"]), int(size.get("step") or 1)
    except (KeyError, TypeError, ValueError):
        raise PacketError("varying size needs min and max frame sizes")
    if not 0 < lo < hi:
        raise PacketError("frame size: min must be smaller than max")
    if hi > MAX_FRAME:
        raise PacketError(f"frame size: max is {MAX_FRAME} bytes")
    if step < 1:
        raise PacketError("frame size: step must be >= 1")
    if mode != "random" and step > hi - lo:
        raise PacketError("frame size: step is larger than the min-max range")
    return {"mode": mode, "min": lo, "max": hi, "step": step}


def to_trex_stream(api, compiled: dict, stream: dict):
    """Build an STLStream from a compiled spec, using the TRex client's API module."""
    from trex.stl.trex_stl_packet_builder_scapy import CTRexVmInsFixHwCs

    instructions = []
    for ins in compiled["vm"]:
        t = ins["type"]
        if t == "var":
            instructions.append(api.STLVmFlowVar(name=ins["name"], init_value=ins["init"], min_value=ins["min"],
                                                 max_value=ins["max"], size=ins["size"], step=ins["step"], op=ins["op"],
                                                 split_to_cores=ins.get("split", True)))
        elif t == "write":
            instructions.append(api.STLVmWrFlowVar(fv_name=ins["var"], pkt_offset=ins["offset"], add_val=ins.get("add", 0)))
        elif t == "trim":
            instructions.append(api.STLVmTrimPktSize(ins["var"]))
        elif t == "write_mask":
            instructions.append(api.STLVmWrMaskFlowVar(fv_name=ins["var"], pkt_offset=ins["offset"],
                                                       pkt_cast_size=ins["cast"], mask=ins["mask"], shift=ins["shift"]))
        elif t == "fix_ipv4":
            instructions.append(api.STLVmFixIpv4(offset=ins["offset"]))
        elif t == "fix_hw":
            l4 = CTRexVmInsFixHwCs.L4_TYPE_UDP if ins["l4_type"] == "udp" else CTRexVmInsFixHwCs.L4_TYPE_TCP
            instructions.append(api.STLVmFixChecksumHw(l3_offset=ins["l3"], l4_offset=ins["l4"], l4_type=l4))
    vm = api.STLScVmRaw(instructions) if instructions else None
    builder = api.STLPktBuilder(pkt=compiled["pkt"], vm=vm)

    rate = stream.get("rate") or {}
    rate_kw = {rate.get("unit", "pps"): float(rate.get("value", 1))}
    mode = stream.get("mode") or {}
    mtype = mode.get("type", "continuous")
    if mtype == "single_burst":
        tx = api.STLTXSingleBurst(total_pkts=int(mode.get("total_pkts", 1)), **rate_kw)
    elif mtype == "multi_burst":
        tx = api.STLTXMultiBurst(pkts_per_burst=int(mode.get("pkts_per_burst", 1)), ibg=float(mode.get("ibg_usec", 0)),
                                 count=int(mode.get("count", 1)), **rate_kw)
    else:
        tx = api.STLTXCont(**rate_kw)

    fs = stream.get("flow_stats") or {}
    flow_stats = None
    if fs.get("type") == "stats":
        flow_stats = api.STLFlowStats(pg_id=int(fs["pg_id"]))
    elif fs.get("type") == "latency":
        flow_stats = api.STLFlowLatencyStats(pg_id=int(fs["pg_id"]))

    return api.STLStream(
        name=stream.get("id") or None,  # unsaved streams have no id yet
        packet=builder,
        mode=tx,
        enabled=bool(stream.get("enabled", True)),
        self_start=bool(stream.get("self_start", True)),
        isg=float(stream.get("isg_usec", 0)),
        flow_stats=flow_stats,
        next=stream.get("next") or None,
    )
