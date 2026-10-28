"""Port settings: L2/L3 with ARP, ping, VLAN/QinQ, IPv6, promiscuous, multicast, flow control, link, service mode."""
import os

import pytest

from conftest import REAL, ApiError, macs


def layer(api, pid):
    return {p["id"]: p for p in api.h("GET", "/ports")}[pid]["layer"]


def port(api, pid):
    return {p["id"]: p for p in api.h("GET", "/ports")}[pid]


def test_l2_destination_mac(api, pair):
    tx, rx = pair
    m = macs(api)
    api.h("POST", f"/ports/{tx}/config", {"l2": {"dst_mac": m[rx]}})
    assert layer(api, tx)["mode"] == "L2" and layer(api, tx)["dst_mac"].lower() == m[rx].lower()


def test_l2_and_l3_together_is_rejected(api, pair):
    with pytest.raises(ApiError) as e:
        api.h("POST", f"/ports/{pair[0]}/config", {"l2": {"dst_mac": "00:11:22:33:44:55"}, "l3": {"src": "1.1.1.1", "dst": "1.1.1.2"}})
    assert e.value.status == 400


def test_l3_pair_resolves(api, pair):
    """Port tx's gateway is port rx, so ARP resolves over the loopback. rx is put in
    service mode while tx resolves: with TRex's linux_based stack a port only answers
    ARP in service mode (the legacy stack always answers)."""
    tx, rx = pair
    api.h("POST", f"/ports/{tx}/config", {"l3": {"src": "198.18.0.1", "dst": "198.18.0.2"}})
    api.h("POST", f"/ports/{rx}/config", {"l3": {"src": "198.18.0.2", "dst": "198.18.0.1"}})
    api.h("POST", f"/ports/{rx}/service", {"mode": "on"})
    try:
        r = api.h("POST", "/ports/resolve", {"ports": [tx]})
    finally:
        api.h("POST", f"/ports/{rx}/service", {"mode": "off"})
    assert r["warnings"] == []
    assert layer(api, tx)["mode"] == "L3"
    assert layer(api, tx)["arp"] == "resolved", layer(api, tx)
    if REAL:  # the mock gateway is not the other port
        assert layer(api, tx)["dst_mac"].lower() == macs(api)[rx].lower()


def test_ping(api, pair):
    """TRex ports answer ARP but not ping, so on a real loopback this only checks the call;
    set TREX_GUI_PING=<port>:<src>:<gateway>:<target> to ping a real host (e.g. the router)."""
    target = os.environ.get("TREX_GUI_PING")
    if target:
        port, src, gw, dst = target.split(":")
        api.h("POST", f"/ports/{port}/config", {"l3": {"src": src, "dst": gw}})
        replies = api.h("POST", f"/ports/{port}/ping", {"dst_ip": dst, "count": 3})
        assert sum(r["state"] == "ok" for r in replies) >= 2, replies
        assert all(r["rtt_ms"] is not None for r in replies if r["state"] == "ok")
        return
    tx, rx = pair
    api.h("POST", f"/ports/{tx}/config", {"l3": {"src": "198.18.0.1", "dst": "198.18.0.2"}})
    api.h("POST", f"/ports/{rx}/config", {"l3": {"src": "198.18.0.2", "dst": "198.18.0.1"}})
    replies = api.h("POST", f"/ports/{tx}/ping", {"dst_ip": "198.18.0.2", "count": 3})
    assert len(replies) == 3 and all(r["state"] in ("ok", "timeout") for r in replies), replies
    if not REAL:
        assert all(r["state"] == "ok" for r in replies)


def test_unresolved_gateway(api, pair):
    tx, _ = pair
    r = api.h("POST", f"/ports/{tx}/config", {"l3": {"src": "198.18.0.1", "dst": "198.19.0.99"}})
    assert layer(api, tx)["arp"] == "unresolved"
    # Warnings carry a code + params for the UI to translate.
    assert [w["code"] for w in r["warnings"]] == ["arpUnresolved"], r["warnings"]
    assert r["warnings"][0]["params"] == {"port": tx, "gateway": "198.19.0.99"}
    r = api.h("POST", "/ports/resolve", {"ports": [tx]})
    assert [w["code"] for w in r["warnings"]] == ["arpUnresolved"], r["warnings"]


def test_vlan_qinq_and_clear(api, pair):
    tx, _ = pair
    api.h("POST", f"/ports/{tx}/config", {"vlan": [100]})
    assert layer(api, tx)["vlan"] == [100]
    api.h("POST", f"/ports/{tx}/config", {"vlan": [100, 200]})
    assert layer(api, tx)["vlan"] == [100, 200]
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{tx}/config", {"vlan": [5000]})
    api.h("POST", f"/ports/{tx}/config", {"vlan": []})
    assert layer(api, tx)["vlan"] == []


def test_promiscuous_multicast(api, pair):
    tx, _ = pair
    api.h("POST", f"/ports/{tx}/config", {"promiscuous": True, "multicast": True})
    lay = layer(api, tx)
    assert lay["promiscuous"] and lay["multicast"]
    api.h("POST", f"/ports/{tx}/config", {"promiscuous": False, "multicast": False})
    lay = layer(api, tx)
    assert not lay["promiscuous"] and not lay["multicast"]


def test_ipv6(api, pair):
    tx, _ = pair
    try:
        api.h("POST", f"/ports/{tx}/config", {"ipv6": {"enabled": True}})
    except ApiError as e:
        # TRex's legacy stack has no IPv6; the error is shown to the user as is.
        assert REAL and "not supported with current stack" in e.detail, e.detail
        return
    assert layer(api, tx)["ipv6"]
    api.h("POST", f"/ports/{tx}/config", {"ipv6": {"enabled": False}})
    assert not layer(api, tx)["ipv6"]


def test_flow_control(api, pair):
    tx, _ = pair
    lay = layer(api, tx)
    if lay.get("flow_ctrl") is None:
        pytest.skip("NIC has no flow control")
    old = lay["flow_ctrl"]
    want = 0 if old else 3
    try:
        r = api.h("POST", f"/ports/{tx}/config", {"flow_ctrl": want})
        if layer(api, tx)["flow_ctrl"] != want:
            # The NIC ignored it (seen on X557/ixgbe): the user is told instead of a silent no-op.
            assert [w["code"] for w in r["warnings"]] == ["flowCtrlNotApplied"], r["warnings"]
        else:
            assert r["warnings"] == []
        with pytest.raises(ApiError):
            api.h("POST", f"/ports/{tx}/config", {"flow_ctrl": 7})
    finally:
        api.h("POST", f"/ports/{tx}/config", {"flow_ctrl": old})


@pytest.mark.skipif(REAL, reason="taking the link down on real hardware disturbs the switch")
def test_link_down_up(api, pair):
    tx, _ = pair
    api.h("POST", f"/ports/{tx}/config", {"link_up": False})
    assert port(api, tx)["link"] == "DOWN"
    api.h("POST", f"/ports/{tx}/config", {"link_up": True})
    assert port(api, tx)["link"] == "UP"


def test_service_mode_on_off(api, pair):
    tx, _ = pair
    api.h("POST", f"/ports/{tx}/service", {"mode": "on"})
    assert layer(api, tx)["service"] == "on"
    api.h("POST", f"/ports/{tx}/service", {"mode": "off"})
    assert layer(api, tx)["service"] == "off"
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{tx}/service", {"mode": "sideways"})


def test_service_mode_filtered(api, pair):
    tx, _ = pair
    try:
        api.h("POST", f"/ports/{tx}/service", {"mode": "filtered"})
    except ApiError as e:
        # TRex supports filtered service mode only when started with --software.
        assert REAL and "software" in e.detail.lower(), e.detail
        return
    finally:
        api.h("POST", f"/ports/{tx}/service", {"mode": "off"})
