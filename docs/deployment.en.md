# Deployment: running the GUI backend on a TRex host

**English** | [繁體中文](deployment.md)

This document explains how to install the GUI backend on the TRex host itself, so users connect to that host directly with a browser.

**When the backend runs on the same machine as TRex, it must be pinned to CPUs that TRex doesn't use for traffic.** The install script does this automatically. The sections below explain why, how to choose the CPUs and how to check the pinning.

If the backend runs on another machine (a management host or a PC), no pinning is needed and you can skip the CPU sections.

---

## 1. Why pin the CPU

TRex sends traffic with DPDK, and every data-plane core runs a busy-polling loop. By default Linux may schedule any process on any core, including the cores TRex is transmitting on. When the backend lands on one of them it competes with TRex for the CPU and directly affects packet timing.

Measured on the lab host on 2026-10-28: Ryzen 7 3800X, ConnectX-4 Lx 2×25G, TRex v3.08 `-c 14`, the two ports cabled as a loopback, 3 runs of 30 seconds per scenario, with 3 browsers watching live stats during the test.

| Packet | Scenario | TX Mpps | Loss | Latency avg | Latency max (6 samples) |
|---|---|---|---|---|---|
| 64B | No GUI | 55.321 | 0 | 7.0 μs | 11–23 μs |
| 64B | **GUI pinned to core 0** | 55.332 | 0 | 7.2 μs | 12–16 μs, once 131 μs |
| 64B | GUI not pinned | 55.321 | 0 | 8.5 μs | 13–17 μs, twice 99 and 200 μs |
| IMIX | No GUI | 16.369 | 0 | 9.8 μs | 13–36 μs |
| IMIX | **GUI pinned to core 0** | 16.369 | 0 | 9.7 μs | 13–27 μs |
| IMIX | GUI not pinned | 16.361 | 0 | 11.2 μs | 13–21 μs |

- **Pinned**: no measurable difference in throughput, loss or average latency.
- **Not pinned**: average latency rises by about 1.5 μs, with occasional spikes of 100 to 200 μs and a slight drop in throughput.
- **Pinning isn't zero impact either**: pinned to core 0, one of the 6 samples had a 131 μs spike, probably from sharing the core with the TRex master thread. If your tests are sensitive to the latency tail (max, jitter), see "Freeing a core" in section 2.

The raw data and scripts are in `bench/`; section 8 explains how to rerun them.

---

## 2. Choosing the CPU

### TRex thread layout

Look at the `platform` block of `/etc/trex_cfg.yaml`:

```yaml
platform:
    master_thread_id: 0       # control thread: RPC and stats, idle most of the time
    latency_thread_id: 8      # latency measurement thread
    dual_if:
      - socket: 0
        threads: [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]   # data-plane thread pool
```

Also check `-c N` in the TRex command line, the number of cores actually used for traffic:

```bash
ps -eo args | grep "[_]t-rex-64"
```

### Rules

Take the first one that applies:

1. **A physical core TRex doesn't use at all**: the best choice. For example, if TRex runs with `-c 12`, the last two entries of the threads list are unused, and if they are the two hyper-threads of one physical core, use that pair.
2. **`master_thread_id`**: the choice when no core is free, and the install script's default. The master is idle most of the time; section 1 tested this setup.
3. **Never use**:
   - `latency_thread_id`: it directly disturbs latency measurement.
   - A core in `dual_if.threads` that is in use: it directly slows traffic.
   - The hyper-thread sibling of the master, if it is a latency or data-plane thread.

To see which logical CPUs share a physical core:

```bash
lscpu -e=CPU,CORE
```

### Freeing a core

If TRex uses every core (like `-c 14` on the lab host) and you care about the latency tail, have TRex use one pair fewer (e.g. `-c 12`) and give the freed pair to the GUI. The cost is a lower maximum rate for small 64B packets, so measure first to make sure that's acceptable.

### Configuration

In `config.yaml`:

```yaml
server:
  cpu_affinity: [0]       # several are allowed, e.g. [7, 15]
```

The backend pins itself at startup, and the worker processes and threads it starts inherit the pinning. This works however the backend is started: systemd, by hand or otherwise.

If the backend detects that it shares the machine with TRex (some host in the config has `server` set to `127.0.0.1` or `localhost`) but `cpu_affinity` isn't set, it logs a `WARNING` at startup.

---

## 3. Installation

TRex hosts often have no pip, no `python3-venv` and no internet access, so the bundle is **built on a dev machine and installed offline on the TRex host**. The default install needs no sudo.

### 3.1 Build the bundle on a dev machine

```bash
deploy/make-bundle.sh 3.12        # argument: the TRex host's python3 version
# produces dist/trex-gui-<version>-py3.12-x86_64.tar.gz
```

The Python version must match the TRex host, because some dependencies are compiled wheels. Check it on the TRex host with `python3 --version`.

### 3.2 Install on the TRex host

```bash
tar xzf trex-gui-0.1.0-py3.12-x86_64.tar.gz
cd trex-gui-0.1.0-py3.12-x86_64
./install.sh
```

The install script:

1. Installs the program to `~/trex-gui` with its own Python virtual environment. No pip and no internet access needed.
2. Finds the TRex install: the running TRex first, otherwise the newest version under `/opt/trex/`.
3. Reads `master_thread_id` from `/etc/trex_cfg.yaml`, writes `config.yaml` and sets `cpu_affinity`. If the chosen core is also a latency or data-plane thread, it prints a warning.
4. Installs and starts a systemd user service.

If `config.yaml` already exists, the install script leaves it alone, so reinstalling or upgrading doesn't overwrite your changes.

### 3.3 Options

| Option | Purpose |
|---|---|
| `--prefix DIR` | Install somewhere else |
| `--trex-dir DIR` | Set the TRex install by hand when auto-detection picks the wrong version |
| `--trex-cfg FILE` | Use when the TRex config isn't at `/etc/trex_cfg.yaml` |
| `--listen ADDR` | Listen address, default `127.0.0.1`; `0.0.0.0` opens it to the whole network, see section 5. Only used when `config.yaml` is first written |
| `--system` | Install as a system service. Run it as `sudo ./install.sh --system`; the service runs as the account that ran sudo |
| `--no-service` | Only install the files, don't create a service |

### 3.4 Starting at boot

By default a user service **stops when that account logs out and doesn't start at boot**. To keep it running, either:

```bash
sudo loginctl enable-linger $USER        # option 1: keep user services running
sudo ./install.sh --system               # option 2: install as a system service instead
```

---

## 4. Verifying the pinning

After installing or changing `cpu_affinity`, run these two checks. For a system service, replace `systemctl --user` with `systemctl` and `journalctl --user` with `journalctl`.

**1. The startup log shows the right CPU and no WARNING:**

```bash
journalctl --user -u trex-gui | grep -E "CPU affinity|WARNING" | tail -2
# INFO:     CPU affinity: 0
```

**2. Every thread of every process in the service may only use the chosen CPUs.**
Worker processes only appear after connecting, so press **Connect** in the web page first, then run:

```bash
CG=$(systemctl --user show trex-gui -p ControlGroup --value)
for pid in $(cat /sys/fs/cgroup$CG/cgroup.procs); do
  grep -h Cpus_allowed_list /proc/$pid/task/*/status
done | sort | uniq -c
#      13 Cpus_allowed_list:	0
```

The output should be a single line with the CPUs you configured. A range such as `0-15` means the pinning didn't take effect.

---

## 5. How users connect

The backend listens on `127.0.0.1:8080` by default. There are two ways in:

### Option 1: open it to the network (recommended on a lab network)

Install with `--listen 0.0.0.0`, or change `server.host` in an existing `config.yaml` to `0.0.0.0` and restart the service. Users open `http://<TRex host>:8080`.

**There is no login yet**, so anyone who can reach port 8080 can control traffic. That is acceptable on an isolated lab network, because TRex's own RPC ports (4500/4501) listen on `0.0.0.0` without authentication by default, so opening the GUI adds no risk that wasn't already there. But **don't do this on a machine connected to an office or production network.**

If the host has a firewall (e.g. ufw), allow TCP 8080.

### Option 2: SSH tunnel

When the network isn't isolated enough, keep `127.0.0.1` and have users connect through an SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 <user>@<TRex host>
```

Then open http://127.0.0.1:8080 in the browser.

---

## 6. Day-to-day operation

```bash
systemctl --user status trex-gui      # status
systemctl --user restart trex-gui     # restart after changing config.yaml
journalctl --user -u trex-gui -f      # follow the log
```

**Starting by hand, without systemd**:

```bash
cd ~/trex-gui/backend && ../.venv/bin/python -m trex_gui -c ../config.yaml
```

The pinning is set in `config.yaml`, so it applies when started by hand too.

---

## 7. Upgrading and uninstalling

**Upgrade**: run `./install.sh` from the new bundle. The program and virtual environment are replaced; `config.yaml` and `data/` (the users' stream definitions) are kept.

**TRex upgrade**: change `client_path` in `config.yaml` to the new release's `automation/trex_control_plane/interactive`. If the new TRex has a different thread layout, check `cpu_affinity` as well.

**Uninstall**:

```bash
systemctl --user disable --now trex-gui
rm ~/.config/systemd/user/trex-gui.service
rm -rf ~/trex-gui          # also deletes the stream definitions in data/; back them up first if needed
```

---

## 8. Rerunning the benchmark

After changing machines, TRex versions or `-c`, rerun the test from section 1 to confirm that pinning still has no impact in the new environment.

The impact of monitoring has its own test (`bench/run_monitor.sh`); data and instructions are in [bench/README.en.md](../bench/README.en.md).

**Prerequisites**: the two TRex ports must be cabled as a loopback (directly, or in an isolated VLAN on a switch), and nobody else may use this TRex during the test.

The test switches the ports to L2 mode temporarily. **Afterwards, restore the original L3 settings: restore the switch first, then TRex**, so ARP can resolve the gateways.

Copy the project's `bench/` directory to the TRex host, then:

```bash
systemctl --user stop trex-gui       # the test starts and stops the GUI itself, so stop the service first

cd bench
DRY_RUN=1 REPS=1 ./run_all.sh        # dry run: only checks starting, stopping and pinning the GUI, no traffic
./run_all.sh                         # the real run, about 14 minutes, results in results.jsonl
python3 analyze.py results.jsonl     # print the summary table

# restore L3 mode; format is port:local IP:gateway
python3 bench.py --restore-l3 0:10.0.0.2:10.0.0.1 1:192.168.200.2:192.168.200.1
systemctl --user start trex-gui
```

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `GUI_DIR` | `~/trex-gui` | Where the GUI is installed |
| `TREX_CLIENT` | `/opt/trex/v3.08/automation/trex_control_plane/interactive` | TRex client path |
| `PIN_CPU` | `0` | CPU to pin to in scenario B |
| `REPS` / `DURATION` | `3` / `30` | Number of runs and seconds per run |

`run_all.sh` writes its own test configs (one pinned, one not) and doesn't read your `config.yaml`. It also checks the thread pinning of each scenario and aborts if it is wrong.

During the test, run `bench/subs.py` on another machine to simulate people watching stats through an SSH tunnel; otherwise the GUI doesn't poll TRex and there is nothing to measure:

```bash
ssh -f -N -L 18080:127.0.0.1:8080 <user>@<TRex host>
python3 bench/subs.py ws://127.0.0.1:18080/api/hosts/local/stats 3
```

---

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `WARNING: ... may use every CPU` at startup | The backend shares the machine with TRex but `cpu_affinity` isn't set; set it as in section 2 |
| `this bundle is for python X but python3 is Y` | The bundle's Python version doesn't match; rebuild on the dev machine with `deploy/make-bundle.sh Y` |
| `TRex client not found` | Auto-detection couldn't find TRex; pass `--trex-dir /opt/trex/vX.XX` |
| `failed to load TRex client` after pressing Connect | `client_path` in `config.yaml` is wrong, or that TRex release's client is incomplete |
| The service stops after logging out | Default behavior of user services; see section 3.4 |
| Port 8080 is in use | Change `server.port` in `config.yaml` |
