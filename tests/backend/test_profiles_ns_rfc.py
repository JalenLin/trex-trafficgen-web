"""TRex Python profiles, namespace nodes and RFC 2544."""
import time

import pytest

from conftest import REAL, ApiError, wait_idle


# --- Python profiles -----------------------------------------------------------

def test_profile_list_and_upload_disabled(api):
    r = api.h("GET", "/profiles")
    assert r["upload_allowed"] is False
    assert r["profiles"], "no profiles listed"
    with pytest.raises(ApiError) as e:
        api.call("POST", "/profiles", params={"name": "x.py"}, content=b"print(1)")
    assert e.value.status == 400
    with pytest.raises(ApiError):
        api.h("GET", "/profiles/info", params={"id": "shared:../../etc/passwd"})


@pytest.mark.skipif(not REAL, reason="mock hosts can't run TRex profiles")
def test_profile_params_and_start(api, l2_loop):
    tx, rx = l2_loop
    ids = {p["id"] for p in api.h("GET", "/profiles")["profiles"]}
    pid = "trex:udp_1pkt_simple_bdir.py" if "trex:udp_1pkt_simple_bdir.py" in ids else "trex:udp_1pkt_simple.py"
    assert pid in ids, sorted(ids)[:20]
    info = api.h("GET", "/profiles/info", params={"id": pid})
    assert info["style"] in ("argparse", "kwargs", "none"), info
    with_args = api.h("GET", "/profiles/info", params={"id": "trex:flow_stats.py"})
    assert with_args["options"], with_args  # argparse options / get_streams kwargs become a form
    api.h("POST", "/stats/clear", {"ports": [tx, rx]})
    r = api.h("POST", "/traffic/start-profile", {"id": pid, "ports": [tx], "mult": "1kpps", "duration": 2, "force": True})
    assert r["streams"]
    assert str(tx) in {str(k) for k in api.h("GET", "/profile-runs")}
    wait_idle(api, [tx], 15)
    s = api.port_stats()
    assert s[str(tx)]["opackets"] == pytest.approx(2000, rel=0.1)
    assert s[str(rx)]["ipackets"] >= s[str(tx)]["opackets"] * 0.999


@pytest.mark.skipif(REAL, reason="mock-only check")
def test_profile_on_mock_explains(api):
    with pytest.raises(ApiError) as e:
        api.h("GET", "/profiles/info", params={"id": "shared:sample.py"})
    assert "mock" in e.value.detail


# --- namespaces ------------------------------------------------------------------

def test_namespace_nodes(api, pair):
    tx, _ = pair
    try:
        before = api.h("GET", f"/ports/{tx}/ns")
    except ApiError as e:
        assert "linux_based" in e.detail, e.detail
        pytest.skip("TRex not started with stack: linux_based (the UI explains this)")
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{tx}/ns", {"mac": "not-a-mac"})
    nodes = api.h("POST", f"/ports/{tx}/ns", {"mac": "02:00:00:00:99:01", "ipv4": "198.18.5.10", "dg": "198.18.5.1", "vlans": [10]})
    assert len(nodes) == len(before) + 1
    node = next(n for n in nodes if n["ether"]["src"] == "02:00:00:00:99:01")
    assert node["ipv4"]["src"] == "198.18.5.10" and node["vlan"]["tags"] == [10]
    with pytest.raises(ApiError):
        api.h("POST", f"/ports/{tx}/ns", {"mac": "02:00:00:00:99:01"})
    assert len(api.h("POST", f"/ports/{tx}/ns/remove", {"macs": ["02:00:00:00:99:01"]})) == len(before)


# --- RFC 2544 ------------------------------------------------------------------------

RFC = {"bidirectional": True, "frame_sizes": [64, 1518], "tests": ["throughput", "latency", "frame_loss", "back_to_back"],
       "trial_s": 1, "resolution_pct": 5, "max_rate_pct": 50 if REAL else 100, "frame_loss_step_pct": 25, "b2b_max_s": 0.01}


def wait_rfc(api, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = api.h("GET", "/rfc2544")
        if job["state"] != "running":
            return job
        time.sleep(2)
    raise TimeoutError("RFC 2544 run did not finish")


def test_rfc2544_validation(api, pair):
    for bad in ({"pairs": []}, {"pairs": [{"tx": pair[0], "rx": pair[0]}]}, {"pairs": [{"tx": pair[0], "rx": pair[1]}], "frame_sizes": [10]},
                {"pairs": [{"tx": pair[0], "rx": pair[1]}], "tests": ["nonsense"]}):
        with pytest.raises(ApiError) as e:
            api.h("POST", "/rfc2544", {**RFC, **bad})
        assert e.value.status == 400, bad


def test_rfc2544_full_run(api, l2_loop):
    tx, rx = l2_loop
    job = api.h("POST", "/rfc2544", {**RFC, "pairs": [{"tx": tx, "rx": rx}]})
    assert job["state"] == "running"
    # Ports in use are protected while the test runs.
    with pytest.raises(ApiError) as e:
        api.h("POST", "/traffic/start", {"ports": [tx], "force": True})
    assert "RFC 2544" in e.value.detail
    with pytest.raises(ApiError):
        api.h("POST", "/rfc2544", {**RFC, "pairs": [{"tx": tx, "rx": rx}]})
    job = wait_rfc(api)
    assert job["state"] == "done", job.get("error")
    r = job["results"]
    assert [x["size"] for x in r["throughput"]] == [64, 1518]
    for x in r["throughput"]:
        assert 0 < x["rate_pct"] <= RFC["max_rate_pct"] and x["mpps"] > 0 and "offered_pct" in x and "tx_limited" in x
    big = next(x for x in r["throughput"] if x["size"] == 1518)
    # Real loopback: lossless up to the cap. Mock: its pretend DUT drops above 85% of line rate.
    assert big["rate_pct"] == pytest.approx(RFC["max_rate_pct"] if REAL else 85, abs=RFC["resolution_pct"])
    assert all(d["latency"]["average"] is not None for x in r["latency"] for d in x["dirs"])
    assert len(r["latency"][0]["dirs"]) == 2  # bidirectional
    assert all(x["points"] for x in r["frame_loss"])
    if REAL:
        assert all(x["frames"] > 0 for x in r["back_to_back"])
    else:  # the pretend DUT drops above 85%: loss is found at 100%, and no burst at 100% gets through
        assert all(x["points"][0]["loss_pct"] > 0 for x in r["frame_loss"])
        assert all(x["frames"] == 0 for x in r["back_to_back"])

    hist = api.h("GET", "/rfc2544/history")
    assert hist[0]["id"] == job["id"]
    assert api.h("GET", f"/rfc2544/history/{job['id']}")["results"]["throughput"]
    api.h("DELETE", f"/rfc2544/history/{job['id']}")
    assert all(h["id"] != job["id"] for h in api.h("GET", "/rfc2544/history"))
    # The ports are usable again.
    api.h("PUT", f"/ports/{tx}/streams", {"streams": []})


def test_rfc2544_stop(api, l2_loop):
    tx, rx = l2_loop
    api.h("POST", "/rfc2544", {**RFC, "pairs": [{"tx": tx, "rx": rx}], "trial_s": 3})
    time.sleep(2)
    api.h("POST", "/rfc2544/stop")
    job = wait_rfc(api, 30)
    assert job["state"] in ("stopped", "cancelled"), job["state"]
    wait_idle(api, [tx, rx], 10)
    api.h("DELETE", f"/rfc2544/history/{job['id']}")
