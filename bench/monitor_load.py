"""Simulated GUI polling, to measure what extra monitoring RPCs cost the traffic.

Runs next to bench.py (pinned like the GUI backend: taskset -c 0) with its own
read-only client and issues one poll set per tick until SIGTERM/SIGINT, then
appends per-call RPC timings to --out.

    gui     what the GUI polls today: get_stats (all ports) + pg/latency stats
    mon     gui + per-core CPU/mbuf (get_utilization) + xstats of every port
    stress  mon with no pause between ticks (worst case, far beyond any real use)
"""
import argparse
import json
import os
import signal
import statistics
import sys
import time

TREX_CLIENT = os.environ.get("TREX_CLIENT", "/opt/trex/v3.08/automation/trex_control_plane/interactive")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["gui", "mon", "stress"])
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--label", default="")
    ap.add_argument("--profile", default="")
    ap.add_argument("--out")
    ap.add_argument("--only", help="keep only calls whose name starts with this (e.g. xstats), to isolate one RPC")
    args = ap.parse_args()

    sys.path.insert(0, TREX_CLIENT)
    import warnings
    warnings.filterwarnings("ignore")
    import trex.stl.api as api

    c = api.STLClient(username="monitor", server="127.0.0.1", verbose_level="error")
    c.connect()
    ports = c.get_all_ports()
    calls = {
        "get_stats": lambda: c.get_stats(ports=ports),
        "pg_stats": lambda: c.get_pgid_stats([10, 11]),
    }
    if args.mode != "gui":
        calls["utilization"] = c.get_util_stats
        for p in ports:
            calls[f"xstats_p{p}"] = lambda p=p: c.get_xstats(p)
    if args.only:
        calls = {n: fn for n, fn in calls.items() if n.startswith(args.only)}
    first = {name: fn() for name, fn in calls.items()}  # warm-up (xstats fetches its name list once)
    sizes = {name: len(json.dumps(v, default=str)) for name, v in first.items()}

    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    times = {name: [] for name in calls}
    period = 0 if args.mode == "stress" else 1.0 / args.hz
    ticks = 0
    t_start = time.monotonic()
    while not stop:
        t0 = time.monotonic()
        for name, fn in calls.items():
            a = time.perf_counter()
            fn()
            times[name].append((time.perf_counter() - a) * 1000)
        ticks += 1
        rest = period - (time.monotonic() - t0)
        if rest > 0:
            time.sleep(rest)
    elapsed = time.monotonic() - t_start
    c.disconnect(stop_traffic=False, release_ports=False)

    def pct(v, q):
        v = sorted(v)
        return v[min(len(v) - 1, int(q * len(v)))]

    result = {
        "label": args.label, "profile": args.profile, "mode": args.mode, "only": args.only,
        "ticks_per_s": ticks / elapsed if elapsed else 0,
        "calls": {n: {"n": len(v), "p50_ms": statistics.median(v), "p99_ms": pct(v, 0.99), "max_ms": max(v),
                      "reply_bytes": sizes[n]} for n, v in times.items() if v},
    }
    print(json.dumps(result))
    if args.out:
        with open(args.out, "a") as f:
            f.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
