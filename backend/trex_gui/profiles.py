"""Where TRex Python profiles may be loaded from (main process, no imports of them).

Loading a profile runs its code, so the GUI only offers files from folders the
server operator controls:
  - "trex":   <TRex install>/stl, the examples shipped with the host's TRex
  - "shared": <data_dir>/profiles, filled over SSH, or by upload when the config
              sets server.allow_profile_upload (off by default)

Profiles are named by (source, file name) only; a path is never taken from the
client, so nothing outside these folders can be reached.
"""
from __future__ import annotations  # ProfileDirs.list() would shadow `list` in annotations

import os
import re
import time
from pathlib import Path

from .config import HostConfig

_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*\.py")


class ProfileError(ValueError):
    pass


class ProfileDirs:
    def __init__(self, data_dir: Path):
        self.shared = data_dir / "profiles"

    def sources(self, host: HostConfig) -> list[tuple[str, Path]]:
        out = []
        if host.client_path:
            # <trex>/automation/trex_control_plane/interactive -> <trex>/stl
            stl = Path(host.client_path).resolve().parents[2] / "stl"
            if stl.is_dir():
                out.append(("trex", stl))
        out.append(("shared", self.shared))
        return out

    def list(self, host: HostConfig) -> list[dict]:
        items = []
        for source, folder in self.sources(host):
            if not folder.is_dir():
                continue
            for f in sorted(folder.glob("*.py")):
                if f.name.startswith("_") or not _NAME.fullmatch(f.name):
                    continue
                st = f.stat()
                items.append({"id": f"{source}:{f.name}", "name": f.name, "source": source, "folder": str(folder),
                              "size": st.st_size, "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
        return items

    def resolve(self, host: HostConfig, profile_id: str) -> Path:
        source, _, name = profile_id.partition(":")
        if not _NAME.fullmatch(name):
            raise ProfileError(f"invalid profile name '{name}'")
        folder = next((f for s, f in self.sources(host) if s == source), None)
        if folder is None:
            raise ProfileError(f"unknown profile folder '{source}'")
        path = folder / name
        if not path.is_file():
            raise ProfileError(f"profile '{name}' not found")
        return path

    def save_upload(self, name: str, data: bytes) -> Path:
        if not _NAME.fullmatch(name):
            raise ProfileError("profile file name must look like my_profile.py")
        self.shared.mkdir(parents=True, exist_ok=True)
        path = self.shared / name
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return path

    def delete(self, name: str):
        if not _NAME.fullmatch(name):
            raise ProfileError(f"invalid profile name '{name}'")
        (self.shared / name).unlink(missing_ok=True)
