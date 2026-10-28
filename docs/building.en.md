# Building

**English** | [繁體中文](building.md)

This document covers setting up a development environment from source, building the frontend, packaging the offline install bundle, and how to add a feature. For deploying to a TRex host see [deployment.en.md](deployment.en.md); for using the GUI see [user-guide.en.md](user-guide.en.md).

---

## 1. Requirements

| Tool | Version | Used for |
|---|---|---|
| Python | 3.10 or later; the dev machine uses 3.12 | Backend |
| Node.js + npm | 22 or later | Building the frontend; not needed on TRex hosts |
| TRex | Optional | Only for connecting to a real TRex; mock hosts work without it |

At runtime the backend depends only on FastAPI, uvicorn and PyYAML. The TRex Python client and its bundled Scapy and ZMQ are not installed; the worker imports the copy that `client_path` in the config points to.

---

## 2. Development environment

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[mock]'   # [mock]: mock hosts build packets with pip's Scapy

# Frontend
cd ../frontend
npm install

# Config
cd ..
cp config.example.yaml config.yaml   # includes one mock host; no TRex needed
```

`config.yaml` and `data/` are not under version control (see `.gitignore`); each machine keeps its own.

### Development mode

Use two terminals:

```bash
backend/.venv/bin/python -m trex_gui -c config.yaml   # backend  http://127.0.0.1:8080
cd frontend && npm run dev                            # frontend http://127.0.0.1:5173
```

Open http://127.0.0.1:5173 . Vite proxies `/api` (including WebSocket) to the backend. Frontend changes reload automatically; backend changes need a restart. If the backend isn't on port 8080, set it with an environment variable:

```bash
TREX_GUI_BACKEND=http://127.0.0.1:8096 npm run dev
```

### Mock hosts

A mock host (`mock: true`) emulates a TRex server with the same interface as the real worker, so you can develop and demo without TRex:

- **Ports**: the number is set by `mock_ports`. Ports 0/1 are an L2 pair that pretends to be "acquired by someone else and transmitting"; the other ports are L3, and their gateways answer ARP.
- **Traffic and stats**: traffic goes through a pretend device under test that loses nothing below 85% of line rate and drops the excess above it. Counters accumulate over time.
- **Other features**: namespace nodes, capture and RFC 2544 all work.

To test with several hosts, add more mock hosts to the config; each one has its own MACs.

```yaml
hosts:
  - {id: lab-a, name: Lab A, mock: true, mock_ports: 2}
  - {id: big, name: Big Box, mock: true, mock_ports: 16}
```

### Developing against a real TRex

Add a host to `config.yaml` with `client_path` pointing to `automation/trex_control_plane/interactive` from **the same release as the server**. If the dev machine isn't the TRex host, copy that directory together with `external_libs`, keeping their relative positions. The backend must reach TCP 4501 / 4500 on the TRex host.

---

## 3. Building

### Frontend

```bash
cd frontend
npm run build                     # type check (vue-tsc) + build into frontend/dist/
npx tsx scripts/check-i18n.ts     # check every UI message's syntax and that zh-TW and en have the same keys
```

- The type check in `npm run build` catches a key missing from English.
- `check-i18n.ts` also catches message syntax errors, such as a bare `{`, `@` or `|` in the text. The type check can't see these; they only fail at runtime.

The backend serves the web pages from `frontend/dist/` by default, so after a build a browser reload shows the new version; the backend doesn't need a restart.

### Backend

The backend is plain Python and needs no build. `pip install -e` is an editable install, so code changes take effect on restart.

---

## 4. The offline install bundle

TRex hosts often have no pip and no internet access, so the bundle is built on a dev machine and installed offline on the TRex host:

```bash
deploy/make-bundle.sh 3.12            # argument: the TRex host's python3 version, default 3.12
deploy/make-bundle.sh 3.10 x86_64     # second argument: CPU architecture, default x86_64
```

The output is `dist/trex-gui-<version>-py<python version>-<arch>.tar.gz`; the version comes from `backend/pyproject.toml`.

The script:
1. Builds the frontend (`npm run build`).
2. Downloads the dependency wheels for that Python version and architecture. Some are compiled, which is why the Python version must match the TRex host. This step needs internet access.
3. Packs the backend code, the frontend `dist/`, `config.example.yaml`, the install script, the systemd unit template and `docs/` together.

For installation see section 3 of [deployment.en.md](deployment.en.md).

### Updating an installed host

For a new release, run `./install.sh` from the new bundle; `config.yaml` and `data/` are kept.

During development you can update an installed host quickly by syncing the files:

```bash
rsync -a --delete --exclude __pycache__ backend/trex_gui/ <user>@<host>:trex-gui/backend/trex_gui/
rsync -a --delete frontend/dist/ <user>@<host>:trex-gui/frontend/dist/
ssh <user>@<host> 'systemctl --user restart trex-gui'
```

Frontend-only changes don't need a service restart. This doesn't update Python dependencies; if the dependencies in `pyproject.toml` change, use the bundle.

---

## 5. Code layout

```
backend/trex_gui/
  __main__.py     entry point (python -m trex_gui -c config.yaml)
  config.py       config file format and defaults
  affinity.py     applies cpu_affinity at startup
  app.py          REST and WebSocket API
  hosts.py        per-host worker processes, connection state, shared stats polling, event log
  worker.py       adapter around the TRex client, running in the worker process (op_* methods)
  mock.py         a fake TRex host with the same interface as worker.TRexAdapter
  packets.py      protocol catalog, packet building and decoding, field engine compilation,
                  header checks (runs only in the worker)
  store.py        saving stream definitions, shared templates and port profiles
  profiles.py / profileops.py
                  listing and running TRex Python profiles
  pcaps.py / pcapops.py
                  PCAP library, replay and capture
  rfc2544.py      RFC 2544 test runs and saved results
frontend/src/
  api.ts          types and calls for every API
  stores/         Pinia: hosts and port state, streams, templates, profiles
  composables/    shared stats stream, port pairs, viewport size
  components/     UI components; the editor is in editor/, monitoring in monitor/,
                  the overview in overview/, RFC 2544 in rfc2544/
  locales/        UI text, with zh-TW (zh) and English (en) side by side in each file
  theme.ts        light / dark theme
deploy/           bundle and install scripts, systemd unit template
bench/            scripts and data for the GUI's impact on traffic
docs/             deployment, user and build documentation
```

### Why the worker is a separate process

Each TRex release's client only works with the same server release and brings its own Scapy, ZMQ and PyYAML. One Python process can't load two versions, so each host gets its own process (`spawn`), and only that process imports the host's client. The main process never imports anything from TRex or Scapy, which is also why `__main__.py` only imports `argparse` at the top level.

---

## 6. Adding a feature

Taking "a new operation on a port" as the example:

1. **`worker.py`**: add `op_<name>(self, ...)` to `TRexAdapter` and call the TRex client there. The return value must be JSON-serializable.
2. **`mock.py`**: add the same method to `MockAdapter` with plausible behavior, so it can be used without TRex.
3. **`app.py`**: add a route. For operations that change state, call the worker through `act(request, host_id, "<event code>", "<name>", ...)`, which records the action, the source IP and the result in the event log (the text for event codes is in `events` in `locales/monitor.ts`). Read-only queries call `session.call("<name>", ...)` directly.
4. **`frontend/src/api.ts`**: add the types and the call.
5. **Components**: use it in `components/`.
6. **`frontend/src/locales/`**: all visible text goes here, in both `zh` and `en`. A key missing from English fails the type check.
7. **Check**: run `npm run build` and `npx tsx scripts/check-i18n.ts`, then try it on a mock host. For anything that touches TRex behavior, test it on a real TRex as well; the mock can't reproduce the exact return formats of the TRex client.

Design rules:
- **Features that send extra requests to TRex are off by default.** Make them an option the user turns on, with a warning, because every request is handled by the TRex master thread. Only features that add no requests are shown by default.
- **Warnings from the backend** (e.g. header checks) are sent as a code plus parameters and phrased by the frontend in the user's language. Don't hard-code Chinese or English text in the backend.
- **Operations that temporarily change port state** (e.g. entering service mode for a capture) must restore the previous state afterwards, not just switch it off.

---

## 7. Testing

There is no automated test suite yet. Changes are verified with:

- **Type check and UI text**: `npm run build`, `npx tsx scripts/check-i18n.ts`.
- **Mock hosts**: every screen and flow can be exercised on a mock host.
- **A real TRex**: cable two ports into a loopback (directly, or in an isolated VLAN on a switch), send traffic through the GUI's API and compare the stats.
- **Performance impact**: the scripts in `bench/`; see [bench/README.en.md](../bench/README.en.md).
