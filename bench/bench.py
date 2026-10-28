"""Measure TRex throughput/latency on a p0<->p1 loopback, for comparing runs
with and without the GUI backend on the same machine.

Usage (on the TRex host; set TREX_CLIENT to use another TRex version):
    python3 bench.py --label A --profile 64b --duration 30 --out results.jsonl
    python3 bench.py --restore-l3 0:10.0.0.2:10.0.0.1 1:192.168.200.2:192.168.200.1
"""
import argparse
import json
import os
import sys
import time

TREX_CLIENT = os.environ.get("TREX_CLIENT", "/opt/trex/v3.08/automation/trex_control_plane/interactive")
PORTS = [0, 1]
WARMUP_S = 5
LATENCY_PPS = 1000


def build_streams(profile, src_port, api):
    Ether, IP, UDP = api.Ether, api.IP, api.UDP
    if src_port == 0:
        base = Ether() / IP(src="16.0.0.1", dst="48.0.0.1") / UDP(sport=1025, dport=12)
    else:
        base = Ether() / IP(src="48.0.0.1", dst="16.0.0.1") / UDP(sport=12, dport=1025)

    def pkt(size):  # size excludes the 4-byte FCS
        pad = max(0, size - len(base)) * b"x"
        vm = api.STLScVmRaw([
            api.STLVmFlowVar(name="src", min_value=1, max_value=254, size=1, op="inc"),
            api.STLVmWrFlowVar(fv_name="src", pkt_offset="IP.src", offset_fixup=3),
            api.STLVmFixIpv4(offset="IP"),
        ])
        return api.STLPktBuilder(pkt=base / pad, vm=vm)

    if profile == "64b":
        mix = [(60, 100.0)]
    else:
        # Classic IMIX 7:4:1 by packet count, expressed as share of L1 bandwidth.
        sizes = [(60, 7), (590, 4), (1514, 1)]
        l1 = {s: n * (s + 4 + 20) for s, n in sizes}
        total = sum(l1.values())
        mix = [(s, 100.0 * l1[s] / total) for s, _ in sizes]

    streams = [api.STLStream(packet=pkt(size), mode=api.STLTXCont(percentage=pct)) for size, pct in mix]
    lat_pkt = api.STLPktBuilder(pkt=base / (max(0, 60 - len(base)) * b"x"))
    streams.append(api.STLStream(
        packet=lat_pkt,
        mode=api.STLTXCont(pps=LATENCY_PPS),
        flow_stats=api.STLFlowLatencyStats(pg_id=10 + src_port),
    ))
    return streams


def run(args):
    import trex.stl.api as api

    c = api.STLClient(username="bench", server="127.0.0.1", verbose_level="error")
    c.connect()
    try:
        c.acquire(ports=PORTS)
        c.reset(ports=PORTS)
        macs = {p: c.get_port(p).get_layer_cfg()["ether"]["src"] for p in PORTS}
        c.set_service_mode(ports=PORTS, enabled=True)
        c.set_l2_mode(0, dst_mac=macs[1])
        c.set_l2_mode(1, dst_mac=macs[0])
        c.set_service_mode(ports=PORTS, enabled=False)
        for p in PORTS:
            c.add_streams(build_streams(args.profile, p, api), ports=[p])

        c.start(ports=PORTS, mult="1", force=True)
        time.sleep(WARMUP_S)
        c.clear_stats(ports=PORTS)
        t0 = time.monotonic()

        cpu_samples = []
        while time.monotonic() - t0 < args.duration:
            time.sleep(5)
            g = c.get_stats(ports=PORTS)["global"]
            cpu_samples.append((g.get("cpu_util", 0), g.get("rx_cpu_util", 0)))

        c.stop(ports=PORTS)
        elapsed = time.monotonic() - t0
        time.sleep(1)  # let in-flight packets land
        s = c.get_stats(ports=PORTS)
    finally:
        c.release(ports=PORTS)
        c.disconnect(stop_traffic=False, release_ports=False)

    tx = sum(s[p]["opackets"] for p in PORTS)
    rx = sum(s[p]["ipackets"] for p in PORTS)
    lat = {}
    for pg in (10, 11):
        L = s["latency"].get(pg, {})
        errs = L.get("err_cntrs", {})
        lat[pg] = {
            "avg_us": L.get("latency", {}).get("average"),
            "max_us": L.get("latency", {}).get("total_max"),
            "jitter_us": L.get("latency", {}).get("jitter"),
            "dropped": errs.get("dropped"),
            "out_of_order": errs.get("out_of_order"),
        }
    result = {
        "label": args.label,
        "profile": args.profile,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_s": round(elapsed, 2),
        "tx_mpps": tx / elapsed / 1e6,
        "rx_mpps": rx / elapsed / 1e6,
        "tx_gbps_l2": sum(s[p]["obytes"] for p in PORTS) * 8 / elapsed / 1e9,
        "loss_pkts": tx - rx,
        "loss_ratio": (tx - rx) / tx if tx else None,
        "ierrors": sum(s[p]["ierrors"] for p in PORTS),
        "oerrors": sum(s[p]["oerrors"] for p in PORTS),
        "dp_cpu_util": sum(x[0] for x in cpu_samples) / len(cpu_samples),
        "rx_cpu_util": sum(x[1] for x in cpu_samples) / len(cpu_samples),
        "latency": lat,
    }
    print(json.dumps(result))
    if args.out:
        with open(args.out, "a") as f:
            f.write(json.dumps(result) + "\n")


def restore_l3(specs):
    import trex.stl.api as api

    c = api.STLClient(username="bench", server="127.0.0.1", verbose_level="error")
    c.connect()
    try:
        ports = [int(s.split(":")[0]) for s in specs]
        c.acquire(ports=ports)
        c.set_service_mode(ports=ports, enabled=True)
        for spec in specs:
            port, src, dst = spec.split(":")
            c.set_l3_mode(int(port), src_ipv4=src, dst_ipv4=dst)
        c.resolve(ports=ports)
        c.set_service_mode(ports=ports, enabled=False)
        for p in ports:
            print(p, c.get_port(p).get_layer_cfg())
        c.release(ports=ports)
    finally:
        c.disconnect(stop_traffic=False, release_ports=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("--profile", choices=["64b", "imix"], default="64b")
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--out")
    ap.add_argument("--restore-l3", nargs="+", metavar="PORT:SRC:DST")
    args = ap.parse_args()

    sys.path.insert(0, TREX_CLIENT)
    import warnings
    warnings.filterwarnings("ignore")

    if args.restore_l3:
        restore_l3(args.restore_l3)
    else:
        run(args)


if __name__ == "__main__":
    main()
