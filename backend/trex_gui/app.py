import asyncio
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .affinity import LOCAL_ADDRESSES
from .config import Config
from .hosts import MONITOR_INTERVALS, HostManager, HostNotConnected, HostNotFound, HostSession, TRexCallError, WorkerError
from .pcaps import PcapError, PcapLibrary
from .profiles import ProfileDirs, ProfileError
from .rfc2544 import DEFAULT_SIZES, Rfc2544Config, Rfc2544Error, Rfc2544Job, Rfc2544Store
from .store import StoreError, StreamStore


class BadRequest(Exception):
    pass


class PortsRequest(BaseModel):
    ports: list[int]
    force: bool = False


class ClearStatsRequest(BaseModel):
    ports: list[int] | None = None


class PacketRequest(BaseModel):
    packet: dict
    # The stream's flow stats setting, so the preview can warn about its requirements.
    flow_stats: dict | None = None


class StreamRequest(BaseModel):
    stream: dict


class StreamsBody(BaseModel):
    streams: list[dict]


class TemplatesBody(BaseModel):
    templates: list[dict]


class StartRequest(BaseModel):
    ports: list[int]
    mult: str = "1"
    force: bool = False
    duration: float = -1


class TrafficRequest(BaseModel):
    ports: list[int]


class UpdateRequest(BaseModel):
    ports: list[int]
    mult: str


class L2Config(BaseModel):
    dst_mac: str


class L3Config(BaseModel):
    src: str
    dst: str


class IPv6Config(BaseModel):
    enabled: bool
    src: str | None = None


class PortConfigRequest(BaseModel):
    """Sections left out (None) are not changed. vlan=[] removes VLAN tags."""
    vlan: list[int] | None = None
    l2: L2Config | None = None
    l3: L3Config | None = None
    ipv6: IPv6Config | None = None
    promiscuous: bool | None = None
    multicast: bool | None = None
    link_up: bool | None = None
    flow_ctrl: int | None = None


class PortProfilesDoc(BaseModel):
    profiles: list[dict]
    last_applied: dict | None = None


class RenameRequest(BaseModel):
    name: str


class ToStreamsRequest(BaseModel):
    indices: list[int]


class PushRequest(BaseModel):
    pcap_id: str
    ports: list[int]
    ipg_usec: float | None = None  # fixed gap; None = the capture's own timing
    speedup: float = 1.0
    count: int = 1  # the UI sends MAX_PUSH_COUNT for "until stopped"
    duration: float = -1
    # (TRex's is_dual needs ERF files with direction metadata, not pcap: not offered.)
    min_ipg_usec: float | None = None
    src_mac_pcap: bool = False
    dst_mac_pcap: bool = False
    force: bool = False


class CaptureRequest(BaseModel):
    tx_ports: list[int] = []
    rx_ports: list[int] = []
    limit: int = 1000
    mode: str = "fixed"
    bpf_filter: str = ""
    service: bool = False


class CaptureStopRequest(BaseModel):
    save: bool = True
    name: str = "capture"


LOCAL_PUSH_LIMIT = 1024 * 1024  # TRex's cap for pcaps sent over RPC
MAX_PUSH_COUNT = 0x3FFFFFFF  # TRex's limit; "until stopped" uses it rather than an undocumented 0


def can_push_remote(session: HostSession) -> bool:
    """TRex reads the file itself only when it shares this machine's disk."""
    return session.cfg.mock or session.cfg.server in LOCAL_ADDRESSES


class ProfileStartRequest(BaseModel):
    id: str
    ports: list[int]
    values: dict = {}
    mult: str = "1"
    duration: float = -1
    force: bool = False


class StreamControlRequest(BaseModel):
    stream_ids: list[str]
    action: str
    mult: str | None = None


class PushPacketRequest(BaseModel):
    packet: dict
    count: int = 1
    ipg_usec: float = 0.0


class NsNodeRequest(BaseModel):
    mac: str
    ipv4: str | None = None
    dg: str | None = None
    ipv6: bool = False
    vlans: list[int] = []
    mtu: int | None = None


class ServiceModeRequest(BaseModel):
    mode: str


class NsRemoveRequest(BaseModel):
    macs: list[str]


class Rfc2544Request(BaseModel):
    pairs: list[dict]
    bidirectional: bool = True
    frame_sizes: list[int] = list(DEFAULT_SIZES)
    tests: list[str] = ["throughput", "latency"]
    trial_s: float = 10.0
    resolution_pct: float = 0.5
    max_rate_pct: float = 100.0
    loss_tolerance_pct: float = 0.0
    frame_loss_step_pct: float = 10.0
    b2b_max_s: float = 2.0


class MonitorSettings(BaseModel):
    cpu: bool = False
    xstats: bool = False
    interval: float = 2.0


class PingRequest(BaseModel):
    dst_ip: str
    count: int = 3
    pkt_size: int = 64


def _api_router() -> APIRouter:
    api = APIRouter(prefix="/api")

    def hosts(request: Request) -> HostManager:
        return request.app.state.hosts

    def client_of(request: Request) -> str | None:
        return request.client.host if request.client else None

    async def act(request: Request, host_id: str, code: str, op: str, log: dict | None = None, **args):
        """Run a TRex action and record it in the host's event log (who, what, result)."""
        session = hosts(request).get(host_id)
        try:
            result = await session.call(op, **args)
        except Exception as e:
            session.log("gui", code, level="warning", client=client_of(request), error=str(e), **(log or {}))
            raise
        session.log("gui", code, client=client_of(request), **(log or {}))
        return result

    @api.get("/hosts/{host_id}/events")
    async def get_events(host_id: str, request: Request):
        return hosts(request).get(host_id).events()

    @api.get("/hosts/{host_id}/monitor")
    async def get_monitor(host_id: str, request: Request):
        return hosts(request).get(host_id).monitor

    @api.put("/hosts/{host_id}/monitor")
    async def put_monitor(host_id: str, body: MonitorSettings, request: Request):
        if body.interval not in MONITOR_INTERVALS:
            raise BadRequest(f"interval must be one of {', '.join(f'{i:g}' for i in MONITOR_INTERVALS)} seconds")
        return hosts(request).get(host_id).set_monitor(body.cpu, body.xstats, body.interval, client_of(request))

    @api.get("/hosts")
    async def list_hosts(request: Request):
        return [s.summary() for s in hosts(request).all()]

    @api.get("/hosts/{host_id}")
    async def get_host(host_id: str, request: Request):
        return hosts(request).get(host_id).summary()

    @api.post("/hosts/{host_id}/connect")
    async def connect(host_id: str, request: Request):
        session = hosts(request).get(host_id)
        try:
            await session.connect()
        except Exception as e:
            session.log("gui", "connect", level="warning", client=client_of(request), error=str(e))
            raise
        session.log("gui", "connect", client=client_of(request))
        return session.summary()

    @api.post("/hosts/{host_id}/disconnect")
    async def disconnect(host_id: str, request: Request):
        session = hosts(request).get(host_id)
        await session.disconnect()
        session.log("gui", "disconnect", client=client_of(request))
        return session.summary()

    @api.get("/hosts/{host_id}/ports")
    async def ports(host_id: str, request: Request):
        return await hosts(request).get(host_id).call("ports")

    @api.post("/hosts/{host_id}/ports/acquire")
    async def acquire(host_id: str, body: PortsRequest, request: Request):
        return await act(request, host_id, "forceAcquire" if body.force else "acquire", "acquire",
                         {"ports": body.ports}, ports=body.ports, force=body.force)

    @api.post("/hosts/{host_id}/ports/release")
    async def release(host_id: str, body: PortsRequest, request: Request):
        return await act(request, host_id, "release", "release", {"ports": body.ports}, ports=body.ports)

    @api.post("/hosts/{host_id}/ports/{port}/config")
    async def port_config(host_id: str, port: int, body: PortConfigRequest, request: Request):
        if body.l2 and body.l3:
            raise BadRequest("choose either L2 or L3, not both")
        cfg = body.model_dump(exclude_none=True)
        return await act(request, host_id, "portConfig", "port_config", {"ports": [port], "items": ", ".join(cfg)},
                         port=port, **cfg)

    @api.get("/hosts/{host_id}/port-profiles")
    async def get_port_profiles(host_id: str, request: Request):
        hosts(request).get(host_id)
        return request.app.state.store.get_port_profiles(host_id)

    @api.put("/hosts/{host_id}/port-profiles")
    async def put_port_profiles(host_id: str, body: PortProfilesDoc, request: Request):
        hosts(request).get(host_id)
        return request.app.state.store.put_port_profiles(host_id, body.model_dump())

    # --- one stream at a time, one packet at a time, namespaces ---

    @api.get("/hosts/{host_id}/ports/{port}/streams/state")
    async def stream_states(host_id: str, port: int, request: Request):
        return await hosts(request).get(host_id).call("stream_states", port=port)

    @api.post("/hosts/{host_id}/ports/{port}/streams/control")
    async def stream_control(host_id: str, port: int, body: StreamControlRequest, request: Request):
        if body.action not in ("pause", "resume", "update"):
            raise BadRequest("action must be pause, resume or update")
        if body.action == "update" and not (body.mult or "").strip():
            raise BadRequest("enter the new rate")
        if not body.stream_ids:
            raise BadRequest("choose at least one stream")
        names = {s["id"]: s.get("name") or s["id"] for s in request.app.state.store.get(host_id, port)}
        code = {"pause": "streamPause", "resume": "streamResume", "update": "streamUpdate"}[body.action]
        return await act(request, host_id, code, "stream_control",
                         {"ports": [port], "streams": ", ".join(names.get(i, i) for i in body.stream_ids), "mult": body.mult or ""},
                         port=port, stream_ids=body.stream_ids, action=body.action, mult=body.mult)

    @api.post("/hosts/{host_id}/ports/{port}/push")
    async def push_packet(host_id: str, port: int, body: PushPacketRequest, request: Request):
        return await act(request, host_id, "pushPacket", "push_packet", {"ports": [port], "count": body.count},
                         port=port, packet=body.packet, count=body.count, ipg_usec=body.ipg_usec)

    @api.post("/hosts/{host_id}/ports/{port}/service")
    async def service_mode(host_id: str, port: int, body: ServiceModeRequest, request: Request):
        return await act(request, host_id, "serviceMode", "service_mode", {"ports": [port], "mode": body.mode},
                         port=port, mode=body.mode)

    @api.get("/hosts/{host_id}/ports/{port}/ns")
    async def ns_nodes(host_id: str, port: int, request: Request):
        return await hosts(request).get(host_id).call("ns_nodes", port=port)

    @api.post("/hosts/{host_id}/ports/{port}/ns")
    async def ns_add(host_id: str, port: int, body: NsNodeRequest, request: Request):
        if not re.fullmatch(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}", body.mac):
            raise BadRequest("MAC must look like 00:11:22:33:44:55")
        return await act(request, host_id, "nsAdd", "ns_add", {"ports": [port], "mac": body.mac, "ip": body.ipv4 or ""},
                         port=port, **body.model_dump())

    @api.post("/hosts/{host_id}/ports/{port}/ns/remove")
    async def ns_remove(host_id: str, port: int, body: NsRemoveRequest, request: Request):
        return await act(request, host_id, "nsRemove", "ns_remove", {"ports": [port], "mac": ", ".join(body.macs)},
                         port=port, macs=body.macs)

    # --- RFC 2544 ---

    def rfc_busy(session: HostSession, ports) -> None:
        """Refuse to touch ports an RFC 2544 run is using."""
        job = session.rfc
        if job and job.state == "running":
            used = {p for d in job.config.directions() for p in d}
            if used & set(ports):
                raise BadRequest(f"an RFC 2544 test is running on port(s) {', '.join(map(str, sorted(used)))}; stop it first")

    @api.post("/hosts/{host_id}/rfc2544")
    async def rfc_start(host_id: str, body: Rfc2544Request, request: Request):
        session = hosts(request).get(host_id)
        if not session.connected:
            raise HostNotConnected(f"host '{host_id}' is not connected")
        if session.rfc and session.rfc.state == "running":
            raise BadRequest("an RFC 2544 test is already running on this host")
        try:
            cfg = Rfc2544Config(**body.model_dump())
            cfg.validate()
            dirs = cfg.directions()
        except Rfc2544Error as e:
            raise BadRequest(str(e))
        job = Rfc2544Job(host_id, cfg, client_of(request))
        for tx, rx in dirs:
            session.profile_runs.pop(tx, None)
        store: Rfc2544Store = request.app.state.rfc2544

        def on_end(j):
            store.save(j)
            session.log("gui", "rfcEnd", level="warning" if j.state == "error" else "info", client=j.client,
                        state=j.state, id=j.id, error=j.error or "")

        session.rfc = job
        session.log("gui", "rfcStart", client=job.client, ports=sorted({p for d in dirs for p in d}),
                    tests=", ".join(cfg.tests), id=job.id)
        job.task = asyncio.create_task(job.run(session, on_end))
        return job.to_dict()

    @api.get("/hosts/{host_id}/rfc2544")
    async def rfc_current(host_id: str, request: Request):
        job = hosts(request).get(host_id).rfc
        return job.to_dict() if job else None

    @api.post("/hosts/{host_id}/rfc2544/stop")
    async def rfc_stop(host_id: str, request: Request):
        job = hosts(request).get(host_id).rfc
        if job and job.state == "running":
            job.stop()
            if job.task:
                job.task.cancel()
        return job.to_dict() if job else None

    @api.get("/hosts/{host_id}/rfc2544/history")
    async def rfc_history(host_id: str, request: Request):
        hosts(request).get(host_id)
        return request.app.state.rfc2544.list(host_id)

    @api.get("/hosts/{host_id}/rfc2544/history/{run_id}")
    async def rfc_result(host_id: str, run_id: str, request: Request):
        hosts(request).get(host_id)
        try:
            return request.app.state.rfc2544.get(host_id, run_id)
        except Rfc2544Error as e:
            raise HostNotFound(str(e))

    @api.delete("/hosts/{host_id}/rfc2544/history/{run_id}")
    async def rfc_delete(host_id: str, run_id: str, request: Request):
        hosts(request).get(host_id)
        try:
            request.app.state.rfc2544.delete(host_id, run_id)
        except Rfc2544Error as e:
            raise BadRequest(str(e))
        return {"ok": True}

    @api.post("/hosts/{host_id}/ports/resolve")
    async def resolve(host_id: str, body: TrafficRequest, request: Request):
        return await act(request, host_id, "resolve", "resolve", {"ports": body.ports}, ports=body.ports)

    @api.post("/hosts/{host_id}/ports/{port}/ping")
    async def ping(host_id: str, port: int, body: PingRequest, request: Request):
        return await hosts(request).get(host_id).call("ping", port=port, **body.model_dump())

    @api.post("/hosts/{host_id}/stats/clear")
    async def clear_stats(host_id: str, body: ClearStatsRequest, request: Request):
        await act(request, host_id, "clearStats", "clear_stats", {"ports": body.ports or []}, ports=body.ports)
        return {"ok": True}

    # --- protocols and packets (worker only, no TRex connection needed) ---

    @api.get("/hosts/{host_id}/protocols")
    async def protocols(host_id: str, request: Request):
        return await hosts(request).get(host_id).call_offline("protocols")

    @api.get("/hosts/{host_id}/protocols/{proto}")
    async def protocol_schema(host_id: str, proto: str, request: Request):
        return await hosts(request).get(host_id).call_offline("protocol_schema", proto=proto)

    @api.post("/hosts/{host_id}/packet")
    async def build_packet(host_id: str, body: PacketRequest, request: Request):
        return await hosts(request).get(host_id).call_offline("build_packet", packet=body.packet, flow_stats=body.flow_stats)

    @api.post("/hosts/{host_id}/streams/check")
    async def check_stream(host_id: str, body: StreamRequest, request: Request):
        return await hosts(request).get(host_id).call_offline("check_stream", stream=body.stream)

    # --- stream definitions (kept by the GUI, pushed to TRex on start) ---

    @api.get("/hosts/{host_id}/ports/{port}/streams")
    async def get_streams(host_id: str, port: int, request: Request):
        hosts(request).get(host_id)
        return request.app.state.store.get(host_id, port)

    @api.put("/hosts/{host_id}/ports/{port}/streams")
    async def put_streams(host_id: str, port: int, body: StreamsBody, request: Request):
        hosts(request).get(host_id)
        return request.app.state.store.put(host_id, port, body.streams)

    # Stream templates: host-independent, shared by everyone using this backend.
    @api.get("/templates")
    async def get_templates(request: Request):
        return request.app.state.store.get_templates()

    @api.put("/templates")
    async def put_templates(body: TemplatesBody, request: Request):
        return request.app.state.store.put_templates(body.templates)

    # --- pcap library (shared by all hosts) ---

    @api.get("/pcaps")
    async def list_pcaps(request: Request):
        return request.app.state.pcaps.list()

    @api.post("/pcaps")
    async def upload_pcap(name: str, request: Request):
        """Raw file body (no multipart), streamed to disk so large captures don't sit in memory."""
        lib: PcapLibrary = request.app.state.pcaps
        limit = request.app.state.config.server.pcap_max_mb * 1024 * 1024
        lib.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=lib.root, prefix=".upload-")
        size = 0
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise PcapError(f"file is larger than the {limit // (1024 * 1024)} MB limit (server.pcap_max_mb)")
                    f.write(chunk)
            return await asyncio.to_thread(lib.add_file, name, Path(tmp))
        finally:
            Path(tmp).unlink(missing_ok=True)

    @api.get("/pcaps/{pcap_id}/download")
    async def download_pcap(pcap_id: str, request: Request):
        lib: PcapLibrary = request.app.state.pcaps
        meta = lib.get(pcap_id)
        name = meta["name"] if meta["name"].lower().endswith(".pcap") else meta["name"] + ".pcap"
        return FileResponse(lib.path(pcap_id), media_type="application/vnd.tcpdump.pcap", filename=name)

    @api.post("/pcaps/{pcap_id}/rename")
    async def rename_pcap(pcap_id: str, body: RenameRequest, request: Request):
        return request.app.state.pcaps.rename(pcap_id, body.name)

    @api.delete("/pcaps/{pcap_id}")
    async def delete_pcap(pcap_id: str, request: Request):
        request.app.state.pcaps.delete(pcap_id)
        return {"ok": True}

    @api.get("/hosts/{host_id}/pcaps/{pcap_id}/packets")
    async def pcap_packets(host_id: str, pcap_id: str, request: Request, start: int = 0, count: int = 100):
        path = str(request.app.state.pcaps.path(pcap_id))
        return await hosts(request).get(host_id).call_offline("pcap_packets", path=path, start=start, count=count)

    @api.post("/hosts/{host_id}/pcaps/{pcap_id}/to-streams")
    async def pcap_to_streams(host_id: str, pcap_id: str, body: ToStreamsRequest, request: Request):
        lib: PcapLibrary = request.app.state.pcaps
        name = lib.get(pcap_id)["name"].rsplit(".", 1)[0]
        return await hosts(request).get(host_id).call_offline(
            "pcap_to_streams", path=str(lib.path(pcap_id)), indices=body.indices, name=name)

    # --- captures ---

    @api.post("/hosts/{host_id}/captures")
    async def start_capture(host_id: str, body: CaptureRequest, request: Request):
        if not body.tx_ports and not body.rx_ports:
            raise BadRequest("choose at least one port to capture on")
        return await act(request, host_id, "captureStart", "capture_start", {"ports": sorted(set(body.tx_ports) | set(body.rx_ports))},
                         **body.model_dump())

    @api.get("/hosts/{host_id}/captures")
    async def capture_status(host_id: str, request: Request):
        return await hosts(request).get(host_id).call("capture_status")

    @api.post("/hosts/{host_id}/captures/{capture_id}/stop")
    async def stop_capture(host_id: str, capture_id: int, body: CaptureStopRequest, request: Request):
        packets = await act(request, host_id, "captureStop", "capture_stop", {"name": body.name if body.save else ""},
                            capture_id=capture_id, save=body.save)
        if not body.save:
            return None
        return await asyncio.to_thread(request.app.state.pcaps.add_capture, body.name, packets)

    # --- TRex Python profiles ---

    @api.get("/hosts/{host_id}/profiles")
    async def list_profiles(host_id: str, request: Request):
        session = hosts(request).get(host_id)
        return {"profiles": request.app.state.profiles.list(session.cfg),
                "upload_allowed": request.app.state.config.server.allow_profile_upload}

    @api.get("/hosts/{host_id}/profiles/info")
    async def profile_info(host_id: str, id: str, request: Request):
        session = hosts(request).get(host_id)
        path = request.app.state.profiles.resolve(session.cfg, id)
        return await session.call_offline("profile_info", path=str(path))

    @api.post("/hosts/{host_id}/traffic/start-profile")
    async def start_profile(host_id: str, body: ProfileStartRequest, request: Request):
        session = hosts(request).get(host_id)
        rfc_busy(session, body.ports)
        path = request.app.state.profiles.resolve(session.cfg, body.id)
        result = await act(request, host_id, "startProfile", "start_profile",
                           {"ports": body.ports, "name": body.id.partition(":")[2], "mult": body.mult},
                           path=str(path), ports=body.ports, values=body.values,
                           mult=body.mult, duration=body.duration, force=body.force)
        for p in body.ports:
            session.profile_runs[p] = {"id": body.id, "values": body.values, "streams": result["streams"].get(p)}
        return result

    @api.get("/hosts/{host_id}/profile-runs")
    async def profile_runs(host_id: str, request: Request):
        return hosts(request).get(host_id).profile_runs

    @api.post("/profiles")
    async def upload_profile(name: str, request: Request):
        if not request.app.state.config.server.allow_profile_upload:
            raise BadRequest("uploading profiles is disabled (server.allow_profile_upload); copy them to the profiles folder over SSH")
        data = await request.body()
        if len(data) > 1024 * 1024:
            raise BadRequest("profile file is larger than 1 MB")
        request.app.state.profiles.save_upload(name, data)
        return {"ok": True}

    @api.delete("/profiles/{name}")
    async def delete_profile(name: str, request: Request):
        if not request.app.state.config.server.allow_profile_upload:
            raise BadRequest("managing profiles from the web page is disabled (server.allow_profile_upload)")
        request.app.state.profiles.delete(name)
        return {"ok": True}

    # --- traffic ---

    @api.post("/hosts/{host_id}/traffic/push")
    async def push_pcap(host_id: str, body: PushRequest, request: Request):
        lib: PcapLibrary = request.app.state.pcaps
        session = hosts(request).get(host_id)
        meta = lib.get(body.pcap_id)
        if body.ipg_usec is not None and body.min_ipg_usec is not None:
            raise BadRequest("fixed gap and minimum gap can't be used together")
        if not 1 <= body.count <= MAX_PUSH_COUNT:
            raise BadRequest(f"count must be 1..{MAX_PUSH_COUNT}")
        rfc_busy(session, body.ports)
        remote = can_push_remote(session)
        if not remote and meta["size"] > LOCAL_PUSH_LIMIT:
            raise BadRequest("this TRex is on another machine, so the pcap is sent over the network, which TRex limits to 1 MB; "
                             "install the GUI backend on the TRex host to replay larger files")
        args = body.model_dump(exclude={"pcap_id"})
        for p in body.ports:
            session.profile_runs.pop(p, None)
        return await act(request, host_id, "pushPcap", "push_pcap", {"ports": body.ports, "name": meta["name"]},
                         path=str(lib.path(body.pcap_id)), remote=remote,
                         packets=meta["packets"], duration_s=meta["duration_s"], avg_frame=meta["avg_frame"], **args)

    @api.post("/hosts/{host_id}/traffic/start")
    async def start(host_id: str, body: StartRequest, request: Request):
        store: StreamStore = request.app.state.store
        rfc_busy(hosts(request).get(host_id), body.ports)
        port_streams = {p: store.get(host_id, p) for p in body.ports}
        for p in body.ports:
            hosts(request).get(host_id).profile_runs.pop(p, None)
        return await act(request, host_id, "start", "start", {"ports": body.ports, "mult": body.mult},
                         port_streams=port_streams, mult=body.mult, force=body.force, duration=body.duration)

    # Declared before /traffic/{action} so it wins the route match.
    @api.post("/hosts/{host_id}/traffic/update")
    async def update(host_id: str, body: UpdateRequest, request: Request):
        return await act(request, host_id, "update", "update", {"ports": body.ports, "mult": body.mult},
                         ports=body.ports, mult=body.mult)

    @api.post("/hosts/{host_id}/traffic/{action}")
    async def traffic(host_id: str, action: str, body: TrafficRequest, request: Request):
        if action not in ("stop", "pause", "resume", "reset"):
            raise HostNotFound(f"unknown traffic action '{action}'")
        if action == "reset":
            for p in body.ports:
                hosts(request).get(host_id).profile_runs.pop(p, None)
        return await act(request, host_id, action, action, {"ports": body.ports}, ports=body.ports)

    @api.websocket("/hosts/{host_id}/stats")
    async def stats_stream(websocket: WebSocket, host_id: str):
        try:
            session = websocket.app.state.hosts.get(host_id)
        except HostNotFound:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        q = session.subscribe()
        try:
            while True:
                await websocket.send_json(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            session.unsubscribe(q)

    return api


def create_app(config: Config) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.hosts = HostManager(config.hosts, config.server.stats_interval)
        app.state.store = StreamStore(config.server.data_dir)
        app.state.pcaps = PcapLibrary(config.server.data_dir)
        app.state.profiles = ProfileDirs(config.server.data_dir)
        app.state.rfc2544 = Rfc2544Store(config.server.data_dir)
        app.state.config = config
        yield
        await app.state.hosts.close()

    app = FastAPI(title="TRex GUI", lifespan=lifespan)

    def error(status: int):
        async def handler(_: Request, exc: Exception):
            return JSONResponse(status_code=status, content={"detail": str(exc)})
        return handler

    app.add_exception_handler(HostNotFound, error(404))
    app.add_exception_handler(HostNotConnected, error(409))

    async def call_error(_: Request, exc: TRexCallError):
        # Invalid packet/stream input is the user's to fix; anything else came from TRex.
        status = 422 if exc.kind == "PacketError" else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    app.add_exception_handler(TRexCallError, call_error)
    app.add_exception_handler(StoreError, error(400))
    app.add_exception_handler(BadRequest, error(400))
    app.add_exception_handler(PcapError, error(400))
    app.add_exception_handler(ProfileError, error(400))
    app.add_exception_handler(WorkerError, error(504))

    app.include_router(_api_router())

    if config.server.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=config.server.static_dir, html=True), name="frontend")

    return app
