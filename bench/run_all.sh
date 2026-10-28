#!/bin/bash
# Runs on the TRex host. Scenarios:
#   A  no GUI backend
#   B  GUI backend pinned via server.cpu_affinity (default CPU 0, the TRex master)
#   C  GUI backend unpinned
# Viewers should connect remotely over an SSH tunnel (subs.py), as real users
# would; without viewers the backend does not poll TRex.
#
# Environment: GUI_DIR (installed GUI, default ~/trex-gui), TREX_CLIENT,
# PIN_CPU, REPS, DURATION, OUT. Stop the trex-gui service first.
# DRY_RUN=1 checks GUI start/stop and pinning without sending any traffic.
set -u
cd "$(dirname "$0")"
GUI_DIR=${GUI_DIR:-$HOME/trex-gui}
export TREX_CLIENT=${TREX_CLIENT:-/opt/trex/v3.08/automation/trex_control_plane/interactive}
PIN_CPU=${PIN_CPU:-0}
OUT=${OUT:-results.jsonl}
REPS=${REPS:-3}
DURATION=${DURATION:-30}
BENCH_DIR=$(pwd)

fail() {
    echo "[$(date +%T)] ABORT: $*"
    exit 1
}

gui_running() {
    pgrep -f "[m] trex_gui|[s]pawn_main" > /dev/null || ss -ltn | grep -q ":8080 "
}

stop_gui() {
    # Match by name, not a pid file: a stale backend from an earlier run would
    # otherwise keep polling and silently contaminate scenario A.
    pkill -f "[m] trex_gui" 2>/dev/null
    for _ in $(seq 20); do
        gui_running || return 0
        # spawn_main = the per-host worker processes, in case the parent died without reaping them
        pkill -f "[s]pawn_main" 2>/dev/null
        sleep 0.5
    done
    fail "GUI backend still running or port 8080 busy after stop"
}

write_config() {  # $1 = file, $2 = cpu_affinity line or empty
    cat > "$1" <<EOF
server:
  host: 127.0.0.1
  port: 8080
  stats_interval: 1.0
  static_dir: $GUI_DIR/frontend/dist
$2
hosts:
  - id: local
    name: bench
    server: 127.0.0.1
    client_path: $TREX_CLIENT
EOF
}

start_gui() {  # $1 = config file, $2 = expected CPU list or "all"
    stop_gui
    (cd "$GUI_DIR/backend" && exec nohup ../.venv/bin/python -m trex_gui -c "$1" \
        >> "$BENCH_DIR/gui.log" 2>&1 < /dev/null) &
    local pid=$!
    for _ in $(seq 20); do curl -s localhost:8080/api/hosts > /dev/null && break; sleep 0.5; done
    kill -0 $pid 2>/dev/null || fail "GUI backend exited on start (see gui.log)"
    curl -sf -X POST localhost:8080/api/hosts/local/connect > /dev/null || fail "GUI could not connect to TRex"
    local allowed
    allowed=$(for p in $pid $(pgrep -P $pid); do grep -h Cpus_allowed_list /proc/$p/task/*/status; done | awk '{print $2}' | sort -u | tr '\n' ' ')
    if [ "$2" = all ]; then
        [ "$allowed" = "0-$(($(nproc --all) - 1)) " ] || fail "unpinned GUI has affinity '$allowed'"
    else
        [ "$allowed" = "$2 " ] || fail "pinned GUI threads have affinity '$allowed', expected $2"
    fi
    echo "[$(date +%T)] gui pid $pid, thread affinity: $allowed"
    sleep 5  # let remote viewers reconnect and polling settle
}

gui_running && fail "a GUI backend is already running; stop it first (systemctl --user stop trex-gui)"
[ -x "$GUI_DIR/.venv/bin/python" ] || fail "no GUI install at $GUI_DIR (set GUI_DIR)"
write_config "$BENCH_DIR/gui-pinned.yaml" "  cpu_affinity: [$PIN_CPU]"
write_config "$BENCH_DIR/gui-unpinned.yaml" ""

for rep in $(seq "$REPS"); do
    for sc in A B C; do
        case $sc in
            A) stop_gui ;;
            B) start_gui "$BENCH_DIR/gui-pinned.yaml" "$PIN_CPU" ;;
            C) start_gui "$BENCH_DIR/gui-unpinned.yaml" all ;;
        esac
        for prof in 64b imix; do
            echo "[$(date +%T)] rep=$rep scenario=$sc profile=$prof"
            [ -n "${DRY_RUN:-}" ] && continue
            taskset -c "$PIN_CPU" python3 bench.py --label "$sc" --profile "$prof" --duration "$DURATION" --out "$OUT" 2>&1 | tail -1
        done
    done
done
stop_gui
echo "[$(date +%T)] done"
