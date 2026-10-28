#!/bin/bash
# Which RPC causes the stress-mode impact? Stress-polls one call type at a time (64B line rate).
set -u
cd "$(dirname "$0")"
export TREX_CLIENT=${TREX_CLIENT:-/opt/trex/v3.08/automation/trex_control_plane/interactive}
REPS=${REPS:-2}
for rep in $(seq "$REPS"); do
    for only in get_stats xstats utilization; do
        echo "[$(date +%T)] rep=$rep stress only=$only"
        taskset -c 0 python3 monitor_load.py stress --only "$only" --label "S-$only" --profile 64b --out isolate-rpc.jsonl > /dev/null 2>&1 &
        poller=$!
        sleep 2
        taskset -c 0 python3 bench.py --label "S-$only" --profile 64b --duration 30 --out isolate-results.jsonl 2>&1 | tail -1 | cut -c1-120
        kill -TERM $poller; wait $poller
    done
done
echo "[$(date +%T)] done"
