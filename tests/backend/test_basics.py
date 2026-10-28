"""Hosts, connection, ports, ownership, event log, templates, port profiles, monitor settings."""
import time

import pytest

from conftest import HOST, PAIR, REAL, Api, ApiError


def test_host_list_and_summary(api):
    hosts = api.call("GET", "/hosts")
    me = next(h for h in hosts if h["id"] == HOST)
    assert me["connected"] is True
    assert api.h("GET", "")["id"] == HOST


def test_unknown_host_is_404(api):
    with pytest.raises(ApiError) as e:
        api.call("GET", "/hosts/no-such-host/ports")
    assert e.value.status == 404


@pytest.mark.skipif(REAL, reason="needs the unreachable host from the mock config")
def test_unreachable_host_reports_reason(server):
    far = Api(server, "far")
    with pytest.raises(ApiError) as e:
        far.h("POST", "/connect")
    assert e.value.status >= 400
    assert far.h("GET", "")["connected"] is False
    assert far.h("GET", "")["last_error"]


def test_ports_shape(api):
    ports = api.h("GET", "/ports")
    assert len(ports) >= 2
    for p in ports:
        for k in ("id", "speed_gbps", "link", "status", "owner", "acquired", "layer"):
            assert k in p, k
        for k in ("mode", "src_mac", "dst_mac", "vlan", "service"):
            assert k in p["layer"], k


def test_acquire_release_and_ownership(api, pair):
    ports = {p["id"]: p for p in api.h("GET", "/ports")}
    assert all(ports[p]["acquired"] for p in pair)
    # Releasing and acquiring again keeps working (the session fixture holds the pair afterwards).
    api.h("POST", "/ports/release", {"ports": [pair[1]]})
    assert not {p["id"]: p for p in api.h("GET", "/ports")}[pair[1]]["acquired"]
    api.h("POST", "/ports/acquire", {"ports": [pair[1]]})
    assert {p["id"]: p for p in api.h("GET", "/ports")}[pair[1]]["acquired"]


@pytest.mark.skipif(REAL, reason="mock ports 0/1 are held by another user")
def test_force_acquire_port_held_by_someone_else(api):
    with pytest.raises(ApiError):
        api.h("POST", "/ports/acquire", {"ports": [0]})
    api.h("POST", "/ports/acquire", {"ports": [0], "force": True})
    assert {p["id"]: p for p in api.h("GET", "/ports")}[0]["acquired"]
    api.h("POST", "/traffic/stop", {"ports": [0]})
    api.h("POST", "/ports/release", {"ports": [0]})


def test_actions_need_acquired_port(api):
    free = next((p["id"] for p in api.h("GET", "/ports") if not p["acquired"] and p["id"] not in PAIR), None)
    if free is None:
        pytest.skip("no spare port")
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{free}/config", {"promiscuous": True})


def test_event_log_records_gui_actions_with_client(api, pair):
    api.h("POST", "/stats/clear", {"ports": list(pair)})
    ev = api.h("GET", "/events")
    mine = [e for e in ev if e.get("source") == "gui" and e.get("code") == "clearStats"]
    assert mine, ev[-5:]
    assert mine[-1].get("client")


def test_stats_stream_shape(api, pair):
    m = api.stats()
    for k in ("global", "ports", "port_states", "pgids"):
        assert k in m, k
    assert str(pair[0]) in m["ports"]
    for k in ("opackets", "ipackets", "tx_pps", "rx_pps", "tx_bps", "rx_bps"):
        assert k in m["ports"][str(pair[0])], k


def test_unknown_host_stats_socket_closes(server):
    from websockets.sync.client import connect
    from websockets.exceptions import ConnectionClosed

    with pytest.raises((ConnectionClosed, Exception)):
        with connect(server.replace("http", "ws", 1) + "/api/hosts/nope/stats", open_timeout=5) as ws:
            ws.recv(timeout=5)


def test_templates_roundtrip(api):
    before = api.call("GET", "/templates")
    try:
        saved = api.call("PUT", "/templates", {"templates": [{"name": "t-test", "stream": {"name": "x"}}]})
        assert any(t["name"] == "t-test" for t in saved)
        assert any(t["name"] == "t-test" for t in api.call("GET", "/templates"))
    finally:
        api.call("PUT", "/templates", {"templates": before})


def test_port_profiles_roundtrip(api):
    before = api.h("GET", "/port-profiles")
    try:
        doc = {"profiles": [{"name": "p-test", "ports": {"0": {"mode": "L2"}}}], "last_applied": None}
        saved = api.h("PUT", "/port-profiles", doc)
        assert saved["profiles"][0]["name"] == "p-test"
        assert api.h("GET", "/port-profiles")["profiles"][0]["name"] == "p-test"
    finally:
        api.h("PUT", "/port-profiles", {"profiles": before.get("profiles", []), "last_applied": before.get("last_applied")})


def test_monitor_settings_and_extra_stats(api):
    with pytest.raises(ApiError) as e:
        api.h("PUT", "/monitor", {"cpu": True, "interval": 0.1})
    assert e.value.status == 400
    try:
        api.h("PUT", "/monitor", {"cpu": True, "xstats": True, "interval": 1})
        assert api.h("GET", "/monitor")["cpu"] is True
        deadline = time.time() + 15
        got = {}
        while time.time() < deadline and not (got.get("cpu") and got.get("xstats")):
            extra = api.stats().get("extra") or {}
            assert not extra.get("error"), extra
            got.update({k: extra[k] for k in ("cpu", "mbuf", "xstats") if extra.get(k)})
        assert got.get("cpu") and got.get("mbuf") and got.get("xstats"), f"advanced monitoring data incomplete: {list(got)}"
    finally:
        api.h("PUT", "/monitor", {"cpu": False, "xstats": False, "interval": 2})
    assert api.h("GET", "/monitor")["cpu"] is False
