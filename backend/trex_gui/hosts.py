import asyncio
import collections
import itertools
import logging
import multiprocessing as mp
import time

from . import worker
from .config import HostConfig

log = logging.getLogger(__name__)

_mp = mp.get_context("spawn")


class HostNotFound(Exception):
    pass


class HostNotConnected(Exception):
    pass


class TRexCallError(Exception):
    """The TRex client raised an error while handling the call."""

    def __init__(self, message: str, kind: str = ""):
        super().__init__(message)
        self.kind = kind


class WorkerError(Exception):
    """The worker process died or stopped answering; it has been restarted."""


class HostWorker:
    """Owns the worker process for one host and serializes calls to it."""

    def __init__(self, cfg: HostConfig):
        self._cfg = cfg
        self._proc = None
        self._conn = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    def _start(self):
        parent, child = _mp.Pipe()
        self._proc = _mp.Process(
            target=worker.run,
            args=(child, self._cfg.to_worker_dict()),
            name=f"trex-worker-{self._cfg.id}",
            daemon=True,
        )
        self._proc.start()
        child.close()
        self._conn = parent

    def _kill(self):
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(timeout=2)
        self._proc = None
        self._conn = None

    def _roundtrip(self, op: str, args: dict, timeout: float):
        req_id = next(self._ids)
        try:
            self._conn.send({"id": req_id, "op": op, "args": args})
            if not self._conn.poll(timeout):
                # A late reply would desynchronize the pipe, so the process has to go.
                self._kill()
                raise WorkerError(f"'{op}' timed out after {timeout}s")
            reply = self._conn.recv()
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError) as e:
            self._kill()
            raise WorkerError(f"worker process died during '{op}': {e}")
        if not reply["ok"]:
            raise TRexCallError(reply["error"], reply.get("kind", ""))
        return reply["result"]

    async def call(self, op: str, timeout: float = 30.0, **args):
        async with self._lock:
            if self._proc is not None and not self._proc.is_alive():
                # It died on its own; its TRex connection died with it. Say so rather
                # than quietly starting a fresh, unconnected worker.
                code = self._proc.exitcode
                self._kill()
                raise WorkerError(f"worker process exited unexpectedly (exit code {code}); reconnect")
            if self._proc is None:
                self._start()
            return await asyncio.to_thread(self._roundtrip, op, args, timeout)

    async def stop(self):
        async with self._lock:
            if self._proc is None:
                return
            try:
                self._conn.send(None)
                await asyncio.to_thread(self._proc.join, 5)
            except (BrokenPipeError, OSError):
                pass
            self._kill()


EVENT_LOG_SIZE = 500
MONITOR_INTERVALS = (1.0, 2.0, 5.0, 10.0)


class HostSession:
    """Connection state and the shared stats poller for one TRex host.

    However many browsers watch a host, its stats are fetched once per interval:
    every RPC lands on the TRex master thread.
    """

    def __init__(self, cfg: HostConfig, stats_interval: float):
        self.cfg = cfg
        self.worker = HostWorker(cfg)
        self.connected = False
        self.server_version: dict | None = None
        self.server_started: str | None = None
        self.last_error: str | None = None
        self._stats_interval = stats_interval
        # port -> the Python profile last started there (cleared when GUI streams start)
        self.profile_runs: dict[int, dict] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._poll_task: asyncio.Task | None = None
        # Event log: TRex async events + actions done through the GUI. In memory only.
        self._events: collections.deque = collections.deque(maxlen=EVENT_LOG_SIZE)
        self._event_seq = itertools.count(1)
        self._unsent: list[dict] = []
        # Opt-in monitoring. Each part adds RPC work on the TRex master thread, so all
        # start off and reset to off when the backend restarts.
        self.monitor = {"cpu": False, "xstats": False, "interval": 2.0}
        # The RFC 2544 run in progress on this host, if any (rfc2544.Rfc2544Job).
        self.rfc = None
        self._extra_at = 0.0

    def summary(self) -> dict:
        return {
            "id": self.cfg.id,
            "name": self.cfg.name,
            "server": "mock" if self.cfg.mock else f"{self.cfg.server}:{self.cfg.sync_port}",
            "mock": self.cfg.mock,
            "connected": self.connected,
            "server_version": self.server_version,
            "server_started": self.server_started,
            "last_error": self.last_error,
        }

    async def connect(self):
        try:
            info = await self.worker.call("connect")
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            raise
        self.connected = True
        self.server_version = info.get("server_version")
        self.server_started = info.get("server_started")
        self.last_error = None

    async def disconnect(self):
        try:
            await self.worker.call("disconnect")
        finally:
            self.connected = False

    async def call(self, op: str, **args):
        if not self.connected:
            raise HostNotConnected(f"host '{self.cfg.id}' is not connected")
        return await self.call_offline(op, **args)

    async def call_offline(self, op: str, **args):
        """For ops that only need the worker's TRex client library, not a server
        connection (protocol catalog, packet building)."""
        try:
            return await self.worker.call(op, timeout=60.0, **args)
        except WorkerError as e:
            self.connected = False
            self.last_error = str(e)
            raise
        except TRexCallError as e:
            if e.kind == "ConnectionLost":
                self.connected = False
                self.last_error = str(e)
            raise

    def log(self, source: str, code: str, level: str = "info", client: str | None = None,
            message: str = "", **params):
        """Add to the event log. source "gui": an action, `code` is translated by the
        UI (locales/monitor.ts events.*); source "trex": `message` is TRex's text."""
        ev = {"seq": next(self._event_seq), "ts": time.time(), "source": source, "level": level, "code": code,
              "params": params, "client": client, "message": message}
        self._events.append(ev)
        if self._subscribers:  # otherwise new viewers read the history from events()
            self._unsent.append(ev)

    def events(self) -> list[dict]:
        return list(self._events)

    def set_monitor(self, cpu: bool, xstats: bool, interval: float, client: str | None):
        changed = {k: v for k, v in (("cpu", cpu), ("xstats", xstats)) if self.monitor[k] != v}
        self.monitor = {"cpu": cpu, "xstats": xstats, "interval": interval}
        self._extra_at = 0.0
        for k, v in changed.items():
            self.log("gui", "monitorOn" if v else "monitorOff", client=client, what=k)
        return self.monitor

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._subscribers.add(q)
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    async def _poll_loop(self):
        while self._subscribers:
            if self.connected:
                try:
                    msg = {"type": "stats", "ts": time.time(), **(await self.call("stats"))}
                    for e in msg.pop("events", []):
                        self.log("trex", "trex", level=e["level"], message=e["message"], origin=e["origin"], at=e["ts"])
                    await self._add_extra(msg)
                except Exception as e:
                    msg = {"type": "error", "error": str(e)}
            else:
                msg = {"type": "disconnected"}
            msg["monitor"] = self.monitor
            msg["events"], self._unsent = self._unsent, []
            for q in list(self._subscribers):
                if q.full():
                    q.get_nowait()  # slow consumer: drop its oldest sample
                q.put_nowait(msg)
            await asyncio.sleep(self._stats_interval)

    async def _add_extra(self, msg: dict):
        want = {k: self.monitor[k] for k in ("cpu", "xstats")}
        if not any(want.values()) or time.monotonic() - self._extra_at < self.monitor["interval"]:
            return
        self._extra_at = time.monotonic()
        try:
            msg["extra"] = {"ts": time.time(), **(await self.call("monitor_extra", **want))}
        except TRexCallError as e:
            msg["extra"] = {"ts": time.time(), "error": str(e)}

    async def close(self):
        if self._poll_task:
            self._poll_task.cancel()
        await self.worker.stop()


class HostManager:
    def __init__(self, hosts: list[HostConfig], stats_interval: float):
        self._sessions = {h.id: HostSession(h, stats_interval) for h in hosts}

    def all(self) -> list[HostSession]:
        return list(self._sessions.values())

    def get(self, host_id: str) -> HostSession:
        try:
            return self._sessions[host_id]
        except KeyError:
            raise HostNotFound(f"unknown host '{host_id}'")

    async def close(self):
        await asyncio.gather(*(s.close() for s in self._sessions.values()), return_exceptions=True)
