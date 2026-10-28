"""Two TRex hosts controlled by one GUI backend, ports cabled across: <host> p0 <-> <peer> p0
and <host> p1 <-> <peer> p1. Runs only when TREX_GUI_PEER names the second host.

    TREX_GUI_URL=http://<gui-host>:8080 TREX_GUI_HOST=local TREX_GUI_PEER=<second-host-id> \\
        backend/.venv/bin/python -m pytest tests/backend/test_cross_host.py
"""
import os
import time

import pytest

from conftest import HOST, UDP, Api, read_pcap, stream, wait_idle

PEER = os.environ.get("TREX_GUI_PEER")
pytestmark = pytest.mark.skipif(not PEER, reason="set TREX_GUI_PEER to the second host's id")


@pytest.fixture(scope="module")
def two(server):
    a, b = Api(server, HOST), Api(server, PEER)
    for x in (a, b):
        x.h("POST", "/connect")
        x.h("POST", "/ports/acquire", {"ports": [0, 1], "force": True})
    before = {x.host: {p["id"]: p["layer"] for p in x.h("GET", "/ports")} for x in (a, b)}
    ma = {p["id"]: p["layer"]["src_mac"] for p in a.h("GET", "/ports")}
    mb = {p["id"]: p["layer"]["src_mac"] for p in b.h("GET", "/ports")}
    for p in (0, 1):
        a.h("POST", f"/ports/{p}/config", {"l2": {"dst_mac": mb[p]}})
        b.h("POST", f"/ports/{p}/config", {"l2": {"dst_mac": ma[p]}})
    yield a, b
    for x in (a, b):
        x.h("POST", "/traffic/reset", {"ports": [0, 1]})
        for p, lay in before[x.host].items():
            cfg = {"l3": {"src": lay["ipv4_src"], "dst": lay["ipv4_dst"]}} if lay["mode"] == "L3" else {"l2": {"dst_mac": lay["dst_mac"]}}
            x.h("POST", f"/ports/{p}/config", cfg)
            x.h("PUT", f"/ports/{p}/streams", {"streams": []})
        x.h("POST", "/ports/release", {"ports": [0, 1]})


def test_traffic_both_ways_on_both_pairs(two):
    a, b = two
    for x in (a, b):
        for p in (0, 1):
            x.h("PUT", f"/ports/{p}/streams", {"streams": [stream("x", rate=200_000, size=256)]})
        x.h("POST", "/stats/clear", {"ports": [0, 1]})
    for x in (a, b):
        x.h("POST", "/traffic/start", {"ports": [0, 1], "duration": 3, "force": True})
    for x in (a, b):
        wait_idle(x, [0, 1], 20)
    sa, sb = a.port_stats(), b.port_stats()
    for p in ("0", "1"):
        assert sa[p]["opackets"] == pytest.approx(600_000, rel=0.02)
        assert sb[p]["ipackets"] == sa[p]["opackets"], (p, sa[p]["opackets"], sb[p]["ipackets"])
        assert sa[p]["ipackets"] == sb[p]["opackets"], (p, sb[p]["opackets"], sa[p]["ipackets"])


def test_remote_capture_comes_back(two):
    """Capture on the peer: packets travel back over RPC into this backend's library."""
    a, b = two
    cap = b.h("POST", "/captures", {"rx_ports": [0], "limit": 100, "service": True})
    a.h("PUT", "/ports/0/streams", {"streams": [stream("c", rate=1000, size=128, mode={"type": "single_burst", "total_pkts": 25},
                                                       payload={"type": "text", "value": "cross"})]})
    a.h("POST", "/traffic/start", {"ports": [0], "force": True})
    wait_idle(a, [0], 10)
    time.sleep(1)
    meta = b.h("POST", f"/captures/{cap['id']}/stop", {"name": "pytest cross"})
    try:
        frames = [f for f in read_pcap(a.raw("GET", f"/pcaps/{meta['id']}/download").content) if b"crosscross" in f]
        assert len(frames) == 25
    finally:
        a.call("DELETE", f"/pcaps/{meta['id']}")
    assert {p["id"]: p for p in b.h("GET", "/ports")}[0]["layer"]["service"] == "off"


def test_single_packets_to_peer(two):
    a, b = two
    b.h("POST", "/stats/clear", {"ports": [1]})
    a.h("POST", "/ports/1/push", {"packet": {"layers": UDP, "frame_size": 100}, "count": 7})
    assert b.port_stats()["1"]["ipackets"] == 7
