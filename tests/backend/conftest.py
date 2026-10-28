"""API tests for the TRex GUI backend, runnable against a mock host or a real TRex.

Mock (default): starts a local backend with mock hosts on a free port and a fresh data dir.

    backend/.venv/bin/python -m pytest tests/backend

Real TRex: point at a running GUI backend whose host has two ports cabled as a loopback
(directly, or in their own VLAN on a switch). The tests switch the pair to L2 or their
own L3 addresses while they run and restore the ports' settings and release them at the end.

    TREX_GUI_URL=http://<gui-host>:8080 TREX_GUI_HOST=local TREX_GUI_PAIR=0,1 \\
        backend/.venv/bin/python -m pytest tests/backend
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from websockets.sync.client import connect as ws_connect

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ.get("TREX_GUI_URL")
REAL = bool(URL)
HOST = os.environ.get("TREX_GUI_HOST", "local" if REAL else "demo")
PAIR = tuple(int(p) for p in os.environ.get("TREX_GUI_PAIR", "0,1" if REAL else "2,3").split(","))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    """Base URL of the backend under test; starts a mock backend unless TREX_GUI_URL is set."""
    if REAL:
        yield URL.rstrip("/")
        return
    tmp = Path(tempfile.mkdtemp(prefix="trex-gui-test-"))
    port = free_port()
    (tmp / "data" / "profiles").mkdir(parents=True)
    (tmp / "data" / "profiles" / "sample.py").write_text("def register():\n    return None\n")
    cfg = tmp / "config.yaml"
    cfg.write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": port, "stats_interval": 0.5, "data_dir": str(tmp / "data")},
        "hosts": [
            {"id": "demo", "name": "Demo", "mock": True, "mock_ports": 8},
            {"id": "other", "name": "Other", "mock": True, "mock_ports": 4},
            {"id": "far", "name": "Far", "server": "192.0.2.10", "client_path": "/nonexistent"},
        ],
    }))
    log = open(tmp / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "trex_gui", "-c", str(cfg)], cwd=ROOT / "backend",
                            stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(base + "/api/hosts", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError(f"backend did not start; see {tmp / 'server.log'}")
    yield base
    proc.terminate()
    proc.wait(10)


class Api:
    """Thin JSON client: raises with the backend's detail on any non-2xx status."""

    def __init__(self, base: str, host: str):
        self.base, self.host = base, host
        self.http = httpx.Client(base_url=base + "/api", timeout=180)

    def raw(self, method, path, **kw):
        return self.http.request(method, path, **kw)

    def call(self, method, path, body=None, **kw):
        r = self.http.request(method, path, json=body, **kw) if body is not None else self.http.request(method, path, **kw)
        if r.status_code >= 300:
            raise ApiError(r.status_code, r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text)
        return r.json() if r.content else None

    def h(self, method, path, body=None, **kw):
        """Call a path under /hosts/<host>."""
        return self.call(method, f"/hosts/{self.host}{path}", body, **kw)

    def stats(self, host: str | None = None, fresh_after: float | None = None) -> dict:
        """One stats message from the shared stats stream (taken after `fresh_after` if given)."""
        url = self.base.replace("http", "ws", 1) + f"/api/hosts/{host or self.host}/stats"
        with ws_connect(url, open_timeout=10) as ws:
            deadline = time.time() + 20
            while time.time() < deadline:
                m = json.loads(ws.recv(timeout=20))
                if m.get("type") == "stats" and (fresh_after is None or time.time() > fresh_after):
                    return m
        raise TimeoutError("no stats message")

    def measure_pps(self, port: int, seconds: float = 3.0, field: str = "opackets") -> float:
        """Packet rate from counter deltas. TRex's own *_pps figures are smoothed and
        lag several seconds behind a start or a rate change."""
        url = self.base.replace("http", "ws", 1) + f"/api/hosts/{self.host}/stats"
        with ws_connect(url, open_timeout=10) as ws:
            samples = []
            while True:
                m = json.loads(ws.recv(timeout=20))
                if m.get("type") != "stats":
                    continue
                samples.append((time.time(), m["ports"][str(port)][field]))
                if len(samples) >= 2 and samples[-1][0] - samples[1][0] >= seconds:
                    break  # samples[0] may be a cached message sent on connect
        (t0, a), (t1, b) = samples[1], samples[-1]
        return (b - a) / (t1 - t0)

    def port_stats(self, settle: float = 1.5) -> dict:
        """Port counters after letting the stats poll catch up."""
        return self.stats(fresh_after=time.time() + settle)["ports"]


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


@pytest.fixture(scope="session")
def api(server):
    a = Api(server, HOST)
    a.h("POST", "/connect")
    return a


@pytest.fixture(scope="session")
def pair(api):
    """The two loopback ports, acquired for the whole session; restored and released at the end."""
    tx, rx = PAIR
    api.h("POST", "/ports/acquire", {"ports": [tx, rx], "force": True})
    before = {p["id"]: p for p in api.h("GET", "/ports") if p["id"] in PAIR}
    yield tx, rx
    try:
        api.h("POST", "/traffic/reset", {"ports": [tx, rx]})
        for pid, p in before.items():
            layer = p["layer"]
            cfg = {"vlan": layer.get("vlan") or [], "promiscuous": bool(layer.get("promiscuous")),
                   "multicast": bool(layer.get("multicast")),
                   "ipv6": {"enabled": bool(layer.get("ipv6")), "src": layer.get("ipv6_src") or None}}
            if layer["mode"] == "L3":
                cfg["l3"] = {"src": layer["ipv4_src"], "dst": layer["ipv4_dst"]}
            else:
                cfg["l2"] = {"dst_mac": layer["dst_mac"]}
            api.h("POST", f"/ports/{pid}/config", cfg)
        for pid in PAIR:
            api.h("PUT", f"/ports/{pid}/streams", {"streams": []})
    finally:
        api.h("POST", "/ports/release", {"ports": [tx, rx]})


def macs(api) -> dict:
    return {p["id"]: p["layer"]["src_mac"] for p in api.h("GET", "/ports")}


@pytest.fixture
def l2_loop(api, pair):
    """Pair in L2, each port sending to the other's MAC (works on a plain loopback)."""
    tx, rx = pair
    m = macs(api)
    api.h("POST", f"/ports/{tx}/config", {"l2": {"dst_mac": m[rx]}, "vlan": []})
    api.h("POST", f"/ports/{rx}/config", {"l2": {"dst_mac": m[tx]}, "vlan": []})
    api.h("POST", "/traffic/reset", {"ports": [tx, rx]})
    yield tx, rx
    api.h("POST", "/traffic/stop", {"ports": [tx, rx]})


# --- streams -----------------------------------------------------------------

UDP = [{"proto": "Ether", "fields": {}}, {"proto": "IP", "fields": {"src": "16.0.0.1", "dst": "48.0.0.1"}},
       {"proto": "UDP", "fields": {"sport": 1025, "dport": 12}}]


def stream(sid="s1", rate=1000, unit="pps", size=128, mode=None, pg=None, pg_type="stats", vm=None, layers=None,
           payload=None, size_var=None, enabled=True, **extra):
    packet = {"layers": layers or UDP, "frame_size": size}
    if payload:
        packet["payload"] = payload
    if size_var:
        packet["size"] = size_var
    return {"id": sid, "name": sid, "enabled": enabled, "vm": vm or [], "mode": mode or {"type": "continuous"},
            "rate": {"unit": unit, "value": rate},
            "flow_stats": {"type": pg_type, "pg_id": pg} if pg is not None else {"type": "none"},
            "packet": packet, **extra}


def wait_idle(api, ports, timeout=30):
    """Wait until none of `ports` is transmitting."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = {p["id"]: p["status"] for p in api.h("GET", "/ports")}
        if all(st[p] != "TRANSMITTING" for p in ports):
            return
        time.sleep(0.5)
    raise TimeoutError(f"ports {ports} still transmitting")


# --- pcap files --------------------------------------------------------------

def pcap_bytes(frames: list[bytes], gap_us: int = 1000) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for i, f in enumerate(frames):
        t = i * gap_us
        out += struct.pack("<IIII", t // 1_000_000, t % 1_000_000, len(f), len(f)) + f
    return out


def read_pcap(data: bytes) -> list[bytes]:
    frames, off = [], 24
    while off + 16 <= len(data):
        n = struct.unpack("<IIII", data[off:off + 16])[2]
        frames.append(data[off + 16:off + 16 + n])
        off += 16 + n
    return frames
