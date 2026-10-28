# TRex GUI

**English** | [繁體中文](README.md)

A web GUI for Cisco TRex in stateless mode. It replaces [trex-stateless-gui](https://github.com/cisco-system-traffic-generator/trex-stateless-gui), which can no longer connect to current TRex releases.

## Documentation

| Document | Contents |
|---|---|
| [User guide](docs/user-guide.en.md) | Using the GUI: sending traffic, the stream editor, stats and monitoring, port settings, PCAP, the multi-host overview, RFC 2544, session export/import |
| [Building](docs/building.en.md) | Development setup, building the frontend, the offline install bundle, code layout, how to add a feature |
| [Deployment](docs/deployment.en.md) | Installing on a TRex host, CPU pinning, opening access, day-to-day operation, troubleshooting |
| [Benchmarks](bench/README.en.md) | Measured impact of the GUI and each kind of monitoring on traffic |

## Architecture

```
Browser (Vue 3 + Naive UI)
   │  HTTP / WebSocket
Backend (FastAPI)  ── one worker process per TRex host
   │                   └ imports the official Python client shipped with that TRex release
TRex server (ZMQ 4501 RPC / 4500 async)
```

- **No home-grown TRex protocol.** Every TRex release ships its own client, and the worker imports that copy, so the protocol always matches the server after an upgrade. The old GUI hand-wrote its JSON-RPC calls, which is why it stopped working entirely when the API moved from 4.x to 5.x.
- **One process per host.** A single Python process cannot load two versions of the client, so separate processes let the GUI talk to different TRex versions at the same time.
- **Shared stats polling.** Each host's stats are polled once and fanned out to every open browser, because every RPC runs on the TRex master thread. Port state and owners are pushed along with the stats; they come from the TRex client's async events and add no RPCs.
- **No hard-coded protocol list.** The TRex packet builder takes Scapy packets, so "the headers TRex supports" are all the layers (core and contrib) in the Scapy bundled with that TRex release. The worker reads each protocol's field definitions from that Scapy, and the frontend builds the edit forms from them. TRex v3.08 has about 2,600 protocols.
- **The GUI keeps the stream definitions.** TRex only stores compiled streams and can't turn them back into editable layers and fields, so the GUI saves them as JSON (`data/<host>/port-<n>.json`) and sends them to TRex on Start. Templates are in `data/templates.json`, pcaps in `data/pcaps/`, and port profiles in `data/<host>/port-profiles.json`.
- **What is stored where.** Shared data that must not be lost (streams, shared templates) lives on the backend. Personal templates live in the browser. Personal preferences (selected ports, layout, recent values, unsaved drafts) live in browser localStorage; clearing browser data resets them without affecting anyone else.
- **Header checks follow Scapy's binding table.** Whether layer B can follow layer A is decided from the same data Scapy uses to fill in type/proto fields (`bind_layers`), so the check works for every protocol without per-protocol rules.
- **Python profiles run on the backend.** A TRex `.py` profile is code, not data: the worker runs it on load and sends the resulting streams to TRex. The GUI only lists two folders on the server: TRex's own `<trex>/stl` (derived from `client_path`, so it is found only when `client_path` points into the TRex install) and `data/profiles`. Profile parameters (argparse options or `get_streams` keyword arguments) become a form automatically.
- **Monitoring must not disturb the test.** Every RPC is handled by the TRex master thread. The cost of each kind of monitoring was measured ([bench/README.en.md](bench/README.en.md)). The rate chart and event log add no RPCs and are shown by default. Per-core CPU/mbuf and xstats add RPCs, so they are off by default; users turn them on in the Monitor tab, behind a warning that quotes the measurements. `server.stats_interval` has a minimum of 0.5 seconds.
- **Two UI languages.** The interface is available in Traditional Chinese and English, switched at the top right and remembered in the browser; the first visit follows the browser language. All text is in `frontend/src/locales/<area>.ts`, with both languages side by side in each file; a key missing from English fails the type check. Backend warnings are sent as a code plus parameters and phrased by the frontend in the chosen language. Errors and events from TRex itself stay in their original English.
- **The backend can run anywhere.** Install it on each TRex host and let users connect with a browser, or install it on another machine. On a TRex host it **must** be pinned with `server.cpu_affinity` to CPUs TRex doesn't use for traffic, or it will affect latency. See [Deployment](docs/deployment.en.md).

## Quick start

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[mock]'   # [mock]: mock hosts build packets with pip's Scapy

# Frontend
cd ../frontend
npm install
npm run build

# Configure and run
cd ..
cp config.example.yaml config.yaml   # includes one mock host, so no TRex is needed to try it
backend/.venv/bin/python -m trex_gui -c config.yaml
```

Open http://127.0.0.1:8080 .

## Deploying to a TRex host

Use the offline install bundle. It needs no pip, internet access or sudo, and the install script sets up CPU pinning automatically:

```bash
deploy/make-bundle.sh 3.12      # on the dev machine; the argument is the TRex host's python3 version
# copy the tar.gz from dist/ to the TRex host, extract it and run ./install.sh
```

For the full steps, how to choose CPUs and how to verify the setup, see [docs/deployment.en.md](docs/deployment.en.md).

## Connecting to a real TRex

Add a host to `config.yaml`, with `client_path` pointing to the client from **the same release as the server**:

```yaml
hosts:
  - id: lab-a
    name: Lab A
    server: 192.0.2.10
    client_path: /opt/trex/v3.06/automation/trex_control_plane/interactive
```

- **Backend and TRex on different machines:** copy `automation/trex_control_plane/interactive` and `external_libs` from the TRex install together, keeping their relative positions (`external_libs` is three levels above `interactive`), or set `ext_libs_path`.
- **After a TRex upgrade:** copy them again, or just change the path.
- **Firewall:** the backend machine must reach TCP 4501 and 4500 on the TRex host.

## Development

```bash
backend/.venv/bin/python -m trex_gui -c config.yaml   # backend :8080
cd frontend && npm run dev                            # frontend :5173, /api is proxied to the backend
```

For the code layout, building, packaging and how to add a feature, see [Building](docs/building.en.md).

## Security

There is **no login yet**; all users share one TRex username (`username` in the config). Because Python profiles run on the backend, uploading profiles from the web page is off by default (`server.allow_profile_upload`); administrators copy files into `data/profiles` over SSH. By default the backend listens on `127.0.0.1` only. On an isolated lab network you can listen on `0.0.0.0` (TRex's own RPC ports have no authentication either); otherwise use an SSH tunnel. See section 5 of [Deployment](docs/deployment.en.md).

## Status

- [x] Multiple hosts, connect and disconnect
- [x] Port list, acquire and release (including force acquire)
- [x] Live stats over WebSocket, clear stats
- [x] Deployment on TRex hosts: CPU pinning, offline install bundle, systemd service
- [x] Stream editor: every protocol TRex supports, field forms, hex and decoded preview
- [x] Field engine: increment, decrement, random, including bit fields (VLAN ID, MPLS label, …), with checksums fixed automatically
- [x] Transmit modes: continuous, single burst, multi-burst; rates in pps, bps or % of line rate; pg_id for flow stats and latency
- [x] Multiple ports: acquire, start, stop, pause, resume and change rate for the selected ports; copy streams to several ports; stats with ports as rows or columns
- [x] pg_id / latency stats: TX/RX per pg, packets per port, latency avg/min/max/jitter, sequence checks, latency histogram
- [x] Port settings: L2 (destination MAC) / L3 (IPv4 + gateway, resolved by ARP), VLAN / QinQ, IPv6, promiscuous, multicast, ping
- [x] Releasing a port also removes the streams the GUI put on TRex
- [x] Header sanity checks (warn only, never block, so malformed packets can still be sent on purpose for negative tests): layers that don't fit, manual fields that contradict the next layer, manual len/chksum, frame size, TRex limits for flow stats and latency
- [x] Stream templates in two kinds: personal (in the browser, visible only to you, exportable/importable as JSON) and shared (on the backend, for everyone and every TRex host); either can be copied to the other
- [x] Remembered preferences (browser localStorage, per person): last host, selected ports, tab, stats layout, rate multiplier history, recent protocols, ping targets, unsaved editor drafts
- [x] Port settings applied in bulk: VLAN, IPv6 on/off, promiscuous, multicast, flow control to all selected ports at once
- [x] Link up/down and flow control (shown only when the NIC supports them)
- [x] Port profiles: save the L2/L3 settings of several ports as a set (on the backend, per TRex host) and preview how each port will change before applying
- [x] Detects a TRex restart or port settings changed outside the GUI and offers to re-apply the last profile (never automatically)
- [x] When TRex disconnects or a worker process exits, the host shows as disconnected with the reason
- [x] PCAP: library (upload pcap/pcapng, download, rename), replay (original timing with speed-up / fixed gap, count, time limit, MAC source), preview and convert to streams (exact original packets), capture TX/RX into the library
- [x] Variable packet size: fixed, increment, decrement, random, with IP / IPv6 / UDP length fields and checksums fixed automatically; built-in IMIX template (64/594/1518, 7:4:1)
- [x] Transmit duration (stop automatically after N seconds) and Reset (stop, remove streams on TRex, clear port stats, turn off service mode, keep the ports)
- [x] TRex Python profiles: list TRex's examples and the shared folder, parameter form, load per port and start (multiplier, duration)
- [x] Monitor tab: rate chart (total of selected ports or per port, bps/pps, 1/5/15 minutes, table view) and event log (GUI actions with source IP, TRex events), neither adding load to TRex
- [x] Advanced monitoring (off by default, with a warning): per data-plane core utilization, mbuf usage, NIC xstats (with per-second deltas)
- [x] UI languages: Traditional Chinese, English
- [x] Appearance: light / dark / follow system (top right, remembered in the browser)
- [x] Multi-host overview: all hosts side by side (totals, per-port rates, rate chart) and port pairs across hosts (A sent vs B received, difference, loss rate, marked "running" while transmitting)
- [x] Capture works on remote hosts (packets come back over RPC into the library on the GUI machine); with service mode ticked, both TX and RX ports enter service mode so stream traffic can be captured
- [x] Per-stream control: pause, resume and change the rate of individual streams while transmitting (marked experimental by TRex; the UI says so)
- [x] Payload fill patterns: zeros, fixed byte, incrementing/decrementing bytes, random (fixed seed), repeated text, repeated hex
- [x] Send single packets: send the packet in the stream editor N times, without saving it first
- [x] Port map: links between ports and to the outside, from L2 destination MACs, L3 gateways and cross-host pairs
- [x] Session export/import: streams, port settings and port profiles of every port on a host in one JSON file; import can map to other ports or another host
- [x] Namespace nodes: emulated hosts behind a port (needs `stack: linux_based` in the TRex config; the UI explains this when it's missing)
- [x] RFC 2544: throughput, latency, frame loss, back-to-back, with result charts, history and JSON/CSV export; throughput is judged on the load actually sent, and results are flagged when TRex itself can't reach the requested rate
- [ ] User login (not planned for now)

## License

Copyright 2026 Jalen Lin. Licensed under the [Apache License 2.0](LICENSE).

This project is not affiliated with Cisco; TRex is an open-source project by Cisco. The TRex Python client and the Scapy it bundles, used at runtime, are not part of this project or its offline bundle and are used under their own licenses.
