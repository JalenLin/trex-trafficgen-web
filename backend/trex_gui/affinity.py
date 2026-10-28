"""Keep the backend off TRex's data-plane cores when both run on one machine.

Applied in the main process before any worker is spawned; workers inherit it.
See docs/deployment.md for how to choose the CPUs.
"""
import os
import sys

from .config import Config

LOCAL_ADDRESSES = {"127.0.0.1", "localhost", "::1"}


def _log(level: str, msg: str):
    # Mirror uvicorn's "LEVEL:    message" format; logging isn't configured yet.
    print(f"{level + ':':<10}{msg}", file=sys.stderr, flush=True)


def apply_cpu_affinity(config: Config):
    wanted = config.server.cpu_affinity
    if not hasattr(os, "sched_setaffinity"):
        if wanted:
            _log("WARNING", "server.cpu_affinity is only supported on Linux; ignored")
        return

    if wanted:
        os.sched_setaffinity(0, wanted)
    cpus = sorted(os.sched_getaffinity(0))
    _log("INFO", f"CPU affinity: {','.join(map(str, cpus))}")

    colocated = [h.id for h in config.hosts if not h.mock and h.server in LOCAL_ADDRESSES]
    if colocated and len(cpus) == os.cpu_count():
        _log(
            "WARNING",
            f"host(s) {', '.join(colocated)} run on this machine but the backend may use every CPU, "
            "including TRex data-plane cores. Set server.cpu_affinity (see docs/deployment.md).",
        )
