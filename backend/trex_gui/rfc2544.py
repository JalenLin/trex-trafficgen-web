"""RFC 2544 benchmarks run through a host's worker: throughput, latency, frame
loss rate and back-to-back frames.

Each trial is: clear stats, start the test streams for a fixed time, wait, read
the flow-stats (pg_id) counters. The waiting happens here in asyncio, not in the
worker, so the host's stats polling keeps running during a test. Loss is counted
per direction from the NICs' port counters (TX port opackets vs RX port ipackets,
cleared before each trial): flow stats (pg_id) are counted in software by TRex's
RX core on some NICs (mlx5) and fall behind at millions of packets per second,
which would read as loss. Only the 1 kpps latency stream uses a pg_id.

Log lines and results carry codes + numbers; the UI words them (locales/rfc2544.ts).
"""
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .packets import FCS_LEN

TESTS = ("throughput", "latency", "frame_loss", "back_to_back")
DEFAULT_SIZES = [64, 128, 256, 512, 1024, 1280, 1518]
PG_LATENCY = 4100  # latency streams' pg_id (TX port number added)
LATENCY_PPS = 1000
LINE_OVERHEAD = 20  # preamble + SFD + inter-frame gap, bytes
MAX_BINARY_STEPS = 20


class Rfc2544Error(Exception):
    pass


@dataclass
class Rfc2544Config:
    pairs: list[dict]  # [{"tx": 0, "rx": 1}, ...], ports of this host
    bidirectional: bool = True
    frame_sizes: list[int] = field(default_factory=lambda: list(DEFAULT_SIZES))
    tests: list[str] = field(default_factory=lambda: ["throughput", "latency"])
    trial_s: float = 10.0
    resolution_pct: float = 0.5
    max_rate_pct: float = 100.0
    loss_tolerance_pct: float = 0.0
    frame_loss_step_pct: float = 10.0
    b2b_max_s: float = 2.0
    settle_s: float = 1.0

    def validate(self):
        if not self.pairs:
            raise Rfc2544Error("choose at least one TX → RX port pair")
        for p in self.pairs:
            if int(p["tx"]) == int(p["rx"]):
                raise Rfc2544Error("a pair needs two different ports")
        if not self.frame_sizes or any(not 64 <= int(s) <= 9216 for s in self.frame_sizes):
            raise Rfc2544Error("frame sizes must be 64..9216 bytes")
        bad = [t for t in self.tests if t not in TESTS]
        if bad or not self.tests:
            raise Rfc2544Error(f"tests must be some of {', '.join(TESTS)}")
        if not 1 <= self.trial_s <= 600:
            raise Rfc2544Error("trial duration must be 1..600 s")
        if not 0.01 <= self.resolution_pct <= 50:
            raise Rfc2544Error("resolution must be 0.01..50 %")
        if not 1 <= self.max_rate_pct <= 100:
            raise Rfc2544Error("maximum rate must be 1..100 % of line rate")
        if not 0 <= self.loss_tolerance_pct < 100:
            raise Rfc2544Error("acceptable loss must be 0..100 %")
        if not 1 <= self.frame_loss_step_pct <= 50:
            raise Rfc2544Error("frame loss step must be 1..50 %")
        if not 0.01 <= self.b2b_max_s <= 10:
            raise Rfc2544Error("longest burst must be 0.01..10 s")

    def directions(self) -> list[tuple[int, int]]:
        out = []
        for p in self.pairs:
            tx, rx = int(p["tx"]), int(p["rx"])
            out.append((tx, rx))
            if self.bidirectional:
                out.append((rx, tx))
        if len({tx for tx, _ in out}) != len(out):
            raise Rfc2544Error("a port can only send in one direction of one pair")
        return out


def line_pps(speed_gbps: float, frame: int) -> float:
    return speed_gbps * 1e9 / ((frame + LINE_OVERHEAD) * 8)


class Rfc2544Job:
    def __init__(self, host_id: str, config: Rfc2544Config, client: str | None):
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.host_id = host_id
        self.config = config
        self.client = client
        self.state = "running"  # running | done | stopped | error
        self.started = time.time()
        self.finished: float | None = None
        self.error: str | None = None
        self.progress: dict = {}
        self.log: list[dict] = []
        self.results: dict = {t: [] for t in config.tests}
        self.trials = 0
        self.speeds: dict[int, float] = {}
        self._stop = False
        self.task: asyncio.Task | None = None

    # --- state for the API ---

    def summary(self) -> dict:
        return {"id": self.id, "state": self.state, "started": self.started, "finished": self.finished,
                "client": self.client, "tests": self.config.tests, "frame_sizes": self.config.frame_sizes,
                "pairs": self.config.pairs, "bidirectional": self.config.bidirectional}

    def to_dict(self) -> dict:
        return {**self.summary(), "config": asdict(self.config), "progress": self.progress, "log": self.log,
                "results": self.results, "trials": self.trials, "error": self.error, "speeds": self.speeds}

    def note(self, code: str, **params):
        self.log.append({"ts": time.time(), "code": code, "params": params})
        del self.log[:-500]

    def stop(self):
        self._stop = True

    def _check_stop(self):
        if self._stop:
            raise asyncio.CancelledError()

    # --- one trial ---

    def _streams(self, size: int, rate_pct: float, burst: int | None, latency: bool) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for tx, rx in self.config.directions():
            pct = rate_pct
            streams = []
            if latency:
                # make room for the latency stream so the total stays at rate_pct
                pct = max(0.01, rate_pct - LATENCY_PPS / line_pps(self.speeds[tx], size) * 100)
                streams.append(self._stream(f"rfc2544-lat-{tx}", tx, rx, size, {"unit": "pps", "value": LATENCY_PPS},
                                            {"type": "continuous"}, {"type": "latency", "pg_id": PG_LATENCY + tx}))
            mode = {"type": "single_burst", "total_pkts": burst} if burst else {"type": "continuous"}
            streams.insert(0, self._stream(f"rfc2544-{tx}", tx, rx, size, {"unit": "percentage", "value": pct}, mode,
                                           {"type": "none"}))
            out[tx] = streams
        return out

    @staticmethod
    def _stream(sid, tx, rx, size, rate, mode, flow_stats) -> dict:
        # Distinct addresses per direction (UDP, fixed size). The source address walks
        # through 253 values so the receiving NIC spreads frames over its RX queues (RSS);
        # a single 5-tuple lands on one queue and one core, which drops small frames at
        # rates far below what the path can carry.
        vm = [{"layer": 1, "field": "src", "op": "inc", "start": f"198.18.{tx}.2", "end": f"198.18.{tx}.254", "step": 1}]
        if flow_stats.get("type") == "latency":
            vm = []  # one flow keeps latency sequence checks meaningful
        return {"id": sid, "name": sid, "enabled": True, "self_start": True, "vm": vm, "mode": mode, "rate": rate,
                "flow_stats": flow_stats,
                "packet": {"layers": [{"proto": "Ether", "fields": {}},
                                      {"proto": "IP", "fields": {"src": f"198.18.{tx}.2", "dst": f"198.19.{rx}.2"}},
                                      {"proto": "UDP", "fields": {"sport": 1024 + tx, "dport": 1024 + rx}}],
                           "frame_size": size}}

    async def _trial(self, session, size: int, rate_pct: float, burst: int | None = None, latency: bool = False) -> dict:
        self._check_stop()
        dirs = self.config.directions()
        txs = sorted({tx for tx, _ in dirs})
        await session.call("clear_stats", ports=None)
        duration = self.config.trial_s
        if burst:
            duration = burst / (line_pps(min(self.speeds[t] for t in txs), size) * rate_pct / 100)
        await session.call("start", port_streams=self._streams(size, rate_pct, burst, latency), mult="1", force=True,
                           duration=-1 if burst else duration)
        self.trials += 1
        deadline = time.monotonic() + duration + 30
        await asyncio.sleep(duration)
        while time.monotonic() < deadline:  # bursts end by themselves; continuous ends at `duration`
            ports = await session.call("ports")
            if all(p["status"] == "IDLE" for p in ports if p["id"] in txs):
                break
            await asyncio.sleep(0.2)
        else:
            await session.call("stop", ports=txs)
        await asyncio.sleep(self.config.settle_s)  # frames still in flight
        stats = await session.call("stats")
        pgids = {int(k): v for k, v in (stats.get("pgids") or {}).items()}
        counters = {int(k): v for k, v in (stats.get("ports") or {}).items()}
        out = {"size": size, "rate_pct": round(rate_pct, 4), "dirs": []}
        for tx, rx in dirs:
            sent = int((counters.get(tx) or {}).get("opackets") or 0)
            # A few stray frames (a switch's LLDP) can arrive too; never count more than was sent.
            got = min(int((counters.get(rx) or {}).get("ipackets") or 0), sent)
            # What TRex actually put on the wire: it may not reach the requested rate
            # (CPU-bound small frames), and loss must be judged at the real load.
            offered = sent / (line_pps(self.speeds[tx], size) * duration) * 100 if duration and not burst else rate_pct
            entry = {"tx": tx, "rx": rx, "sent": sent, "received": got, "offered_pct": round(offered, 4),
                     "loss_pct": (sent - got) / sent * 100 if sent else None}
            if latency:
                lat = (pgids.get(PG_LATENCY + tx) or {}).get("latency") or {}
                entry["latency"] = {k: lat.get(k) for k in ("total_min", "average", "total_max", "jitter", "dropped")}
            out["dirs"].append(entry)
        return out

    def _passed(self, trial: dict) -> bool:
        return all(d["sent"] > 0 and d["loss_pct"] is not None and d["loss_pct"] <= self.config.loss_tolerance_pct
                   for d in trial["dirs"])

    # --- the four tests ---

    async def _throughput(self, session, size: int) -> dict:
        c = self.config
        hi, lo = c.max_rate_pct, 0.0
        self.progress.update(test="throughput", size=size, rate_pct=hi)
        first = await self._trial(session, size, hi)
        self.note("trial", test="throughput", size=size, rate_pct=hi, loss_pct=_worst(first), passed=self._passed(first))
        best = first if self._passed(first) else None
        if not best:
            for _ in range(MAX_BINARY_STEPS):
                if hi - lo <= c.resolution_pct:
                    break
                mid = (hi + lo) / 2
                self.progress.update(rate_pct=mid)
                t = await self._trial(session, size, mid)
                ok = self._passed(t)
                self.note("trial", test="throughput", size=size, rate_pct=mid, loss_pct=_worst(t), passed=ok)
                if ok:
                    lo, best = mid, t
                else:
                    hi = mid
        rate = best["rate_pct"] if best else 0.0
        # Judge by the load actually offered (the worst direction), not the requested one.
        offered = min((d["offered_pct"] for d in best["dirs"]), default=0.0) if best else 0.0
        slowest = min(self.speeds[tx] for tx, _ in c.directions())
        pps = line_pps(slowest, size) * offered / 100
        res = {"size": size, "rate_pct": rate, "offered_pct": offered, "tx_limited": bool(best) and offered < rate * 0.98,
               "mpps": pps / 1e6, "gbps_l1": pps * (size + LINE_OVERHEAD) * 8 / 1e9,
               "gbps_l2": pps * (size - FCS_LEN) * 8 / 1e9, "trial": best}
        self.note("result", test="throughput", size=size, rate_pct=offered, mpps=res["mpps"], tx_limited=res["tx_limited"])
        return res

    async def _latency(self, session, size: int, rate_pct: float) -> dict:
        self.progress.update(test="latency", size=size, rate_pct=rate_pct)
        t = await self._trial(session, size, rate_pct, latency=True)
        self.note("trial", test="latency", size=size, rate_pct=rate_pct, loss_pct=_worst(t), passed=self._passed(t))
        res = {"size": size, "rate_pct": rate_pct, "dirs": [{k: d[k] for k in ("tx", "rx", "latency", "loss_pct")} for d in t["dirs"]]}
        avg = [d["latency"].get("average") for d in t["dirs"] if d["latency"].get("average") is not None]
        self.note("result", test="latency", size=size, avg_us=max(avg) if avg else None)
        return res

    async def _frame_loss(self, session, size: int) -> dict:
        c = self.config
        points, zero_run, rate = [], 0, c.max_rate_pct
        while rate > 0 and zero_run < 2:
            self.progress.update(test="frame_loss", size=size, rate_pct=rate)
            t = await self._trial(session, size, rate)
            loss = _worst(t)
            self.note("trial", test="frame_loss", size=size, rate_pct=rate, loss_pct=loss, passed=self._passed(t))
            points.append({"rate_pct": rate, "offered_pct": min((d["offered_pct"] for d in t["dirs"]), default=rate),
                           "loss_pct": loss})
            zero_run = zero_run + 1 if loss is not None and loss <= 0 else 0
            rate = round(rate - c.frame_loss_step_pct, 6)
        self.note("result", test="frame_loss", size=size, points=len(points))
        return {"size": size, "points": points}

    async def _back_to_back(self, session, size: int) -> dict:
        c = self.config
        slowest = min(self.speeds[tx] for tx, _ in c.directions())
        hi = max(1, int(line_pps(slowest, size) * c.max_rate_pct / 100 * c.b2b_max_s))
        lo, best = 0, 0
        self.progress.update(test="back_to_back", size=size, rate_pct=c.max_rate_pct, burst=hi)
        t = await self._trial(session, size, c.max_rate_pct, burst=hi)
        self.note("trial", test="back_to_back", size=size, burst=hi, loss_pct=_worst(t), passed=self._passed(t))
        if self._passed(t):
            best = hi
        else:
            for _ in range(MAX_BINARY_STEPS):
                if hi - lo <= max(1, hi // 100):  # within 1 %
                    break
                mid = (hi + lo) // 2
                self.progress.update(burst=mid)
                t = await self._trial(session, size, c.max_rate_pct, burst=mid)
                ok = self._passed(t)
                self.note("trial", test="back_to_back", size=size, burst=mid, loss_pct=_worst(t), passed=ok)
                lo, hi = (mid, hi) if ok else (lo, mid)
                best = lo
        res = {"size": size, "frames": best, "seconds": best / (line_pps(slowest, size) * c.max_rate_pct / 100),
               "capped": best >= int(line_pps(slowest, size) * c.max_rate_pct / 100 * c.b2b_max_s)}
        self.note("result", test="back_to_back", size=size, frames=best)
        return res

    # --- whole run ---

    async def run(self, session, on_end):
        c = self.config
        txs = sorted({p for d in c.directions() for p in d})
        try:
            ports = {p["id"]: p for p in await session.call("ports")}
            missing = [p for p in txs if p not in ports or not ports[p]["acquired"]]
            if missing:
                raise Rfc2544Error(f"acquire port(s) {', '.join(map(str, missing))} first")
            self.speeds = {p: float(ports[p].get("speed_gbps") or 0) or 10.0 for p in txs}
            self.note("start", directions=[f"{tx}→{rx}" for tx, rx in c.directions()], sizes=c.frame_sizes, tests=c.tests)
            for size in c.frame_sizes:
                tp = None
                if "throughput" in c.tests:
                    tp = await self._throughput(session, size)
                    self.results["throughput"].append(tp)
                if "latency" in c.tests:
                    rate = tp["rate_pct"] if tp else c.max_rate_pct
                    if rate > 0:
                        self.results["latency"].append(await self._latency(session, size, rate))
                if "frame_loss" in c.tests:
                    self.results["frame_loss"].append(await self._frame_loss(session, size))
                if "back_to_back" in c.tests:
                    self.results["back_to_back"].append(await self._back_to_back(session, size))
            self.state = "done"
            self.note("done")
        except asyncio.CancelledError:
            self.state = "stopped"
            self.note("stopped")
        except Exception as e:
            self.state, self.error = "error", str(e)
            self.note("error", error=str(e))
        finally:
            self.finished = time.time()
            self.progress = {}
            try:
                await session.call("stop", ports=txs)
            except Exception:
                pass
            on_end(self)


def _worst(trial: dict):
    losses = [d["loss_pct"] for d in trial["dirs"] if d["loss_pct"] is not None]
    return max(losses) if losses else None


class Rfc2544Store:
    """Finished runs, one JSON file each: <data_dir>/<host>/rfc2544/<id>.json."""

    def __init__(self, data_dir: Path):
        self.root = data_dir

    def _dir(self, host_id: str) -> Path:
        return self.root / host_id / "rfc2544"

    def save(self, job: Rfc2544Job):
        d = self._dir(job.host_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{job.id}.tmp"
        tmp.write_text(json.dumps(job.to_dict()))
        os.replace(tmp, d / f"{job.id}.json")

    def list(self, host_id: str) -> list[dict]:
        out = []
        for f in sorted(self._dir(host_id).glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            out.append({k: data.get(k) for k in ("id", "state", "started", "finished", "client", "tests", "frame_sizes",
                                                  "pairs", "bidirectional")})
        return out

    def get(self, host_id: str, run_id: str) -> dict:
        path = self._path(host_id, run_id)
        if not path.is_file():
            raise Rfc2544Error(f"no RFC 2544 result '{run_id}'")
        return json.loads(path.read_text())

    def delete(self, host_id: str, run_id: str):
        self._path(host_id, run_id).unlink(missing_ok=True)

    def _path(self, host_id: str, run_id: str) -> Path:
        if not run_id.replace("-", "").isalnum():
            raise Rfc2544Error("invalid result id")
        return self._dir(host_id) / f"{run_id}.json"
