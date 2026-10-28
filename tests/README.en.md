# Tests

**English** | [繁體中文](README.md)

| Directory | Contents | Runs against |
|---|---|---|
| `backend/` | Backend API tests (pytest) covering every API | A mock host or a real TRex |
| `e2e/` | Browser end-to-end tests (Playwright) that use every screen, in both languages | Mock hosts |

For the frontend type check and UI text check, see section 3 of [docs/building.en.md](../docs/building.en.md).

**GitHub Actions**: `.github/workflows/test.yml` runs the backend tests against mock, the frontend build and UI text check, and the browser tests on every push and pull request, uploading screenshots and the backend log on failure. Tests against real TRex need a cabled loopback; run them by hand as below.

## Backend API tests

```bash
backend/.venv/bin/pip install -e 'backend[mock,test]'   # once
backend/.venv/bin/python -m pytest tests/backend
```

With no settings, the tests start their own mock backend (random port, fresh data folder). A run takes about 2.5 minutes.

### Against a real TRex

You need a running GUI backend and two ports cabled as a loopback (directly, or in a switch VLAN that contains only those two ports). Nobody else may use the two ports during the run.

```bash
TREX_GUI_URL=http://<GUI host>:8080 TREX_GUI_HOST=local TREX_GUI_PAIR=0,1 \
    backend/.venv/bin/python -m pytest tests/backend
```

| Variable | Purpose |
|---|---|
| `TREX_GUI_URL` | The GUI backend to test; mock when unset |
| `TREX_GUI_HOST` | Host id from its config, default `local` (`demo` for mock) |
| `TREX_GUI_PAIR` | The two loopback ports, default `0,1` (`2,3` for mock) |
| `TREX_GUI_PEER` | Id of a second host, for `test_cross_host.py`. p0 and p1 of the two hosts must be cabled to each other |
| `TREX_GUI_PING` | `<port>:<local IP>:<gateway>:<target>` to ping a real host (TRex ports don't answer ping) |

- **Before the run**: the tests force-acquire the two ports.
- **After the run**: they restore the ports' settings to what they were before and release the ports.
- **The two stacks**: the namespace and IPv6 tests need TRex's `stack: linux_based`; without it they are skipped or check the error message instead.

## Browser end-to-end tests

```bash
cd tests/e2e
npm ci                           # once
npx playwright-core install chromium   # once: the matching browser
node run.mjs                     # everything, about 3 minutes
node run.mjs streams pcap        # only groups whose names match (group 01 always runs)
```

- **Backend and data**: the runner starts its own mock backend on port 8098, with a fresh data folder each run.
- **Frontend build**: the frontend is rebuilt first when `frontend/src` is newer than `frontend/dist`.
- **Browser and Python**: by default the Chromium installed by `npx playwright-core install chromium` and the Python in `backend/.venv`; set `CHROME` or `E2E_PYTHON` to use others.
- **Screenshots**: saved to `$E2E_OUT/e2e-shots`.
- **Order matters**: groups share one page and run in order, and later groups use ports acquired by earlier ones, so running a single group on its own is only indicative.
- **What counts as a failure**: any page error or console error.
