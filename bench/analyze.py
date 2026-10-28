"""Summarize results.jsonl from run_all.sh: one row per (profile, scenario)."""
import json
import statistics as st
import sys
from collections import defaultdict

rows = [json.loads(line) for line in open(sys.argv[1] if len(sys.argv) > 1 else "results.jsonl")]
groups = defaultdict(list)
for r in rows:
    groups[(r["profile"], r["label"])].append(r)


def lat(r, field):
    return [r["latency"][pg][field] for pg in ("10", "11")]


def fmt(vals, digits=3):
    if len(vals) == 1:
        return f"{vals[0]:.{digits}f}"
    return f"{st.mean(vals):.{digits}f} ({min(vals):.{digits}f}–{max(vals):.{digits}f})"


print("| 封包 | 情境 | 次數 | TX Mpps | TX−RX 差 | latency 丟包 | DP CPU % | latency 平均 μs | latency 最大 μs | jitter μs |")
print("|---|---|---|---|---|---|---|---|---|---|")
for (profile, label), rs in sorted(groups.items()):
    avg = [x for r in rs for x in lat(r, "avg_us")]
    mx = [x for r in rs for x in lat(r, "max_us")]
    jit = [x for r in rs for x in lat(r, "jitter_us")]
    # tx-rx is noisy by a few hundred packets: clear_stats is not atomic across ports
    # while traffic flows. The latency stream's sequence-based drop count is exact.
    diff = [r["loss_pkts"] for r in rs]
    drops = sum(x or 0 for r in rs for x in lat(r, "dropped"))
    print(
        f"| {profile} | {label} | {len(rs)} | {fmt([r['tx_mpps'] for r in rs])} | {min(diff)}~{max(diff)} | {drops} "
        f"| {fmt([r['dp_cpu_util'] for r in rs], 1)} | {fmt(avg, 1)} | {sorted(mx)} | {max(jit)} |"
    )
