"""PCAP library shared by all hosts: uploads and captures, stored as classic pcap.

Pure Python (runs in the main process, which never imports Scapy). pcapng is
converted to classic pcap on the way in, because TRex's own replay reader takes
pcap; only Ethernet captures are accepted, since TRex sends Ethernet frames.

Layout: <data_dir>/pcaps/<id>.pcap  plus  <data_dir>/pcaps/index.json
"""
from __future__ import annotations  # PcapLibrary.list() would shadow `list` in annotations

import json
import os
import struct
import tempfile
import time
import uuid
from pathlib import Path

LINKTYPE_ETHERNET = 1
LINKTYPE_NAMES = {0: "BSD loopback", 101: "raw IP", 113: "Linux cooked (tcpdump -i any)", 228: "raw IPv4", 229: "raw IPv6",
                  276: "Linux cooked v2"}
# Classic pcap magic -> (byte order, timestamp fraction units per second)
_PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000), b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000), b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
}
_PCAPNG_SHB = b"\x0a\x0d\x0d\x0a"


class PcapError(ValueError):
    pass


def _linktype_error(lt: int) -> PcapError:
    name = LINKTYPE_NAMES.get(lt, f"link type {lt}")
    return PcapError(f"only Ethernet captures can be replayed; this file is {name}. "
                     "Capture on a specific interface (e.g. tcpdump -i eth0) instead of 'any'")


def read_packets(path: Path):
    """Yield (timestamp_seconds, frame_bytes) from a pcap or pcapng file (Ethernet only)."""
    with open(path, "rb") as f:
        head = f.read(4)
        f.seek(0)
        if head in _PCAP_MAGIC:
            yield from _read_pcap(f)
        elif head == _PCAPNG_SHB:
            yield from _read_pcapng(f)
        else:
            raise PcapError("not a pcap or pcapng file")


def _read_pcap(f):
    order, units = _PCAP_MAGIC[f.read(4)]
    _, _, _, _, _, linktype = struct.unpack(order + "HHiIII", f.read(20))
    if linktype & 0xFFFF != LINKTYPE_ETHERNET:
        raise _linktype_error(linktype & 0xFFFF)
    while True:
        rec = f.read(16)
        if len(rec) < 16:
            return
        sec, frac, incl, _ = struct.unpack(order + "IIII", rec)
        data = f.read(incl)
        if len(data) < incl:
            return  # truncated last record
        yield sec + frac / units, data


def _read_pcapng(f):
    order = "<"
    interfaces: list[tuple[int, float]] = []  # (linktype, seconds per timestamp unit)
    while True:
        head = f.read(8)
        if len(head) < 8:
            return
        btype_raw, blen_raw = head[:4], head[4:]
        if btype_raw == _PCAPNG_SHB:
            bom = f.read(4)
            order = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            blen = struct.unpack(order + "I", blen_raw)[0]
            f.seek(blen - 12, 1)
            interfaces = []  # interface ids are per section
            continue
        btype, blen = struct.unpack(order + "II", head)
        body = f.read(blen - 12)
        f.read(4)  # trailing block length
        if btype == 1:  # Interface Description Block
            linktype = struct.unpack(order + "H", body[:2])[0]
            resol = 1e-6
            opts = body[8:]
            while len(opts) >= 4:
                code, length = struct.unpack(order + "HH", opts[:4])
                if code == 0:
                    break
                if code == 9 and length >= 1:  # if_tsresol
                    v = opts[4]
                    resol = 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
                opts = opts[4 + ((length + 3) & ~3):]
            interfaces.append((linktype, resol))
        elif btype == 6:  # Enhanced Packet Block
            iface, ts_hi, ts_lo, caplen, _ = struct.unpack(order + "IIIII", body[:20])
            linktype, resol = interfaces[iface]
            if linktype != LINKTYPE_ETHERNET:
                raise _linktype_error(linktype)
            yield ((ts_hi << 32) | ts_lo) * resol, body[20:20 + caplen]
        elif btype == 3:  # Simple Packet Block: no timestamp
            linktype = interfaces[0][0] if interfaces else LINKTYPE_ETHERNET
            if linktype != LINKTYPE_ETHERNET:
                raise _linktype_error(linktype)
            origlen = struct.unpack(order + "I", body[:4])[0]
            yield 0.0, body[4:4 + origlen]


def write_pcap(path: Path, packets) -> dict:
    """Write (ts, bytes) pairs as classic little-endian microsecond pcap; returns stats."""
    count, first, last, size_sum = 0, None, None, 0
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, LINKTYPE_ETHERNET))
        for ts, data in packets:
            sec = int(ts)
            usec = int(round((ts - sec) * 1_000_000))
            if usec >= 1_000_000:
                sec, usec = sec + 1, usec - 1_000_000
            f.write(struct.pack("<IIII", sec, usec, len(data), len(data)))
            f.write(data)
            count += 1
            size_sum += len(data)
            first = ts if first is None else first
            last = ts
    if not count:
        raise PcapError("the capture has no packets")
    return {"packets": count, "duration_s": round((last or 0) - (first or 0), 6), "avg_frame": round(size_sum / count, 1)}


class PcapLibrary:
    def __init__(self, root: Path):
        self.root = root / "pcaps"

    def _index(self) -> list[dict]:
        try:
            return json.loads((self.root / "index.json").read_text())["pcaps"]
        except FileNotFoundError:
            return []

    def _save_index(self, items: list[dict]):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            json.dump({"pcaps": items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.root / "index.json")

    def list(self) -> list[dict]:
        return sorted(self._index(), key=lambda m: m["created_at"], reverse=True)

    def get(self, pcap_id: str) -> dict:
        meta = next((m for m in self._index() if m["id"] == pcap_id), None)
        if meta is None:
            raise PcapError(f"unknown pcap '{pcap_id}'")
        return meta

    def path(self, pcap_id: str) -> Path:
        self.get(pcap_id)
        return self.root / f"{pcap_id}.pcap"

    def _add(self, name: str, packets, source: str) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        pcap_id = uuid.uuid4().hex[:12]
        final = self.root / f"{pcap_id}.pcap"
        stats = write_pcap(final, packets)
        meta = {"id": pcap_id, "name": name, "source": source, "size": final.stat().st_size,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **stats}
        self._save_index(self._index() + [meta])
        return meta

    def add_file(self, name: str, upload: Path) -> dict:
        """Import an uploaded pcap/pcapng (normalised to classic pcap)."""
        try:
            return self._add(name, read_packets(upload), "upload")
        except struct.error:
            raise PcapError("the file is truncated or not a valid pcap/pcapng")
        finally:
            upload.unlink(missing_ok=True)

    def add_capture(self, name: str, packets: list[tuple[float, bytes]]) -> dict:
        return self._add(name, packets, "capture")

    def rename(self, pcap_id: str, name: str) -> dict:
        items = self._index()
        for m in items:
            if m["id"] == pcap_id:
                m["name"] = name
                self._save_index(items)
                return m
        raise PcapError(f"unknown pcap '{pcap_id}'")

    def delete(self, pcap_id: str):
        self._save_index([m for m in self._index() if m["id"] != pcap_id])
        (self.root / f"{pcap_id}.pcap").unlink(missing_ok=True)
