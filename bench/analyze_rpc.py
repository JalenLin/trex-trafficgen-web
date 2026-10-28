"""Summarize monitor-rpc.jsonl from run_monitor.sh: RPC time per call while traffic runs."""
import json
import sys
from collections import defaultdict

rows = [json.loads(line) for line in open(sys.argv[1] if len(sys.argv) > 1 else "monitor-rpc.jsonl")]
groups = defaultdict(list)
for r in rows:
    groups[(r["label"], r["profile"])].append(r)

print("| 情境 | 封包 | 每秒輪數 | 呼叫 | 中位數 ms | p99 ms | 最大 ms | 回應大小 |")
print("|---|---|---|---|---|---|---|---|")
for (label, profile), rs in sorted(groups.items()):
    tps = sum(r["ticks_per_s"] for r in rs) / len(rs)
    for name in rs[0]["calls"]:
        cs = [r["calls"][name] for r in rs]
        p50 = sorted(c["p50_ms"] for c in cs)[len(cs) // 2]
        print(f"| {label} | {profile} | {tps:.1f} | {name} | {p50:.2f} | {max(c['p99_ms'] for c in cs):.2f} "
              f"| {max(c['max_ms'] for c in cs):.2f} | {cs[0]['reply_bytes']} B |")
