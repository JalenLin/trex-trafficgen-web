#!/bin/bash
# Runs on the TRex host, on a p0<->p1 loopback. Does extra monitoring polling hurt traffic?
#   A  no polling
#   G  what the GUI polls today, 1/s
#   M  + per-core CPU/mbuf and xstats of every port, 1/s
#   S  M back-to-back (stress, worst case)
# The poller is pinned to PIN_CPU like the GUI backend. Stop the trex-gui service first.
# Environment: TREX_CLIENT, PIN_CPU, REPS, DURATION, OUT, POLL_OUT.
set -u
cd "$(dirname "$0")"
export TREX_CLIENT=${TREX_CLIENT:-/opt/trex/v3.08/automation/trex_control_plane/interactive}
PIN_CPU=${PIN_CPU:-0}
REPS=${REPS:-3}
DURATION=${DURATION:-20}
OUT=${OUT:-monitor-results.jsonl}
POLL_OUT=${POLL_OUT:-monitor-rpc.jsonl}

if ss -ltn | grep -q ":8080 "; then
    echo "a GUI backend is listening on 8080; stop it first (systemctl --user stop trex-gui)"
    exit 1
fi

for rep in $(seq "$REPS"); do
    for sc in A G M S; do
        for prof in 64b imix; do
            echo "[$(date +%T)] rep=$rep scenario=$sc profile=$prof"
            poller=
            case $sc in
                G) mode=gui ;; M) mode=mon ;; S) mode=stress ;; *) mode= ;;
            esac
            if [ -n "$mode" ]; then
                taskset -c "$PIN_CPU" python3 monitor_load.py "$mode" --label "$sc" --profile "$prof" --out "$POLL_OUT" > /dev/null 2>&1 &
                poller=$!
                sleep 2
            fi
            taskset -c "$PIN_CPU" python3 bench.py --label "$sc" --profile "$prof" --duration "$DURATION" --out "$OUT" 2>&1 | tail -1 | cut -c1-160
            if [ -n "$poller" ]; then
                kill -TERM "$poller"
                wait "$poller"
            fi
        done
    done
done
echo "[$(date +%T)] done"
