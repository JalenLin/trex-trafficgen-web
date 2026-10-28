# Benchmarks

**English** | [繁體中文](README.md)

These tests answer two questions: does running the GUI backend on the TRex host slow down traffic, and does each additional kind of monitoring slow down traffic? All tests run on a p0↔p1 loopback (for the lab host's switch setup see section 8 of `docs/deployment.en.md`), at line rate in both directions, each direction with an extra 1000 pps latency stream.

| Script | Purpose |
|---|---|
| `bench.py` | Runs traffic once and measures throughput, loss, DP CPU and latency |
| `run_all.sh` | GUI backend: not running / pinned / not pinned (2026-10-28, `results-2026-10-28.jsonl`) |
| `monitor_load.py` | Emulates the GUI's polling: pinned to core 0, sending RPCs with its own read-only client |
| `run_monitor.sh` | Monitoring load: scenarios A/G/M/S (`monitor-results.jsonl`, `monitor-rpc.jsonl`) |
| `run_isolate.sh` | Each RPC on its own under stress (`isolate-results.jsonl`, `isolate-rpc.jsonl`) |
| `analyze.py` / `analyze_rpc.py` | Turn the jsonl files into the tables below |

## Monitoring load (2026-10-28, TRex v3.08, Ryzen 7 3800X, ConnectX-4 Lx 25G)

| Scenario | Polling |
|---|---|
| A | No polling |
| G | The GUI's current polling: `get_stats` (including pg/latency) once a second |
| M | G plus per-core CPU/mbuf (`get_utilization`) and per-port xstats, once a second |
| S | M's queries back to back with no pause, about 25–27 rounds a second (a stress test far beyond real use) |

| Packet | Scenario | Runs | TX Mpps | Latency loss | DP CPU % | Latency avg μs | Latency max μs | Jitter μs |
|---|---|---|---|---|---|---|---|---|
| 64b | A | 3 | 55.187 | 0 | 92.4 | 7.2 | [11, 13, 14, 15, 15, 180] | 11 |
| 64b | G | 3 | 55.188 | 0 | 92.4 | 8.7 | [13, 13, 14, 15, 101, 206] | 13 |
| 64b | M | 3 | 55.187 | 0 | 92.4 | 7.2 | [14, 15, 32, 32, 110, 112] | 7 |
| 64b | S | 3 | 55.114 (−0.13%) | 0 | 88.1 | 8.0 | [21, 21, 27, 124, 212, 282] | 32 |
| imix | A | 3 | 16.368 | 0 | 17.4 | 10.0 | [13, 13, 13, 13, 14, 14] | 1 |
| imix | G | 3 | 16.368 | 0 | 16.9 | 9.8 | [13, 13, 15, 19, 20, 22] | 1 |
| imix | M | 3 | 16.368 | 0 | 16.8 | 9.8 | [13, 14, 18, 19, 50, 50] | 1 |
| imix | S | 3 | 16.369 | 0 | 19.4 | 10.0 | [17, 17, 18, 18, 167, 169] | 1 |

Each RPC on its own at 64B line rate, queried back to back:

| RPC | Per second | Time per call (median) | TX Mpps | Latency max μs |
|---|---|---|---|---|
| `get_stats` | 37 | 26.8 ms | 55.117 (−0.13%) | [17, 19, 21, 72] |
| `get_utilization` | 896 | 1.1 ms | 55.191 (no difference) | [18, 21, 329, 450] |
| `get_port_xstats_values` (2 ports) | 101 rounds | 4.8 ms per port | 55.143 (−0.08%) | [22, 23, 240, 499] |

Conclusions:

- **At one query every 1–2 seconds** (how the GUI actually polls), there is no measurable difference in throughput, loss, DP CPU or average latency. Latency max occasionally jumps to 100–200 μs anyway; the baseline A had a 180 μs sample too, so the max values of G and M are within the noise.
- Only back-to-back queries, 25–900 times the real rate, show an effect. `get_stats` lowers throughput by about 0.1%; `get_utilization` and xstats don't affect throughput but make latency spikes more frequent.
- The resulting design:
  - Stats are polled once per host, however many browsers are open.
  - `server.stats_interval` has a minimum of 0.5 seconds.
  - Per-core CPU/mbuf and xstats are off by default; the user turns them on (behind a warning quoting this data), with an interval of 1, 2, 5 or 10 seconds, and they go back to off when the backend restarts.
  - The rate chart and event log only use data already received and add no RPCs, so they are shown by default.

To rerun (stop the GUI service and set up the loopback first):

```bash
systemctl --user stop trex-gui
./run_monitor.sh                 # about 12 minutes; REPS and DURATION are adjustable
python3 analyze.py monitor-results.jsonl
python3 analyze_rpc.py monitor-rpc.jsonl
```
