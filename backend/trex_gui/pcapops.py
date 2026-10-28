"""PCAP preview and import, run inside worker processes (needs the host's Scapy)."""
from .packets import Catalog
from .pcaps import read_packets

PREVIEW_MAX = 500


def list_packets(catalog: Catalog, path: str, start: int = 0, count: int = 100) -> list[dict]:
    """A page of packets: index, time from the first packet, length, one-line summary.

    Takes the catalog only to make sure every layer is loaded, so Ether() dissects
    past L2 (IP, UDP, ...) instead of stopping at Raw.
    """
    from scapy.layers.l2 import Ether

    count = min(count, PREVIEW_MAX)
    out, first = [], None
    for i, (ts, data) in enumerate(read_packets(path)):
        first = ts if first is None else first
        if i < start:
            continue
        if len(out) >= count:
            break
        try:
            summary = Ether(data).summary()
        except Exception as e:
            summary = f"(cannot decode: {type(e).__name__})"
        out.append({"index": i, "ts": round(ts - first, 6), "length": len(data), "summary": summary})
    return out


def to_streams(catalog: Catalog, path: str, indices: list[int], name: str) -> list[dict]:
    """Editable streams from chosen packets; each reproduces its frame byte for byte."""
    wanted = set(indices)
    frames = {i: data for i, (_, data) in enumerate(read_packets(path)) if i in wanted}
    streams = []
    for i in indices:
        if i not in frames:
            raise ValueError(f"packet #{i + 1} is not in the pcap")
        spec = catalog.packet_to_spec(frames[i])
        streams.append({
            "name": f"{name} #{i + 1}",
            "enabled": True,
            "packet": {"layers": spec["layers"], "frame_size": None},
            "vm": [],
            "mode": {"type": "continuous"},
            "rate": {"unit": "pps", "value": 1000},
            "flow_stats": {"type": "none"},
            "self_start": True,
            "next": None,
            "import_note": spec["note"],
            "import_note_code": spec.get("note_code"),
        })
    return streams
