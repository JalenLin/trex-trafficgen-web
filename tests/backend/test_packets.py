"""Protocol catalog, packet building, header checks, field engine and payload, through the
API, so they run against the Scapy of the host under test (pip's for mock, TRex's for real)."""
import random

import pytest

from conftest import UDP, ApiError, stream


def build(api, layers, frame=64, flow_stats=None, payload=None):
    packet = {"layers": [{"proto": l} if isinstance(l, str) else l for l in layers], "frame_size": frame}
    if payload:
        packet["payload"] = payload
    return api.h("POST", "/packet", {"packet": packet, "flow_stats": flow_stats})


def check(api, s):
    return api.h("POST", "/streams/check", {"stream": s})


def test_protocol_catalog(api):
    cat = api.h("GET", "/protocols")
    names = {p["id"] for p in cat["protocols"]}
    assert {"Ether", "IP", "UDP"} <= set(cat["common"])
    for p in ("Ether", "Dot1Q", "IP", "IPv6", "UDP", "TCP", "ICMP", "ARP", "VXLAN", "GRE", "MPLS"):
        assert p in names, p
    assert len(names) > 500


def test_protocol_schema(api):
    schema = api.h("GET", "/protocols/IP")
    fields = {f["name"] for f in schema["fields"]}
    assert {"src", "dst", "ttl", "proto", "len", "chksum"} <= fields


def test_build_describes_layers_and_hex(api):
    d = build(api, UDP, 64)
    assert [l["name"] for l in d["layers"] if not l["padding"]] == ["Ether", "IP", "UDP"]
    assert d["frame_length"] == 64 and len(bytes.fromhex(d["hex"])) == 60
    ip = next(l for l in d["layers"] if l["name"] == "IP")
    assert next(f for f in ip["fields"] if f["name"] == "src")["repr"] == "16.0.0.1"


CLEAN = [
    ("Ether/IP/UDP", ["Ether", "IP", "UDP"], 64, None),
    ("Ether/Dot1Q/IP/TCP", ["Ether", "Dot1Q", "IP", "TCP"], 128, None),
    ("QinQ", ["Ether", "Dot1AD", "Dot1Q", "IP", "UDP"], 64, None),
    ("MPLS x2", ["Ether", "MPLS", "MPLS", "IP", "UDP"], 64, None),
    ("GRE", ["Ether", "IP", "GRE", "IP", "UDP"], 128, None),
    ("VXLAN", ["Ether", "IP", "UDP", "VXLAN", "Ether", "IP", "TCP"], 128, None),
    ("GTP-U", ["Ether", "IP", "UDP", "GTP_U_Header", "IP", "UDP"], 128, None),
    ("GENEVE", ["Ether", "IP", "UDP", "GENEVE", "Ether", "IP"], 128, None),
    ("IPv6/ICMPv6", ["Ether", "IPv6", "ICMPv6EchoRequest"], 78, None),
    ("IPv6 frag", ["Ether", "IPv6", "IPv6ExtHdrFragment", "UDP"], 78, None),
    ("IPv6 HbH/TCP", ["Ether", "IPv6", "IPv6ExtHdrHopByHop", "TCP"], 128, None),
    ("ARP", ["Ether", "ARP"], 64, None),
    ("IP/ICMP", ["Ether", "IP", "ICMP"], 64, None),
    ("UDP/Raw", ["Ether", "IP", "UDP", {"proto": "Raw", "fields": {"load": "hi"}}], 64, None),
    ("latency IP/UDP 64", ["Ether", "IP", "UDP"], 64, "latency"),
    ("VLAN/IPv6/UDP", ["Ether", "Dot1Q", "IPv6", "UDP"], 128, None),
    ("VXLAN alt port 4790", ["Ether", "IP", {"proto": "UDP", "fields": {"dport": "4790"}}, "VXLAN", "Ether"], 128, None),
]

WARN = [
    ("Ether/UDP", ["Ether", "UDP"], 64, None),
    ("TCP before IP", ["Ether", "TCP", "IP"], 64, None),
    ("IPv6/ICMP", ["Ether", "IPv6", "ICMP"], 78, None),
    ("IP.proto=6 + UDP", ["Ether", {"proto": "IP", "fields": {"proto": "6"}}, "UDP"], 64, None),
    ("Ether.type=0x86dd + IP", [{"proto": "Ether", "fields": {"type": "0x86dd"}}, "IP", "UDP"], 64, None),
    ("Dot1Q.type=0x86dd + IP", ["Ether", {"proto": "Dot1Q", "fields": {"type": "0x86dd"}}, "IP", "UDP"], 64, None),
    ("IP.len=10", ["Ether", {"proto": "IP", "fields": {"len": "10"}}, "UDP"], 64, None),
    ("IP after Raw", ["Ether", "IP", "UDP", {"proto": "Raw", "fields": {"load": "x"}}, "IP"], 128, None),
    ("frame 40", ["Ether", "IP", "UDP"], 40, None),
    ("latency TCP 64B", ["Ether", "IP", "TCP"], 64, "latency"),
    ("stats on ARP", ["Ether", "ARP"], 64, "stats"),
]


def _stream_for(layers, frame, fs):
    s = stream(layers=[{"proto": l} if isinstance(l, str) else l for l in layers], size=frame)
    if fs:
        s["flow_stats"] = {"type": fs, "pg_id": 1}
    return s


@pytest.mark.parametrize("name,layers,frame,fs", CLEAN, ids=[c[0] for c in CLEAN])
def test_sensible_headers_have_no_warnings(api, name, layers, frame, fs):
    assert check(api, _stream_for(layers, frame, fs))["warnings"] == []


@pytest.mark.parametrize("name,layers,frame,fs", WARN, ids=[c[0] for c in WARN])
def test_odd_headers_warn_but_still_build(api, name, layers, frame, fs):
    ws = check(api, _stream_for(layers, frame, fs))["warnings"]
    assert ws, name
    for w in ws:  # warnings carry a code and params for the UI to translate
        assert w["code"] and isinstance(w.get("params", {}), dict)


@pytest.mark.parametrize("kind,value,expect", [
    ("zeros", "", lambda n: b"\0" * n),
    ("byte", "0xAA", lambda n: b"\xaa" * n),
    ("inc", "0x10", lambda n: bytes((0x10 + i) & 0xFF for i in range(n))),
    ("dec", "5", lambda n: bytes((5 - i) & 0xFF for i in range(n))),
    ("random", "42", lambda n: random.Random(42).randbytes(n)),
    ("text", "TRex", lambda n: (b"TRex" * n)[:n]),
    ("hex", "de:ad:be:ef", lambda n: (b"\xde\xad\xbe\xef" * n)[:n]),
])
def test_payload_fill(api, kind, value, expect):
    d = build(api, UDP, 128, payload={"type": kind, "value": value})
    data = bytes.fromhex(d["hex"])
    n = len(data) - 42  # Ether 14 + IP 20 + UDP 8
    assert data[42:] == expect(n)


@pytest.mark.parametrize("payload,needle", [
    ({"type": "byte", "value": "300"}, "0..255"),
    ({"type": "hex", "value": "zz"}, "hex"),
    ({"type": "text", "value": ""}, "text"),
    ({"type": "nope"}, "payload"),
])
def test_payload_errors(api, payload, needle):
    with pytest.raises(ApiError) as e:
        build(api, UDP, 128, payload=payload)
    assert e.value.status == 422 and needle in e.value.detail


def test_field_engine_plan(api):
    vm = [{"layer": 1, "field": "src", "op": "inc", "start": "16.0.0.1", "end": "16.0.0.10", "step": 1},
          {"layer": 0, "field": "src", "op": "random", "start": "00:00:00:00:00:01", "end": "00:00:00:00:00:ff"},
          {"layer": 2, "field": "sport", "op": "dec", "start": "2000", "end": "1000", "step": 10}]
    r = check(api, stream(vm=vm))
    assert r["warnings"] == []
    assert any(i["type"] == "var" for i in r["vm"])
    assert any("fix" in i["type"] or "checksum" in i["type"] for i in r["vm"]), r["vm"]


def test_field_engine_bit_field(api):
    layers = [{"proto": "Ether"}, {"proto": "Dot1Q", "fields": {"vlan": 10}}, {"proto": "IP"}, {"proto": "UDP"}]
    r = check(api, stream(layers=layers, vm=[{"layer": 1, "field": "vlan", "op": "inc", "start": "10", "end": "20"}]))
    assert r["vm"]


@pytest.mark.parametrize("row,needle", [
    ({"layer": 9, "field": "src", "start": "1.1.1.1"}, "not in the packet"),
    ({"layer": 1, "field": "nope", "start": "1"}, "no field"),
    ({"layer": 1, "field": "src", "start": "not-an-ip"}, "field engine row 1"),
])
def test_field_engine_errors(api, row, needle):
    with pytest.raises(ApiError) as e:
        check(api, stream(vm=[row]))
    assert e.value.status == 422 and needle in e.value.detail


@pytest.mark.parametrize("mode", ["inc", "dec", "random"])
def test_varying_frame_size(api, mode):
    r = check(api, stream(size_var={"mode": mode, "min": 64, "max": 1518, "step": 7}))
    assert any(i.get("type") == "var" for i in r["vm"])


@pytest.mark.parametrize("size,needle", [
    ({"mode": "inc", "min": 1000, "max": 100}, "min must be smaller"),
    ({"mode": "inc", "min": 64, "max": 10000}, "max is"),
    ({"mode": "inc", "min": 64, "max": 70, "step": 50}, "step is larger"),
    ({"mode": "wobble", "min": 64, "max": 128}, "unknown size mode"),
    ({"mode": "inc", "min": 20, "max": 128}, "smaller than the headers"),
])
def test_varying_frame_size_errors(api, size, needle):
    with pytest.raises(ApiError) as e:
        check(api, stream(size_var=size))
    assert needle in e.value.detail


@pytest.mark.parametrize("patch,needle", [
    ({"mode": {"type": "sometimes"}}, "unknown mode"),
    ({"rate": {"unit": "furlongs", "value": 1}}, "unknown rate unit"),
    ({"rate": {"unit": "pps", "value": 0}}, "greater than 0"),
    ({"flow_stats": {"type": "magic", "pg_id": 1}}, "unknown flow stats"),
])
def test_stream_validation(api, patch, needle):
    with pytest.raises(ApiError) as e:
        check(api, {**stream(), **patch})
    assert e.value.status == 422 and needle in e.value.detail
