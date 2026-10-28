"""Sending traffic over the loopback pair: streams, transmit modes, rates, control, flow stats,
latency, per-stream control, single packets, and what actually goes on the wire."""
import time
from collections import Counter

import pytest

from conftest import REAL, UDP, ApiError, read_pcap, stream, wait_idle

# A real loopback loses nothing at these rates; the mock DUT model is lossless below 85%.
LOSS = 0.0 if REAL else 0.002


def put(api, port, *streams):
    api.h("PUT", f"/ports/{port}/streams", {"streams": list(streams)})


def counters(api, tx, rx):
    s = api.port_stats()
    return s[str(tx)]["opackets"], s[str(rx)]["ipackets"]


def assert_delivered(sent, got, expect=None):
    if expect is not None:
        assert sent == pytest.approx(expect, rel=0.01 if not REAL else 0), (sent, expect)
    assert got >= sent * (1 - LOSS) and got <= sent * 1.0001 + 5, (sent, got)


def test_streams_saved_and_listed(api, pair):
    tx, _ = pair
    put(api, tx, stream("a"), stream("b", enabled=False))
    got = api.h("GET", f"/ports/{tx}/streams")
    assert [s["id"] for s in got] == ["a", "b"]
    with pytest.raises(ApiError):
        put(api, tx, stream("dup"), stream("dup"))


def test_single_stream_starts(api, l2_loop):
    """Regression: TRex returns an int, not a list, for one stream."""
    tx, rx = l2_loop
    put(api, tx, stream("only", rate=1000))
    api.h("POST", "/traffic/start", {"ports": [tx]})
    assert {p["id"]: p for p in api.h("GET", "/ports")}[tx]["status"] == "TRANSMITTING"
    api.h("POST", "/traffic/stop", {"ports": [tx]})


def test_single_burst_exact_count(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("burst", rate=10_000, mode={"type": "single_burst", "total_pkts": 5000}))
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    api.h("POST", "/traffic/start", {"ports": [tx]})
    wait_idle(api, [tx])
    sent, got = counters(api, tx, rx)
    assert_delivered(sent, got, 5000)


def test_multi_burst_count(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("mb", rate=10_000, mode={"type": "multi_burst", "pkts_per_burst": 100, "count": 7, "ibg_usec": 1000}))
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    api.h("POST", "/traffic/start", {"ports": [tx]})
    wait_idle(api, [tx])
    sent, got = counters(api, tx, rx)
    assert_delivered(sent, got, 700)


def test_disabled_stream_not_sent(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("on", rate=10_000, mode={"type": "single_burst", "total_pkts": 1000}),
        stream("off", rate=10_000, mode={"type": "single_burst", "total_pkts": 1000}, enabled=False))
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    api.h("POST", "/traffic/start", {"ports": [tx]})
    wait_idle(api, [tx])
    sent, _ = counters(api, tx, rx)
    assert sent == pytest.approx(1000, rel=0.01 if not REAL else 0)


def test_rate_units_and_multiplier(api, l2_loop):
    tx, rx = l2_loop
    for unit, value, mult, expect_pps in [("pps", 20_000, "1", 20_000), ("pps", 10_000, "2", 20_000),
                                          ("bps_L2", 128 * 8 * 20_000, "1", 20_000), ("pps", 1000, "20kpps", 20_000)]:
        put(api, tx, stream("r", rate=value, unit=unit, size=128))
        api.h("POST", "/traffic/start", {"ports": [tx], "mult": mult, "force": True})
        time.sleep(1)
        pps = api.measure_pps(tx)
        assert pps == pytest.approx(expect_pps, rel=0.03), (unit, value, mult, pps)
    api.h("POST", "/traffic/stop", {"ports": [tx]})


def test_percent_of_line_rate(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("pct", rate=1, unit="percentage", size=1518))
    api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    time.sleep(1)
    l1_bps = api.measure_pps(tx) * (1518 + 20) * 8  # + preamble and inter-frame gap
    speed = {x["id"]: x for x in api.h("GET", "/ports")}[tx]["speed_gbps"]
    assert l1_bps == pytest.approx(speed * 1e9 * 0.01, rel=0.03)
    api.h("POST", "/traffic/stop", {"ports": [tx]})


def test_pause_resume_update_stop(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("c", rate=10_000))
    api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    api.h("POST", "/traffic/pause", {"ports": [tx]})
    assert {p["id"]: p for p in api.h("GET", "/ports")}[tx]["status"] == "PAUSE"
    a = api.port_stats()[str(tx)]["opackets"]
    time.sleep(1.5)
    assert api.port_stats()[str(tx)]["opackets"] - a < 100  # nothing sent while paused
    api.h("POST", "/traffic/resume", {"ports": [tx]})
    api.h("POST", "/traffic/update", {"ports": [tx], "mult": "3"})
    time.sleep(1)
    assert api.measure_pps(tx) == pytest.approx(30_000, rel=0.03)
    api.h("POST", "/traffic/stop", {"ports": [tx]})
    wait_idle(api, [tx], 5)


def test_duration_stops_by_itself(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("d", rate=1000))
    api.h("POST", "/traffic/start", {"ports": [tx], "duration": 2, "force": True})
    time.sleep(1)
    assert {p["id"]: p for p in api.h("GET", "/ports")}[tx]["status"] == "TRANSMITTING"
    wait_idle(api, [tx], 10)


def test_start_on_running_port_needs_force(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("f", rate=1000))
    api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    with pytest.raises(ApiError):
        api.h("POST", "/traffic/start", {"ports": [tx]})
    api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    api.h("POST", "/traffic/stop", {"ports": [tx]})


def test_reset_clears_streams_on_trex_and_stats(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("x", rate=1000))
    api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    time.sleep(1)
    api.h("POST", "/traffic/reset", {"ports": [tx, rx]})
    wait_idle(api, [tx], 5)
    assert api.h("GET", f"/ports/{tx}/streams/state")["on_trex"] == []
    assert api.port_stats()[str(tx)]["opackets"] < 100
    assert {p["id"]: p for p in api.h("GET", "/ports")}[tx]["acquired"]


def test_bidirectional_line_rate_mix(api, l2_loop):
    """Both directions at once, several streams each, counters match per direction."""
    tx, rx = l2_loop
    put(api, tx, stream("a", rate=50_000, size=64), stream("b", rate=20_000, size=1518))
    put(api, rx, stream("c", rate=30_000, size=512))
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    api.h("POST", "/traffic/start", {"ports": [tx, rx], "duration": 3, "force": True})
    wait_idle(api, [tx, rx], 15)
    s = api.port_stats()
    for a, b in ((tx, rx), (rx, tx)):
        assert_delivered(s[str(a)]["opackets"], s[str(b)]["ipackets"])
    assert s[str(tx)]["opackets"] == pytest.approx(70_000 * 3, rel=0.03)


def test_flow_stats_and_latency(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("fs", rate=10_000, pg=51, pg_type="stats", size=128),
        stream("lat", rate=1000, pg=52, pg_type="latency", size=128))
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    api.h("POST", "/traffic/start", {"ports": [tx], "duration": 3, "force": True})
    wait_idle(api, [tx], 15)
    time.sleep(1)
    pg = api.stats(fresh_after=time.time() + 1)["pgids"]
    fs, lat = pg["51"], pg["52"]
    assert fs["tx_pkts"] == pytest.approx(30_000, rel=0.03)
    if REAL and fs["rx_pkts"] == 0 and api.port_stats()[str(rx)]["ipackets"] >= fs["tx_pkts"]:
        # Seen on e300 (X557, net_ixgbe, TRex v3.08): the packets arrive but TRex's RX
        # never counts pg ids; the same happens with TRex's own client.
        pytest.xfail("TRex does not count flow stats / latency RX on this NIC")
    assert fs["rx_pkts"] >= fs["tx_pkts"] * (1 - LOSS)
    assert str(rx) in {str(k) for k in fs["rx_ports"]}
    L = lat["latency"]
    assert L and L["average"] and L["total_max"] >= L["total_min"] >= 0
    assert L["dropped"] == 0 and L["out_of_order"] == 0
    assert lat["rx_pkts"] == pytest.approx(3000, rel=0.03)


@pytest.mark.skipif(not REAL, reason="TRex itself enforces this; the mock doesn't")
def test_latency_pg_id_must_be_unique(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("l1", pg=60, pg_type="latency"), stream("l2", pg=60, pg_type="latency"))
    with pytest.raises(ApiError):
        api.h("POST", "/traffic/start", {"ports": [tx], "force": True})


def test_per_stream_pause_resume_rate(api, l2_loop):
    tx, rx = l2_loop
    put(api, tx, stream("A", rate=20_000, pg=71), stream("B", rate=20_000, pg=72))
    api.h("POST", "/traffic/start", {"ports": [tx], "force": True})

    def rates():
        time.sleep(2.5)
        pg = api.stats(fresh_after=time.time() + 1)["pgids"]
        return pg["71"]["tx_pps"], pg["72"]["tx_pps"]

    api.h("POST", f"/ports/{tx}/streams/control", {"stream_ids": ["A"], "action": "pause"})
    a, b = rates()
    assert a < 500 and b == pytest.approx(20_000, rel=0.05)
    assert "A" in api.h("GET", f"/ports/{tx}/streams/state")["paused"]
    api.h("POST", f"/ports/{tx}/streams/control", {"stream_ids": ["B"], "action": "update", "mult": "50kpps"})
    a, b = rates()
    assert b == pytest.approx(50_000, rel=0.05)
    api.h("POST", f"/ports/{tx}/streams/control", {"stream_ids": ["A"], "action": "resume"})
    a, b = rates()
    assert a == pytest.approx(20_000, rel=0.05)
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{tx}/streams/control", {"stream_ids": ["A"], "action": "explode"})
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{tx}/streams/control", {"stream_ids": ["A"], "action": "update"})
    api.h("POST", "/traffic/stop", {"ports": [tx]})


def test_push_single_packets(api, l2_loop):
    tx, rx = l2_loop
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    r = api.h("POST", f"/ports/{tx}/push", {"packet": {"layers": UDP, "frame_size": 100}, "count": 10, "ipg_usec": 100})
    assert r["sent"] == 10 and r["bytes"] == 96
    sent, got = counters(api, tx, rx)
    assert sent == 10 and got == 10


# --- on the wire (captured on the receiving port) -----------------------------
# The mock's capture is only a rough copy of the stream template, so these run on real TRex.
wire = pytest.mark.skipif(not REAL, reason="checks real packets on the wire")

def capture_rx(api, rx, start_traffic, limit=500, bpf=""):
    cap = api.h("POST", "/captures", {"rx_ports": [rx], "limit": limit, "service": True, "bpf_filter": bpf})
    try:
        start_traffic()
        time.sleep(2)
    finally:
        meta = api.h("POST", f"/captures/{cap['id']}/stop", {"name": "pytest wire"})
    data = api.raw("GET", f"/pcaps/{meta['id']}/download").content
    api.call("DELETE", f"/pcaps/{meta['id']}")
    # Only the test's own IPv4/UDP frames to 48.0.0.1 (a switch's discovery broadcasts may show up too).
    return [f for f in read_pcap(data) if f[12:14] == b"\x08\x00" and f[23] == 17 and f[30:34] == bytes([48, 0, 0, 1])]


def burst(api, tx, s):
    def go():
        put(api, tx, s)
        api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    return go


@wire
def test_wire_field_engine(api, l2_loop):
    """TRex spreads a stream over its DP cores, so the values interleave on the wire,
    but every value in the range is sent an equal number of times."""
    tx, rx = l2_loop
    vm = [{"layer": 1, "field": "src", "op": "inc", "start": "10.0.0.1", "end": "10.0.0.5"},
          {"layer": 2, "field": "dport", "op": "dec", "start": "1005", "end": "1001"}]
    s = stream("vm", rate=1000, mode={"type": "single_burst", "total_pkts": 100}, vm=vm)
    frames = capture_rx(api, rx, burst(api, tx, s))
    assert len(frames) == 100
    srcs = Counter(".".join(map(str, f[26:30])) for f in frames)
    assert srcs == {f"10.0.0.{i}": 20 for i in range(1, 6)}, srcs
    assert Counter(int.from_bytes(f[36:38], "big") for f in frames) == {p: 20 for p in range(1001, 1006)}
    for f in frames:  # IPv4 header checksum is valid after the change
        h = f[14:34]
        assert sum(int.from_bytes(h[i:i + 2], "big") for i in range(0, 20, 2)) % 0xFFFF == 0


@wire
@pytest.mark.parametrize("mode,lo,hi,step,n", [("inc", 100, 109, 1, 100), ("inc", 64, 1518, 7, 416), ("dec", 64, 1518, 100, 300)])
def test_wire_varying_size(api, l2_loop, mode, lo, hi, step, n):
    """Every size on the user's grid, in equal shares, and nothing else (regression: with
    the size variable not split across cores, a burst got the first sizes many times)."""
    tx, rx = l2_loop
    s = stream("sz", rate=2000, mode={"type": "single_burst", "total_pkts": n}, size_var={"mode": mode, "min": lo, "max": hi, "step": step})
    frames = capture_rx(api, rx, burst(api, tx, s), limit=n + 50)
    assert len(frames) == n
    grid = set(range(lo, hi + 1, step)) if mode == "inc" else set(range(hi, lo - 1, -step))
    sizes = Counter(len(f) + 4 for f in frames)  # captured without FCS
    assert set(sizes) == grid, sorted(set(sizes) ^ grid)[:10]
    assert max(sizes.values()) - min(sizes.values()) <= 1, sizes
    for f in frames:
        assert int.from_bytes(f[16:18], "big") == len(f) - 14  # IP total length follows the frame


@wire
def test_wire_payload_text(api, l2_loop):
    tx, rx = l2_loop
    s = stream("pl", rate=1000, mode={"type": "single_burst", "total_pkts": 10}, payload={"type": "text", "value": "TRex"})
    frames = capture_rx(api, rx, burst(api, tx, s))
    assert len(frames) == 10
    assert all(f[42:] == (b"TRex" * 40)[:len(f) - 42] for f in frames)
