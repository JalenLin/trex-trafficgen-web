"""PCAP library, preview, conversion to streams, replay and capture."""
import time

import pytest

from conftest import REAL, ApiError, pcap_bytes, read_pcap, wait_idle


def frame(i: int, size: int = 100) -> bytes:
    """Ether/IPv4/UDP with a valid IP checksum, source IP varying with i."""
    ip_len = size - 14
    hdr = bytearray(b"\x45\x00" + ip_len.to_bytes(2, "big") + b"\x00\x01\x00\x00\x40\x11\x00\x00" +
                    bytes([10, 1, 0, i % 250 + 1]) + bytes([10, 2, 0, 1]))
    s = sum(int.from_bytes(hdr[j:j + 2], "big") for j in range(0, 20, 2))
    s = (s & 0xFFFF) + (s >> 16)
    hdr[10:12] = (~s & 0xFFFF).to_bytes(2, "big")
    udp = (1000 + i).to_bytes(2, "big") + (2000).to_bytes(2, "big") + (ip_len - 20).to_bytes(2, "big") + b"\x00\x00"
    eth = bytes.fromhex("02000000000a" "02000000000b" "0800")
    return eth + bytes(hdr) + udp + bytes(ip_len - 28)


@pytest.fixture
def pcap(api):
    frames = [frame(i) for i in range(20)]
    meta = api.call("POST", "/pcaps", params={"name": "pytest.pcap"}, content=pcap_bytes(frames, gap_us=1000))
    yield meta, frames
    try:
        api.call("DELETE", f"/pcaps/{meta['id']}")
    except ApiError:
        pass


def test_upload_list_download_rename(api, pcap):
    meta, frames = pcap
    assert meta["packets"] == 20
    assert any(p["id"] == meta["id"] for p in api.call("GET", "/pcaps"))
    data = api.raw("GET", f"/pcaps/{meta['id']}/download").content
    assert read_pcap(data) == frames
    renamed = api.call("POST", f"/pcaps/{meta['id']}/rename", {"name": "renamed"})
    assert renamed["name"] == "renamed"


def test_reject_non_pcap(api):
    with pytest.raises(ApiError) as e:
        api.call("POST", "/pcaps", params={"name": "junk.pcap"}, content=b"this is not a capture file at all")
    assert e.value.status == 400


def test_pcapng_upload_is_converted(api):
    # Minimal pcapng: SHB, IDB (Ethernet), one EPB.
    import struct
    f = frame(1)
    shb_body = struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
    shb = struct.pack("<II", 0x0A0D0D0A, 12 + len(shb_body)) + shb_body + struct.pack("<I", 12 + len(shb_body))
    idb_body = struct.pack("<HHI", 1, 0, 65535)
    idb = struct.pack("<II", 1, 12 + len(idb_body)) + idb_body + struct.pack("<I", 12 + len(idb_body))
    pad = (-len(f)) % 4
    epb_body = struct.pack("<IIIII", 0, 0, 0, len(f), len(f)) + f + b"\0" * pad
    epb = struct.pack("<II", 6, 12 + len(epb_body)) + epb_body + struct.pack("<I", 12 + len(epb_body))
    meta = api.call("POST", "/pcaps", params={"name": "x.pcapng"}, content=shb + idb + epb)
    try:
        assert meta["packets"] == 1
        assert read_pcap(api.raw("GET", f"/pcaps/{meta['id']}/download").content) == [f]
    finally:
        api.call("DELETE", f"/pcaps/{meta['id']}")


def test_preview_and_to_streams(api, pcap):
    meta, frames = pcap
    pk = api.h("GET", f"/pcaps/{meta['id']}/packets", params={"start": 0, "count": 5})
    items = pk["packets"] if isinstance(pk, dict) else pk
    assert len(items) == 5
    streams = api.h("POST", f"/pcaps/{meta['id']}/to-streams", {"indices": [0, 3]})
    assert len(streams) == 2
    # A converted stream builds back to exactly the original bytes.
    d = api.h("POST", "/packet", {"packet": streams[1]["packet"]})
    assert bytes.fromhex(d["hex"]) == frames[3]


def test_replay_to_loopback(api, l2_loop, pcap):
    tx, rx = l2_loop
    meta, _ = pcap
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    api.h("POST", "/traffic/push", {"pcap_id": meta["id"], "ports": [tx], "count": 3, "ipg_usec": 100, "force": True})
    wait_idle(api, [tx], 20)
    s = api.port_stats()
    assert s[str(tx)]["opackets"] == 60 and s[str(rx)]["ipackets"] == 60


def test_replay_rejects_both_gap_options(api, l2_loop, pcap):
    with pytest.raises(ApiError):
        api.h("POST", "/traffic/push", {"pcap_id": pcap[0]["id"], "ports": [l2_loop[0]], "ipg_usec": 10, "min_ipg_usec": 5})


@pytest.mark.skipif(not REAL, reason="the mock does not capture replayed pcaps")
def test_capture_tx_and_rx_with_service_mode(api, l2_loop, pcap):
    tx, rx = l2_loop
    meta, frames = pcap
    cap = api.h("POST", "/captures", {"tx_ports": [tx], "rx_ports": [rx], "limit": 100, "service": True})
    assert any(c["id"] == cap["id"] for c in api.h("GET", "/captures"))
    api.h("POST", "/traffic/push", {"pcap_id": meta["id"], "ports": [tx], "count": 1, "ipg_usec": 100, "force": True})
    wait_idle(api, [tx], 20)
    time.sleep(1)
    saved = api.h("POST", f"/captures/{cap['id']}/stop", {"name": "pytest capture"})
    try:
        got = read_pcap(api.raw("GET", f"/pcaps/{saved['id']}/download").content)
        # Replay puts the port's own MACs on the frames; the rest is unchanged.
        body = [f[12:] for f in frames]
        assert sum(f[12:] in body for f in got) == 40, len(got)  # 20 seen leaving tx + 20 arriving at rx
    finally:
        api.call("DELETE", f"/pcaps/{saved['id']}")
    # Service mode goes back to what the ports had before the capture.
    lay = {p["id"]: p["layer"] for p in api.h("GET", "/ports")}
    assert lay[tx]["service"] == "off" and lay[rx]["service"] == "off"


def test_capture_keeps_users_service_mode(api, l2_loop):
    tx, rx = l2_loop
    api.h("POST", f"/ports/{rx}/service", {"mode": "on"})
    try:
        cap = api.h("POST", "/captures", {"rx_ports": [rx], "limit": 10, "service": True})
        api.h("POST", f"/captures/{cap['id']}/stop", {"save": False})
        assert {p["id"]: p for p in api.h("GET", "/ports")}[rx]["layer"]["service"] == "on"
    finally:
        api.h("POST", f"/ports/{rx}/service", {"mode": "off"})


@pytest.mark.skipif(not REAL, reason="the mock does not capture replayed pcaps")
def test_capture_bpf_filter(api, l2_loop, pcap):
    tx, rx = l2_loop
    meta, frames = pcap
    cap = api.h("POST", "/captures", {"rx_ports": [rx], "limit": 100, "service": True, "bpf_filter": "udp src port 1005"})
    api.h("POST", "/traffic/push", {"pcap_id": meta["id"], "ports": [tx], "count": 1, "ipg_usec": 100, "force": True})
    wait_idle(api, [tx], 20)
    time.sleep(1)
    saved = api.h("POST", f"/captures/{cap['id']}/stop", {"name": "pytest bpf"})
    try:
        got = read_pcap(api.raw("GET", f"/pcaps/{saved['id']}/download").content)
        assert [f[12:] for f in got] == [frames[5][12:]], len(got)
    finally:
        api.call("DELETE", f"/pcaps/{saved['id']}")


def test_capture_start_list_discard(api, l2_loop):
    tx, rx = l2_loop
    cap = api.h("POST", "/captures", {"tx_ports": [tx], "rx_ports": [rx], "limit": 10, "mode": "cyclic"})
    assert any(c["id"] == cap["id"] for c in api.h("GET", "/captures"))
    assert api.h("POST", f"/captures/{cap['id']}/stop", {"save": False}) is None
    assert all(c["id"] != cap["id"] for c in api.h("GET", "/captures"))


def test_capture_needs_a_port(api, pair):
    with pytest.raises(ApiError) as e:
        api.h("POST", "/captures", {})
    assert e.value.status == 400
