"""Stream definitions per host and port, kept as JSON files.

TRex only holds compiled streams (raw bytes + VM program), which cannot be
turned back into editable layers, so the GUI's own copy is the source of truth.
The files are pushed to TRex when traffic starts.

Layout: <data_dir>/<host_id>/port-<n>.json  ->  {"streams": [...]}
        <data_dir>/templates.json         ->  {"templates": [...]}   shared by all hosts
        <data_dir>/<host_id>/port-profiles.json -> {"profiles": [...], "last_applied": {...} | null}
"""
import json
import os
import tempfile
import uuid
from pathlib import Path


class StoreError(ValueError):
    pass


class StreamStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, host_id: str, port: int) -> Path:
        return self.root / host_id / f"port-{int(port)}.json"

    def get(self, host_id: str, port: int) -> list[dict]:
        try:
            return json.loads(self._path(host_id, port).read_text())["streams"]
        except FileNotFoundError:
            return []

    def put(self, host_id: str, port: int, streams: list[dict]) -> list[dict]:
        self._write(self._path(host_id, port), "streams", _with_ids(streams))
        return streams

    def get_templates(self) -> list[dict]:
        try:
            return json.loads((self.root / "templates.json").read_text())["templates"]
        except FileNotFoundError:
            return []

    def put_templates(self, templates: list[dict]) -> list[dict]:
        self._write(self.root / "templates.json", "templates", _with_ids(templates))
        return templates

    # Port L2/L3 profiles are tied to one host's cabling, so they live per host.
    def get_port_profiles(self, host_id: str) -> dict:
        try:
            doc = json.loads((self.root / host_id / "port-profiles.json").read_text())
        except FileNotFoundError:
            doc = {}
        return {"profiles": doc.get("profiles", []), "last_applied": doc.get("last_applied")}

    def put_port_profiles(self, host_id: str, doc: dict) -> dict:
        path = self.root / host_id / "port-profiles.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        profiles = _with_ids(list(doc.get("profiles") or []))
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            json.dump({"profiles": profiles, "last_applied": doc.get("last_applied")}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return self.get_port_profiles(host_id)

    def _write(self, path: Path, key: str, items: list[dict]):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash never leaves a half-written file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            json.dump({key: items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def _with_ids(items: list[dict]) -> list[dict]:
    for item in items:
        item.setdefault("id", uuid.uuid4().hex[:12])
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise StoreError("duplicate id")
    return items
