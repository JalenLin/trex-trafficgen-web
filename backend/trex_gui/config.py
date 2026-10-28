from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class ConfigError(Exception):
    pass


MIN_STATS_INTERVAL = 0.5


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    stats_interval: float = 1.0
    static_dir: Path = DEFAULT_STATIC_DIR
    # CPUs the backend and its workers may run on. Set this when the backend
    # shares a machine with TRex, so it stays off the data-plane cores.
    cpu_affinity: list[int] | None = None
    # Where stream definitions are saved. Relative paths are resolved against
    # the config file's directory; default: <config dir>/data.
    data_dir: Path | None = None
    # Largest pcap accepted for upload, in MB.
    pcap_max_mb: int = 1024
    # Allow uploading TRex Python profiles from the web page. A profile is Python
    # code that runs on this machine when loaded, and there is no login yet:
    # anyone who can reach the GUI could run code here. Off by default; put
    # profiles in <data_dir>/profiles over SSH instead.
    allow_profile_upload: bool = False


@dataclass
class HostConfig:
    id: str
    name: str
    server: str = ""
    sync_port: int = 4501
    async_port: int = 4500
    username: str = "trex-gui"
    # TRex ships a matching client with every release, e.g.
    # /opt/trex/v3.06/automation/trex_control_plane/interactive
    client_path: str = ""
    # Only needed when external_libs is not at its usual place next to client_path.
    ext_libs_path: str = ""
    mock: bool = False
    mock_ports: int = 4

    def to_worker_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    hosts: list[HostConfig] = field(default_factory=list)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")

    server_raw = dict(raw.get("server") or {})
    if "static_dir" in server_raw:
        server_raw["static_dir"] = (path.parent / server_raw["static_dir"]).resolve()
    server_raw["data_dir"] = (path.parent / server_raw.get("data_dir", "data")).resolve()
    server = ServerConfig(**server_raw)
    # Every poll is RPC work on the TRex master thread. Back-to-back get_stats
    # (~36/s) measurably cut 64B line rate (bench/README.md), so keep a floor.
    if not server.stats_interval >= MIN_STATS_INTERVAL:
        raise ConfigError(f"server.stats_interval must be at least {MIN_STATS_INTERVAL} seconds")
    if server.cpu_affinity is not None:
        if not server.cpu_affinity or not all(isinstance(c, int) and c >= 0 for c in server.cpu_affinity):
            raise ConfigError("server.cpu_affinity must be a non-empty list of CPU numbers, e.g. [0]")

    hosts: list[HostConfig] = []
    seen: set[str] = set()
    for i, h in enumerate(raw.get("hosts") or []):
        if "id" not in h:
            raise ConfigError(f"hosts[{i}]: missing 'id'")
        h.setdefault("name", h["id"])
        try:
            host = HostConfig(**h)
        except TypeError as e:
            raise ConfigError(f"hosts[{i}] ({h['id']}): {e}")
        if host.id in seen:
            raise ConfigError(f"duplicate host id: {host.id}")
        if not host.mock and not (host.server and host.client_path):
            raise ConfigError(f"host {host.id}: 'server' and 'client_path' are required unless mock is true")
        seen.add(host.id)
        hosts.append(host)

    return Config(server=server, hosts=hosts)
