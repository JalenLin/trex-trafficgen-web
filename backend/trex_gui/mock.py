"""Fake TRex host for developing the GUI without a TRex server.

Implements the same ops as worker.TRexAdapter. Packets are built and validated
with the pip-installed Scapy, so stream editing behaves like the real thing;
traffic is simulated from the stream rates. Ports 0 and 1 are owned by another
user and already transmitting, to exercise the ownership UI. Ports are wired in
pairs (0<->1, 2<->3, ...); each port receives what its peer sends, minus 0.1%.
"""
import ipaddress
import math
import os
import random
import re
import time
import zlib

OTHER_USER = "lab-user"
LINE_OVERHEAD = 8 + 12  # preamble/SFD + inter-frame gap, bytes


class MockAdapter:
    def __init__(self, cfg: dict):
        self._username = cfg["username"]
        self._connected = False
        self._catalog = None
        self._ports = []
        # Per-host MACs, so several mock hosts don't look wired to each other on the port map.
        tag = zlib.crc32(cfg["id"].encode()) & 0xFF
        self._mac = lambda pid: f"02:00:5e:{tag:02x}:53:{pid:02x}"
        self._gw_mac = lambda pid: f"02:00:00:{tag:02x}:01:{pid:02x}"
        for pid in range(cfg.get("mock_ports", 16)):
            busy = pid < 2
            self._ports.append({
                "id": pid,
                "driver": "net_mock",
                "description": "Mock 25G port",
                "speed_gbps": 25.0,
                "link": "UP",
                "status": "TRANSMITTING" if busy else "IDLE",
                "vlan": "-",
                "hw_mac": self._mac(pid),
                "owner": OTHER_USER if busy else "",
            })
        # L3 by default (gateway answers ARP); ports 0/1 in L2 like a loopback pair.
        self._layer = {
            p["id"]: {
                "mode": "L2" if p["id"] < 2 else "L3",
                "src_mac": p["hw_mac"],
                "dst_mac": self._mac(p["id"] ^ 1) if p["id"] < 2 else self._gw_mac(p["id"]),
                "ipv4_src": None if p["id"] < 2 else f"10.{p['id']}.0.2",
                "ipv4_dst": None if p["id"] < 2 else f"10.{p['id']}.0.1",
                "arp": "none" if p["id"] < 2 else "resolved",
                "ipv6": False, "ipv6_src": None, "vlan": [], "promiscuous": False, "multicast": False,
                "link_up": True, "link_supported": True, "flow_ctrl": 0, "service": "off",
            }
            for p in self._ports
        }
        self._pg = {}  # pg_id -> {"type", "tx": {port: n}, "rx": {port: n}, "tx_pps", "rx_pps"}
        self._captures = {}  # id -> {"tx", "rx", "limit", "start", "mode"}
        self._next_capture = 1
        # Per port: list of {"pps", "bytes", "until"}; ports 0/1 carry the other user's traffic.
        self._flows = {p["id"]: [] for p in self._ports}
        for pid in (0, 1):
            if pid < len(self._ports):
                self._flows[pid] = [{"pps": 1_000_000.0, "bytes": 512, "until": None, "wobble": True}]
        self._paused = set()
        self._stop_at = {}
        self._counters = {p["id"]: dict.fromkeys(("opackets", "ipackets", "obytes", "ibytes"), 0.0) for p in self._ports}
        self._baseline = {pid: dict(c) for pid, c in self._counters.items()}
        self._last = time.monotonic()
        # A new worker process = a "restarted" mock server with default port settings.
        self._started = time.strftime("%b %d %Y @ %H:%M:%S")

    def _require_connected(self):
        if not self._connected:
            raise RuntimeError("not connected")

    def _require_owned(self, ports):
        for pid in ports:
            if self._ports[pid]["owner"] != self._username:
                raise RuntimeError(f"port {pid} is not owned by you")

    def op_connect(self):
        self._connected = True
        return {"server_version": {"version": "mock", "build_date": "", "mode": "STL"}, "server_started": self._started}

    def op_disconnect(self):
        for p in self._ports:
            if p["owner"] == self._username:
                self._halt(p["id"])
                p["owner"] = ""
        self._connected = False
        return None

    def op_ports(self):
        self._require_connected()
        self._expire()
        return [dict(p, acquired=p["owner"] == self._username, layer=dict(self._layer[p["id"]])) for p in self._ports]

    def op_acquire(self, ports, force=False):
        self._require_connected()
        for pid in ports:
            port = self._ports[pid]
            if port["owner"] not in ("", self._username) and not force:
                raise RuntimeError(f"port {pid} is owned by '{port['owner']}', use force to take it over")
            if port["owner"] != self._username:
                self._halt(pid)
            port["owner"] = self._username
        return self.op_ports()

    def op_release(self, ports):
        self._require_connected()
        for pid in ports:
            if self._ports[pid]["owner"] == self._username:
                self._ports[pid]["owner"] = ""
        return self.op_ports()

    def op_clear_stats(self, ports=None):
        self._require_connected()
        self._expire()
        for pid in ports if ports is not None else self._counters:
            self._baseline[pid] = dict(self._counters[pid])
        for pg in self._pg.values():
            pg["tx"] = dict.fromkeys(pg["tx"], 0.0)
            pg["rx"] = dict.fromkeys(pg["rx"], 0.0)
        return None

    # --- port L2/L3 configuration ---

    def op_port_config(self, port, vlan=None, l2=None, l3=None, ipv6=None, promiscuous=None, multicast=None,
                       link_up=None, flow_ctrl=None):
        self._require_connected()
        self._require_owned([port])
        if self._ports[port]["status"] != "IDLE":
            raise RuntimeError(f"port {port} is transmitting; stop it before changing L2/L3 settings")
        layer = self._layer[port]
        warnings = []
        if vlan is not None:
            if len(vlan) > 2 or any(not 1 <= int(v) <= 4094 for v in vlan):
                raise RuntimeError("VLAN: one or two tags (QinQ), each 1-4094")
            layer["vlan"] = [int(v) for v in vlan]
        if l2 is not None:
            if not re.fullmatch(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", l2["dst_mac"]):
                raise RuntimeError(f"invalid MAC address: '{l2['dst_mac']}'")
            layer.update(mode="L2", dst_mac=l2["dst_mac"].lower(), ipv4_src=None, ipv4_dst=None, arp="none")
        if l3 is not None:
            for key in ("src", "dst"):
                try:
                    ipaddress.IPv4Address(l3[key])
                except ValueError:
                    raise RuntimeError(f"{key}_ipv4 is not a valid IPv4 address: '{l3[key]}'")
            layer.update(mode="L3", ipv4_src=l3["src"], ipv4_dst=l3["dst"])
            warnings += self._arp(port)
        if ipv6 is not None:
            layer.update(ipv6=bool(ipv6.get("enabled")), ipv6_src=ipv6.get("src") or None)
        if promiscuous is not None:
            layer["promiscuous"] = promiscuous
        if multicast is not None:
            layer["multicast"] = multicast
        if link_up is not None:
            layer["link_up"] = link_up
            self._ports[port]["link"] = "UP" if link_up else "DOWN"
        if flow_ctrl is not None:
            if flow_ctrl not in (0, 1, 2, 3):
                raise RuntimeError("flow_ctrl must be 0 (none), 1 (tx), 2 (rx) or 3 (full)")
            layer["flow_ctrl"] = flow_ctrl
        return {"ports": self.op_ports(), "warnings": warnings}

    def _arp(self, port) -> list:
        # The simulated gateway answers only when it is in the port's /24.
        layer = self._layer[port]
        net = ipaddress.ip_network(f"{layer['ipv4_src']}/24", strict=False)
        if ipaddress.ip_address(layer["ipv4_dst"]) in net and layer["ipv4_dst"] != layer["ipv4_src"]:
            layer.update(arp="resolved", dst_mac=self._gw_mac(port))
            return []
        layer["arp"] = "unresolved"
        return [f"port {port}: gateway {layer['ipv4_dst']} did not answer ARP; traffic will not start until it resolves"]

    def op_resolve(self, ports):
        self._require_connected()
        self._require_owned(ports)
        warnings = []
        for pid in ports:
            if self._layer[pid]["mode"] == "L3":
                warnings += self._arp(pid)
        return {"ports": self.op_ports(), "warnings": warnings}

    def op_ping(self, port, dst_ip, count=3, pkt_size=64):
        self._require_connected()
        self._require_owned([port])
        layer = self._layer[port]
        if layer["mode"] != "L3":
            raise RuntimeError(f"port {port} is in L2 mode; ping needs an L3 (IPv4) configuration")
        reachable = layer["arp"] == "resolved" and ipaddress.ip_address(dst_ip) in ipaddress.ip_network(f"{layer['ipv4_src']}/24", strict=False)
        return [{"state": "ok", "responder": dst_ip, "rtt_ms": round(random.uniform(0.05, 0.3), 3), "ttl": 64} if reachable
                else {"state": "timeout", "responder": "N/A", "rtt_ms": None, "ttl": None} for _ in range(count)]

    # --- packets and streams ---

    def catalog(self):
        if self._catalog is None:
            from .packets import Catalog
            self._catalog = Catalog()
        return self._catalog

    def op_protocols(self):
        return self.catalog().list()

    def op_protocol_schema(self, proto):
        return self.catalog().schema(proto)

    def op_build_packet(self, packet, flow_stats=None):
        cat = self.catalog()
        desc = cat.describe(cat.build(packet), user_layers=len(packet.get("layers") or []))
        warnings = cat.lint_packet(packet, desc) + cat.lint_stream({"flow_stats": flow_stats, "packet": packet}, desc)
        return {**desc, "warnings": warnings}

    def op_check_stream(self, stream):
        from .packets import compile_stream
        compiled = compile_stream(self.catalog(), stream)
        return {"describe": compiled["describe"], "vm": compiled["vm"], "warnings": compiled["warnings"]}

    # --- traffic ---

    def op_start(self, port_streams, mult="1", force=False, duration=-1):
        from .packets import compile_stream
        self._require_connected()
        ports = sorted(port_streams)
        self._require_owned(ports)
        self._expire()
        busy = [p for p in ports if self._ports[p]["status"] != "IDLE"]
        if busy and not force:
            raise RuntimeError(f"port(s) {', '.join(map(str, busy))} already transmitting; stop them first")

        for port in ports:
            if self._layer[port]["mode"] == "L3" and self._layer[port]["arp"] != "resolved":
                raise RuntimeError(f"port {port} is in L3 mode but gateway {self._layer[port]['ipv4_dst']} is unresolved")
        now = time.monotonic()
        plans = {}
        for port in ports:
            flows = []
            for s in port_streams[port]:
                try:
                    compiled = compile_stream(self.catalog(), s)
                except Exception as e:
                    raise RuntimeError(f"port {port}, stream '{s.get('name') or s['id']}': {e}")
                if not s.get("enabled", True) or not s.get("self_start", True):
                    continue
                size = compiled["describe"]["frame_length"]
                pps = _to_pps(s.get("rate") or {}, size, self._ports[port]["speed_gbps"])
                mode = s.get("mode") or {}
                if mode.get("type") == "single_burst":
                    until = now + int(mode.get("total_pkts", 1)) / pps
                elif mode.get("type") == "multi_burst":
                    until = now + int(mode.get("pkts_per_burst", 1)) * int(mode.get("count", 1)) / pps
                else:
                    until = None
                fs = s.get("flow_stats") or {}
                pg = int(fs["pg_id"]) if fs.get("type") in ("stats", "latency") else None
                flows.append({"id": s.get("id"), "pps": pps, "bytes": size - 4, "until": until, "pg": pg,
                              "frame": bytes(compiled["pkt"]), "paused": False})
                if pg is not None:
                    self._pg.setdefault(pg, {"type": fs["type"], "tx": {}, "rx": {}})["type"] = fs["type"]
            if not flows:
                raise RuntimeError(f"port {port} has no enabled streams")
            plans[port] = flows

        for port, flows in plans.items():
            factor = _mult_factor(mult, flows, self._ports[port]["speed_gbps"])
            for f in flows:
                f["base_pps"] = f["pps"]  # rates as defined; update() scales from these
                f["pps"] *= factor
            self._flows[port] = flows
            self._ports[port]["status"] = "TRANSMITTING"
            self._paused.discard(port)
            self._stop_at[port] = now + duration if duration and duration > 0 else None
        return self.op_ports()

    def op_stop(self, ports):
        self._require_connected()
        self._expire()
        self._require_owned(ports)
        for pid in ports:
            self._halt(pid)
        return self.op_ports()

    def op_pause(self, ports):
        self._require_connected()
        self._expire()
        self._require_owned(ports)
        for pid in ports:
            if self._ports[pid]["status"] == "TRANSMITTING":
                self._ports[pid]["status"] = "PAUSE"
                self._paused.add(pid)
        return self.op_ports()

    def op_resume(self, ports):
        self._require_connected()
        self._expire()
        self._require_owned(ports)
        for pid in ports:
            if pid in self._paused:
                self._ports[pid]["status"] = "TRANSMITTING"
                self._paused.discard(pid)
        return self.op_ports()

    def op_update(self, ports, mult):
        self._require_connected()
        self._expire()
        self._require_owned(ports)
        for pid in ports:
            flows = self._flows[pid]
            if self._ports[pid]["status"] == "IDLE" or not flows:
                raise RuntimeError(f"port {pid} is not transmitting")
            base = [dict(f, pps=f.get("base_pps", f["pps"])) for f in flows]
            factor = _mult_factor(mult, base, self._ports[pid]["speed_gbps"])
            for f, b in zip(flows, base):
                f["pps"] = b["pps"] * factor
        return self.op_ports()

    # --- pcap ---

    def op_pcap_packets(self, path, start=0, count=100):
        from .pcapops import list_packets
        return list_packets(self.catalog(), path, start, count)

    def op_pcap_to_streams(self, path, indices, name):
        from .pcapops import to_streams
        return to_streams(self.catalog(), path, indices, name)

    def op_push_pcap(self, ports, path, remote, ipg_usec=None, speedup=1.0, count=1, duration=-1,
                     min_ipg_usec=None, src_mac_pcap=False, dst_mac_pcap=False, force=False,
                     packets=1, duration_s=0.0, avg_frame=64):
        from .pcaps import read_packets
        self._require_connected()
        self._require_owned(ports)
        self._expire()
        busy = [p for p in ports if self._ports[p]["status"] != "IDLE"]
        if busy and not force:
            raise RuntimeError(f"port(s) {', '.join(map(str, busy))} already transmitting; stop them first")
        if not remote and os.path.getsize(path) > 1024 * 1024:
            raise RuntimeError("PCAP is too big for local push (1MB limit)")
        first_frame = next(read_packets(path))[1]
        # Replay speed: fixed gap, else the capture's own timing sped up.
        one_pass = packets * ipg_usec / 1e6 if ipg_usec else max(duration_s, 1e-3) / max(speedup, 1e-9)
        pps = packets / max(one_pass, 1e-6)
        total = one_pass * max(count, 1) if count else None
        if duration and duration > 0:
            total = min(total, duration) if total else duration
        now = time.monotonic()
        for port in ports:
            self._flows[port] = [{"pps": pps, "bytes": avg_frame, "until": now + total if total else None,
                                  "pg": None, "frame": first_frame}]
            self._ports[port]["status"] = "TRANSMITTING"
            self._paused.discard(port)
            self._stop_at[port] = None
        return self.op_ports()

    def op_capture_start(self, tx_ports, rx_ports, limit=1000, mode="fixed", bpf_filter="", service=False):
        self._require_connected()
        cid = self._next_capture
        self._next_capture += 1
        self._captures[cid] = {"tx": list(tx_ports), "rx": list(rx_ports), "limit": limit, "mode": mode, "start": time.monotonic()}
        return {"id": cid}

    def _captured(self, cap) -> list:
        # Simulated: copies of what each captured port sends (TX) or its peer sends (RX).
        now = time.monotonic()
        sources = [(p, "tx") for p in cap["tx"]] + [(p ^ 1, "rx") for p in cap["rx"]]
        out = []
        for port, _ in sources:
            for f in self._flows.get(port, []):
                n = int(min(f["pps"] * (now - cap["start"]), cap["limit"]))
                out += [(i / max(f["pps"], 1), f.get("frame", b"\x00" * 60)) for i in range(n)]
        out.sort(key=lambda x: x[0])
        return out[: cap["limit"]] if cap["mode"] == "fixed" else out[-cap["limit"]:]

    def op_capture_status(self):
        return [{"id": cid, "state": "ACTIVE", "count": len(self._captured(c)), "limit": c["limit"], "bytes": 0, "mode": c["mode"]}
                for cid, c in self._captures.items()]

    def op_capture_stop(self, capture_id, save=True):
        cap = self._captures.pop(capture_id, None)
        if cap is None:
            raise RuntimeError(f"no capture {capture_id}")
        return self._captured(cap) if save else []

    def op_profile_info(self, path):
        raise RuntimeError("mock hosts can't run TRex Python profiles (they import the TRex client)")

    def op_start_profile(self, path, ports, values, mult="1", duration=-1, force=False):
        raise RuntimeError("mock hosts can't run TRex Python profiles (they import the TRex client)")

    def op_reset(self, ports):
        self._require_connected()
        self._require_owned(ports)
        for pid in ports:
            self._halt(pid)
            self._baseline[pid] = dict(self._counters[pid])
        return self.op_ports()

    def _halt(self, pid):
        self._flows[pid] = []
        self._ports[pid]["status"] = "IDLE"
        self._paused.discard(pid)
        self._stop_at.pop(pid, None)

    def _expire(self):
        """Bring the simulation up to now: counters are integrated up to each moment a
        port stops (duration over, burst sent) before it stops, then up to now. So
        counts are right whether or not anyone polled while traffic ran."""
        now = time.monotonic()
        while True:
            due = []
            for p in self._ports:
                pid = p["id"]
                if p["status"] == "IDLE":
                    continue
                if self._stop_at.get(pid):
                    due.append(self._stop_at[pid])
                due += [f["until"] for f in self._flows[pid] if f["until"] is not None]
            due = [t for t in due if t <= now]
            if not due:
                break
            t = min(due)
            self._advance_to(t)
            for p in self._ports:
                pid = p["id"]
                if p["status"] == "IDLE":
                    continue
                if self._stop_at.get(pid) and self._stop_at[pid] <= t:
                    self._halt(pid)
                    continue
                self._flows[pid] = [f for f in self._flows[pid] if f["until"] is None or f["until"] > t]
                if not self._flows[pid]:
                    self._halt(pid)
        self._advance_to(now)

    def _advance_to(self, t):
        dt = t - self._last
        if dt <= 0:
            return
        self._last = t
        for p in self._ports:
            pid = p["id"]
            tx_pps, tx_bps = self._tx(pid, t)
            if not tx_pps:
                continue
            ratio = self._delivered(pid)
            c, peer = self._counters[pid], self._counters[pid ^ 1]
            c["opackets"] += tx_pps * dt
            c["obytes"] += tx_bps / 8 * dt
            peer["ipackets"] += tx_pps * ratio * dt
            peer["ibytes"] += tx_bps / 8 * ratio * dt
            if p["status"] != "TRANSMITTING":
                continue
            for f in self._flows[pid]:
                if f.get("pg") is None or f.get("paused"):
                    continue
                pg = self._pg[f["pg"]]
                pg["tx"][pid] = pg["tx"].get(pid, 0.0) + f["pps"] * dt
                pg["rx"][pid ^ 1] = pg["rx"].get(pid ^ 1, 0.0) + f["pps"] * dt * ratio

    def _tx(self, pid, now):
        if self._ports[pid]["status"] != "TRANSMITTING":
            return 0.0, 0.0
        pps = bps = 0.0
        for f in self._flows[pid]:
            if f.get("paused"):
                continue
            r = f["pps"] * (1 + 0.1 * math.sin(now / 5 + pid)) if f.get("wobble") else f["pps"]
            pps += r
            bps += r * f["bytes"] * 8
        return pps, bps

    def op_stats(self):
        self._require_connected()
        self._expire()
        now = self._last
        tx = {p["id"]: self._tx(p["id"], now) for p in self._ports}
        ports = {}
        total = dict.fromkeys(("tx_bps", "rx_bps", "tx_pps", "rx_pps"), 0.0)
        for p in self._ports:
            pid = p["id"]
            tx_pps, tx_bps = tx[pid]
            peer = pid ^ 1
            ratio = self._delivered(peer)
            rx_pps, rx_bps = (x * ratio for x in tx.get(peer, (0.0, 0.0)))
            c = self._counters[pid]
            base = self._baseline[pid]
            line = p["speed_gbps"] * 1e9
            l1_extra = tx_pps * (LINE_OVERHEAD + 4) * 8  # tx_bps excludes FCS
            ports[pid] = {
                **{k: int(c[k] - base[k]) for k in c},
                "oerrors": 0,
                "ierrors": 0,
                "tx_bps": tx_bps,
                "tx_pps": tx_pps,
                "tx_bps_L1": tx_bps + l1_extra,
                "tx_util": (tx_bps + l1_extra) / line * 100,
                "rx_bps": rx_bps,
                "rx_pps": rx_pps,
                "rx_bps_L1": rx_bps + rx_pps * (LINE_OVERHEAD + 4) * 8,
                "rx_util": (rx_bps + rx_pps * (LINE_OVERHEAD + 4) * 8) / line * 100,
            }
            total["tx_bps"] += tx_bps
            total["rx_bps"] += rx_bps
            total["tx_pps"] += tx_pps
            total["rx_pps"] += rx_pps
        pgids = self._pg_stats(now)
        busy = sum(1 for p in self._ports if p["status"] == "TRANSMITTING")
        states = {p["id"]: {"status": p["status"], "owner": p["owner"], "acquired": p["owner"] == self._username}
                  for p in self._ports}
        return {"global": {"cpu_util": min(100.0, 3 + 6 * busy), **total}, "ports": ports, "port_states": states,
                "pgids": pgids, "pg_global": {"rx_err": 0, "tx_err": 0, "old_flow": 0, "bad_hdr": 0},
                "events": self._state_events(states)}

    def _state_events(self, states: dict) -> list:
        """TRex-style async events, made up by diffing port states between polls."""
        prev, self._prev_states = getattr(self, "_prev_states", None), states
        if prev is None:
            return []
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        verbs = {"TRANSMITTING": "started", "IDLE": "stopped", "PAUSE": "paused"}
        out = []
        for pid, now in states.items():
            was = prev.get(pid, now)
            if now["status"] != was["status"]:
                verb = "resumed" if was["status"] == "PAUSE" and now["status"] == "TRANSMITTING" else verbs.get(now["status"], now["status"])
                out.append({"ts": ts, "origin": "server", "level": "info", "message": f"Port {pid} has {verb}"})
            if now["owner"] != was["owner"]:
                msg = f"Port {pid} was acquired by '{now['owner']}'" if now["owner"] else f"Port {pid} was released by '{was['owner']}'"
                out.append({"ts": ts, "origin": "server", "level": "info", "message": msg})
        return out

    def op_monitor_extra(self, cpu=False, xstats=False):
        self._require_connected()
        busy = [p["id"] for p in self._ports if p["status"] == "TRANSMITTING"]
        out = {}
        if cpu:
            out["cpu"] = [{"ports": [i % len(self._ports), (i + 1) % len(self._ports)] if busy else [-1, -1],
                           "history": [min(100, int(len(busy) * 6 + random.random() * 5)) for _ in range(20)]}
                          for i in range(14)]
            out["mbuf"] = {"cpu-socket-0": {size: {"used": int(total * (0.02 + 0.1 * bool(busy))), "total": total}
                                            for size, total in (("64b", 106470), ("128b", 53235), ("2048b", 42997), ("9kb", 22656))}}
        if xstats:
            out["xstats"] = {p["id"]: {"rx_good_packets": int(self._counters[p["id"]]["ipackets"]),
                                       "tx_good_packets": int(self._counters[p["id"]]["opackets"]),
                                       "rx_missed_errors": 0, "rx_errors": 0, "tx_errors": 0}
                             for p in self._ports}
        return out

    def _pg_stats(self, now) -> dict:
        rates = {pg: [0.0, 0.0] for pg in self._pg}
        for p in self._ports:
            pid = p["id"]
            if p["status"] != "TRANSMITTING":
                continue
            ratio = self._delivered(pid)
            for f in self._flows[pid]:
                if f.get("pg") is None or f.get("paused"):
                    continue
                rates[f["pg"]][0] += f["pps"]
                rates[f["pg"]][1] += f["pps"] * ratio
        out = {}
        for pg_id, pg in self._pg.items():
            tx, rx = sum(pg["tx"].values()), sum(pg["rx"].values())
            entry = {
                "tx_pkts": int(tx), "rx_pkts": int(rx), "tx_pps": rates[pg_id][0], "rx_pps": rates[pg_id][1],
                "tx_ports": {k: int(v) for k, v in pg["tx"].items()}, "rx_ports": {k: int(v) for k, v in pg["rx"].items()},
                "latency": None,
            }
            if pg["type"] == "latency":
                avg = 5 + math.sin(now / 7 + pg_id)
                entry["latency"] = {
                    "average": round(avg, 1), "total_min": 2, "total_max": 31, "last_max": round(avg * 1.8),
                    "jitter": 1, "histogram": {1: int(rx * 0.1), 2: int(rx * 0.6), 5: int(rx * 0.29), 10: int(rx * 0.01)},
                    "dropped": int(tx - rx), "out_of_order": 0, "dup": 0, "seq_too_high": 0, "seq_too_low": 0,
                }
            out[pg_id] = entry
        return out

    DUT_CAPACITY = 0.85  # pretend device under test: forwards up to 85 % of line rate

    def _delivered(self, pid):
        """Share of what port `pid` sends that reaches its peer through the pretend DUT."""
        if self._ports[pid]["status"] != "TRANSMITTING":
            return 1.0
        line = self._ports[pid]["speed_gbps"] * 1e9
        l1 = sum(f["pps"] * (f["bytes"] + 4 + LINE_OVERHEAD) * 8 for f in self._flows[pid] if not f.get("paused"))
        util = l1 / line if line else 0
        return 1.0 if util <= self.DUT_CAPACITY else self.DUT_CAPACITY / util

    # --- per-stream control, push, namespaces (same interface as worker.TRexAdapter) ---

    def op_stream_control(self, port, stream_ids, action, mult=None):
        self._require_connected()
        self._expire()
        self._require_owned([port])
        flows = {f["id"]: f for f in self._flows.get(port, [])}
        if any(s not in flows for s in stream_ids):
            raise RuntimeError("these streams are not running on TRex; press Start first")
        for sid in stream_ids:
            f = flows[sid]
            if action == "pause":
                f["paused"] = True
            elif action == "resume":
                f["paused"] = False
            elif action == "update":
                f["pps"] = _to_pps_mult(mult, f["base_pps"], f["bytes"] + 4, self._ports[port]["speed_gbps"])
            else:
                raise RuntimeError(f"unknown stream action {action!r}")
        return self.op_stream_states(port)

    def op_stream_states(self, port):
        flows = self._flows.get(port, []) if self._ports[port]["status"] != "IDLE" else []
        return {"running": bool(flows), "on_trex": sorted(f["id"] for f in self._flows.get(port, []) if f["id"]),
                "paused": sorted(f["id"] for f in flows if f.get("paused"))}

    def op_push_packet(self, port, packet, count=1, ipg_usec=0.0):
        self._require_connected()
        self._expire()
        self._require_owned([port])
        if not 1 <= int(count) <= 1000:
            raise RuntimeError("count must be 1..1000")
        size = len(bytes(self.catalog().build(packet)))
        self._counters[port]["opackets"] += int(count)
        self._counters[port]["obytes"] += int(count) * size
        self._counters[port ^ 1]["ipackets"] += int(count)
        self._counters[port ^ 1]["ibytes"] += int(count) * size
        return {"sent": int(count), "bytes": size}

    def op_service_mode(self, port, mode):
        self._require_connected()
        self._require_owned([port])
        if mode not in ("off", "filtered", "on"):
            raise RuntimeError("service mode must be off, filtered or on")
        self._layer[port]["service"] = mode
        return self.op_ports()

    def op_ns_nodes(self, port):
        self._require_connected()
        return [dict(n) for n in getattr(self, "_ns", {}).get(port, {}).values()]

    def op_ns_add(self, port, mac, ipv4=None, dg=None, ipv6=False, vlans=None, mtu=None):
        self._require_connected()
        self._require_owned([port])
        if ipv4 and not dg:
            raise RuntimeError("an IPv4 node needs a default gateway")
        nodes = self.__dict__.setdefault("_ns", {}).setdefault(port, {})
        if mac.lower() in nodes:
            raise RuntimeError(f"node {mac} already exists")
        nodes[mac.lower()] = {"ether": {"src": mac.lower()}, "vlan": {"tags": [int(v) for v in vlans or []]},
                              "ipv4": {"src": ipv4 or "", "dst": dg or ""},
                              "ipv6": {"enabled": bool(ipv6)}}
        return self.op_ns_nodes(port)

    def op_ns_remove(self, port, macs):
        self._require_connected()
        self._require_owned([port])
        for m in macs:
            getattr(self, "_ns", {}).get(port, {}).pop(m.lower(), None)
        return self.op_ns_nodes(port)

    def close(self):
        pass


def _to_pps_mult(mult, base_pps, frame_len, speed_gbps):
    """A stream's new rate from an update multiplier: '2' (x base), '50%' of line, '10kpps', '1gbps'."""
    m = str(mult or "1").strip().lower()
    units = {"kpps": 1e3, "mpps": 1e6, "pps": 1, "kbps": 1e3, "mbps": 1e6, "gbps": 1e9, "bps": 1}
    for suffix in sorted(units, key=len, reverse=True):
        if m.endswith(suffix):
            v = float(m[: -len(suffix)]) * units[suffix]
            return v if "pps" in suffix else v / ((frame_len + LINE_OVERHEAD) * 8)
    if m.endswith("%"):
        return float(m[:-1]) / 100 * speed_gbps * 1e9 / ((frame_len + LINE_OVERHEAD) * 8)
    return base_pps * float(m)


def _to_pps(rate: dict, frame_len: int, speed_gbps: float) -> float:
    unit, value = rate.get("unit", "pps"), float(rate.get("value", 1))
    l1_bits = (frame_len + LINE_OVERHEAD) * 8
    if unit == "pps":
        return value
    if unit == "bps_L2":
        return value / (frame_len * 8)
    if unit == "bps_L1":
        return value / l1_bits
    return speed_gbps * 1e9 * value / 100 / l1_bits  # percentage


_ABS_MULT = re.compile(r"([\d.]+)\s*([kmg]?)(pps|bps)", re.I)


def _mult_factor(mult, flows, speed_gbps: float) -> float:
    """TRex-style multiplier: '2' (x2), '50%' (of line rate), '10kpps', '5gbps'."""
    text = str(mult).strip().lower()
    base_pps = sum(f["pps"] for f in flows) or 1.0
    base_l1 = sum(f["pps"] * (f["bytes"] + 4 + LINE_OVERHEAD) * 8 for f in flows) or 1.0
    if text.endswith("%"):
        return speed_gbps * 1e9 * float(text[:-1]) / 100 / base_l1
    m = _ABS_MULT.fullmatch(text)
    if m:
        value = float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[m.group(2)]
        return value / (base_pps if m.group(3) == "pps" else base_l1)
    return float(text.rstrip("x"))
