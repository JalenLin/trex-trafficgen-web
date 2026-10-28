"""Per-host worker process.

Every TRex host gets its own process, so hosts running different TRex versions
can each load the client that ships with their release. This module must stay
free of third-party imports: the TRex client bundles its own yaml/scapy/zmq and
they have to be the first copies imported in the process.

Protocol over the pipe: request {"id", "op", "args"} -> reply {"id", "ok", "result" | "error"}.
Each op maps to an ``op_<name>`` method on the adapter and must return plain
picklable data.
"""
import contextlib
import numbers
import os
import sys

USER_ERRORS = {"PacketError", "RuntimeError", "TRexError", "STLError", "ConnectionLost"}


class ConnectionLost(RuntimeError):
    """The TRex server went away (restart, crash); the GUI must reconnect."""


NO_TCP_UDP_MASK = 1  # TRex filtered service mode: hand only non-TCP/UDP packets to the CPU


class TRexAdapter:
    def __init__(self, cfg: dict):
        if cfg.get("ext_libs_path"):
            os.environ["TREX_EXT_LIBS"] = cfg["ext_libs_path"]
        sys.path.insert(0, cfg["client_path"])
        import trex.stl.api as api

        self._api = api
        self._catalog = None
        self._capture_service: dict[int, dict] = {}  # capture id -> service modes to put back ({state: ports})
        self._last_event = None  # last TRex event already forwarded by op_stats
        # port -> {GUI stream id: TRex stream id} for what op_start put there, and the
        # GUI ids paused one by one (per-stream control)
        self._stream_ids: dict[int, dict[str, int]] = {}
        self._paused: dict[int, set[str]] = {}
        self._client = api.STLClient(
            username=cfg["username"],
            server=cfg["server"],
            sync_port=cfg["sync_port"],
            async_port=cfg["async_port"],
            verbose_level="error",
        )

    def op_connect(self):
        self._client.connect()
        info = self._client.get_server_system_info()
        # TRex reports its start time as "uptime" (e.g. "Oct 27 2026 @ 09:43:21");
        # a new value means the server restarted and port settings reset.
        return {"server_version": self._client.get_server_version(), "server_started": str(info.get("uptime", ""))}

    def op_disconnect(self):
        if self._client.is_connected():
            self._client.disconnect()
        return None

    def op_ports(self):
        c = self._client
        port_ids = c.get_all_ports()
        acquired = set(c.get_acquired_ports())
        ports = []
        for pid, info in zip(port_ids, c.get_port_info(port_ids)):
            ports.append({
                "id": pid,
                "driver": info.get("driver", ""),
                "description": info.get("description", ""),
                "speed_gbps": info.get("speed", 0),
                "link": info.get("link", "N/A"),
                "status": info.get("status", ""),
                "vlan": str(info.get("vlan", "-")),
                "hw_mac": info.get("hw_mac", ""),
                "owner": getattr(c.get_port(pid), "owner", "") or "",
                "acquired": pid in acquired,
                "layer": self._layer(pid),
            })
        return ports

    def _layer(self, pid):
        # All from the client's cached port attributes; no RPC.
        port = self._client.get_port(pid)
        cfg = port.get_layer_cfg()
        ipv4, ipv6 = cfg.get("ipv4", {}), cfg.get("ipv6", {})
        attr = port.get_ts_attr() or {}
        return {
            "mode": "L2" if ipv4.get("state", "none") == "none" else "L3",
            "src_mac": cfg.get("ether", {}).get("src", ""),
            "dst_mac": cfg.get("ether", {}).get("dst", ""),
            "ipv4_src": ipv4.get("src"),
            "ipv4_dst": ipv4.get("dst"),
            "arp": ipv4.get("state", "none"),
            "ipv6": bool(ipv6.get("enabled")),
            "ipv6_src": ipv6.get("src"),
            "vlan": list(port.get_vlan_cfg() or []),
            "promiscuous": bool(attr.get("promiscuous", {}).get("enabled")),
            "multicast": bool(attr.get("multicast", {}).get("enabled")),
            "link_up": bool(attr.get("link", {}).get("up")),
            "link_supported": bool(port.info.get("is_link_supported")),
            "service": self._service_state(pid),
            # 0 none, 1 tx, 2 rx, 3 full; None when the NIC can't do flow control
            "flow_ctrl": attr.get("fc", {}).get("mode") if port.info.get("is_fc_supported") else None,
        }

    def op_stats(self):
        c = self._client
        if not c.is_connected():
            raise ConnectionLost("lost connection to the TRex server (restarted or stopped?); reconnect")
        port_ids = c.get_all_ports()
        stats = c.get_stats(ports=port_ids)
        acquired = set(c.get_acquired_ports())
        return {
            "global": stats["global"],
            "ports": {pid: stats[pid] for pid in port_ids},
            # Kept current by TRex async events in the client; no extra RPC.
            "port_states": {
                pid: {"status": c.get_port(pid).get_port_state_name(), "owner": c.get_port(pid).owner or "",
                      "acquired": pid in acquired}
                for pid in port_ids
            },
            # get_stats() already fetched these (one RPC); just reshape for JSON.
            **pg_summary(stats.get("flow_stats", {}), stats.get("latency", {})),
            "events": self._new_events(),
        }

    def _new_events(self):
        """TRex async events the client recorded since the last call (port started/
        stopped/acquired by someone, server stopped...). Read from the client's own
        buffer, no RPC. Messages are TRex's English text."""
        events = list(self._client.ctx.event_handler.events)
        start = 0
        if self._last_event is not None:
            start = next((i + 1 for i in range(len(events) - 1, -1, -1) if events[i] is self._last_event), 0)
        if events:
            self._last_event = events[-1]
        return [{"ts": e.ts, "origin": e.origin, "level": e.ev_type, "message": str(e.msg)} for e in events[start:]]

    def op_monitor_extra(self, cpu=False, xstats=False):
        """Opt-in monitoring: each part is extra RPC work on the TRex master thread
        (get_utilization ~1 ms, xstats ~5 ms per port), so the GUI only asks for
        what a user switched on (bench/README.md)."""
        c = self._client
        out = {}
        if cpu:
            u = c.get_util_stats()
            out["cpu"] = [{"ports": core.get("ports", []), "history": core.get("history", [])} for core in u.get("cpu", [])]
            # TRex reports each mbuf pool as [free, total]
            out["mbuf"] = {sock: {size: {"used": v[1] - v[0], "total": v[1]} for size, v in pools.items()}
                           for sock, pools in u.get("mbuf_stats", {}).items()}
        if xstats:
            out["xstats"] = {pid: c.get_xstats(pid) for pid in c.get_all_ports()}
        return out

    def op_acquire(self, ports, force=False):
        self._client.acquire(ports=ports, force=force)
        return self.op_ports()

    def op_release(self, ports):
        c = self._client
        # The GUI keeps its own stream definitions; don't leave its copies on
        # TRex for whoever acquires the port next. Ports still sending are left alone.
        idle = [p for p in ports if p in c.get_acquired_ports() and p not in c.get_active_ports()]
        if idle:
            c.remove_all_streams(ports=idle)
        c.release(ports=ports)
        self._forget_streams(ports)
        return self.op_ports()

    def op_clear_stats(self, ports=None):
        self._client.clear_stats(ports=ports)
        return None

    # --- port L2/L3 configuration (port must be acquired and idle) ---

    # Service mode is "off", "filtered" (only non-TCP/UDP to the CPU: ARP, ping,
    # namespace nodes; streams keep full speed) or "on" (everything to the CPU).
    # Operations that need it switch to "on" and put back whatever was there.

    def _service_state(self, port) -> str:
        # cached attributes: is_service_mode_on() re-syncs (an RPC) for ports we don't own
        p = self._client.get_port(port)
        return "on" if p.service_mode else "filtered" if getattr(p, "service_mode_filtered", False) else "off"

    def _set_service(self, ports, state):
        if not ports:
            return
        c = self._client
        if state == "on":
            c.set_service_mode(ports=ports, enabled=True)
        elif state == "filtered":
            c.set_service_mode(ports=ports, enabled=False, filtered=True, mask=NO_TCP_UDP_MASK)
        else:
            c.set_service_mode(ports=ports, enabled=False)

    def _enter_service(self, ports) -> dict:
        """Switch ports to full service mode; returns {previous state: ports} to restore."""
        before: dict[str, list] = {}
        for p in ports:
            state = self._service_state(p)
            if state != "on":
                before.setdefault(state, []).append(p)
        self._set_service([p for ps in before.values() for p in ps], "on")
        return before

    def _restore_service(self, before: dict):
        for state, ports in before.items():
            self._set_service(ports, state)

    @contextlib.contextmanager
    def _service(self, ports):
        """TRex only accepts L2/L3/VLAN changes in service mode; enter it just for the change."""
        before = self._enter_service(ports)
        try:
            yield
        finally:
            self._restore_service(before)

    def op_service_mode(self, port, mode):
        if mode not in ("off", "filtered", "on"):
            raise RuntimeError("service mode must be off, filtered or on")
        self._set_service([port], mode)
        return self.op_ports()

    def op_port_config(self, port, vlan=None, l2=None, l3=None, ipv6=None, promiscuous=None, multicast=None,
                       link_up=None, flow_ctrl=None):
        """Apply the given sections; None leaves a setting unchanged. vlan=[] clears VLAN tags."""
        c = self._client
        warnings = []
        with self._service([port]):
            # VLAN first: L3 resolution sends ARP with the port's VLAN tags.
            if vlan is not None:
                if vlan:
                    c.set_vlan(ports=[port], vlan=vlan)
                else:
                    c.clear_vlan(ports=[port])
            if l2 is not None:
                c.set_l2_mode(port, dst_mac=l2["dst_mac"])
            if l3 is not None:
                try:
                    c.set_l3_mode(port, src_ipv4=l3["src"], dst_ipv4=l3["dst"])
                except Exception as e:
                    # The address is set even when ARP fails; report, don't fail.
                    if "resolve" not in str(e).lower():
                        raise
                    warnings.append(port_warning("arpUnresolved", port=port, gateway=l3["dst"]))
            if ipv6 is not None:
                c.conf_ipv6(port, enabled=bool(ipv6.get("enabled")), src_ipv6=ipv6.get("src") or None)
        if any(v is not None for v in (promiscuous, multicast, link_up, flow_ctrl)):
            c.set_port_attr(ports=[port], promiscuous=promiscuous, multicast=multicast, link_up=link_up, flow_ctrl=flow_ctrl)
        ports = self.op_ports()
        # Some NICs (e.g. X557 on ixgbe) accept the setting but keep reporting the old mode.
        got = next(p for p in ports if p["id"] == port)["layer"]["flow_ctrl"]
        if flow_ctrl is not None and got is not None and got != flow_ctrl:
            warnings.append(port_warning("flowCtrlNotApplied", port=port))
        return {"ports": ports, "warnings": warnings}

    def op_resolve(self, ports):
        warnings, error = [], None
        with self._service(ports):
            try:
                self._client.resolve(ports=ports, retries=2)
            except Exception as e:
                error = str(e)
        result = self.op_ports()
        unresolved = [p for p in result if p["id"] in ports and p["layer"]["arp"] == "unresolved"]
        warnings += [port_warning("arpUnresolved", port=p["id"], gateway=p["layer"]["ipv4_dst"]) for p in unresolved]
        if error and not unresolved:
            warnings.append({"code": None, "params": {}, "message": error})  # TRex's own text
        return {"ports": result, "warnings": warnings}

    def op_ping(self, port, dst_ip, count=3, pkt_size=64):
        with self._service([port]):
            records = self._client.ping_ip(src_port=port, dst_ip=dst_ip, pkt_size=pkt_size, count=count, interval_sec=0.5)
        names = {0: "timeout", 1: "unreachable", 2: "ok"}
        return [{"state": names.get(r.state, str(r.state)), "responder": str(r.responder_ip),
                 "rtt_ms": r.rtt if isinstance(r.rtt, numbers.Number) else None,
                 "ttl": r.ttl if isinstance(r.ttl, numbers.Number) else None} for r in records]

    # --- packets and streams (no TRex connection needed) ---

    def catalog(self):
        if self._catalog is None:
            from .packets import Catalog
            self._catalog = Catalog()
        return self._catalog

    def op_protocols(self):
        return self.catalog().list()

    def op_protocol_schema(self, proto):
        return self.catalog().schema(proto)

    def op_build_packet(self, packet, flow_stats=None):
        cat = self.catalog()
        desc = cat.describe(cat.build(packet), user_layers=len(packet.get("layers") or []))
        warnings = cat.lint_packet(packet, desc) + cat.lint_stream({"flow_stats": flow_stats, "packet": packet}, desc)
        return {**desc, "warnings": warnings}

    def op_check_stream(self, stream):
        from .packets import compile_stream, to_trex_stream
        compiled = compile_stream(self.catalog(), stream)
        to_trex_stream(self._api, compiled, stream)  # let the TRex client validate too
        return {"describe": compiled["describe"], "vm": compiled["vm"], "warnings": compiled["warnings"]}

    # --- traffic ---

    def op_start(self, port_streams, mult="1", force=False, duration=-1):
        from .packets import compile_stream, to_trex_stream
        c = self._client
        ports = sorted(port_streams)
        built = {}
        for port in ports:
            built[port] = []
            for s in port_streams[port]:
                try:
                    built[port].append(to_trex_stream(self._api, compile_stream(self.catalog(), s), s))
                except Exception as e:
                    raise RuntimeError(f"port {port}, stream '{s.get('name') or s['id']}': {e}")
            if not any(s.get("enabled", True) for s in port_streams[port]):
                raise RuntimeError(f"port {port} has no enabled streams")
        # Streams can only be replaced on idle ports.
        active = [p for p in ports if p in c.get_active_ports()]
        if active:
            if not force:
                raise RuntimeError(f"port(s) {', '.join(map(str, active))} already transmitting; stop them first")
            c.stop(ports=active)
        for port in ports:
            c.remove_all_streams(ports=[port])
            ids = c.add_streams(built[port], ports=[port])
            # TRex returns a bare id when it was given a single stream
            ids = [ids] if isinstance(ids, int) else list(ids)
            self._stream_ids[port] = dict(zip((s["id"] for s in port_streams[port]), ids))
            self._paused[port] = set()
        c.start(ports=ports, mult=mult, force=force, duration=duration)
        return self.op_ports()

    # --- one stream at a time (TRex marks these "temporary"; see the UI's note) ---

    def op_stream_control(self, port, stream_ids, action, mult=None):
        c = self._client
        known = self._stream_ids.get(port, {})
        missing = [s for s in stream_ids if s not in known]
        if missing:
            raise RuntimeError("these streams are not running on TRex; press Start first")
        trex_ids = [known[s] for s in stream_ids]
        if action == "pause":
            c.pause_streams(port, trex_ids)
            self._paused.setdefault(port, set()).update(stream_ids)
        elif action == "resume":
            c.resume_streams(port, trex_ids)
            self._paused.setdefault(port, set()).difference_update(stream_ids)
        elif action == "update":
            c.update_streams(port, mult=mult, force=True, stream_ids=trex_ids)
        else:
            raise RuntimeError(f"unknown stream action {action!r}")
        return self.op_stream_states(port)

    def op_stream_states(self, port):
        """Which of the GUI's streams are on TRex for this port, and which are paused."""
        running = self._client.get_port(port).get_port_state_name() != "IDLE"
        return {"running": running, "on_trex": sorted(self._stream_ids.get(port, {})),
                "paused": sorted(self._paused.get(port, set())) if running else []}

    # --- send a packet once (not a stream) ---

    def op_push_packet(self, port, packet, count=1, ipg_usec=0.0):
        """Send `count` copies of one packet now, through TRex's push_packets (RX core,
        so for test packets, not rates). Unset outer Ether src/dst use the port's MACs."""
        if not 1 <= int(count) <= 1000:
            raise RuntimeError("count must be 1..1000")
        pkt = self.catalog().build(packet)
        self._client.push_packets([pkt] * int(count), ports=[port], ipg_usec=float(ipg_usec))
        return {"sent": int(count), "bytes": len(bytes(pkt))}

    # --- namespaces (TRex 'stack: linux_based'): emulated hosts behind a port ---

    def _ns(self, port, build):
        from trex.common.trex_ns import NSCmds

        c = self._client
        # TRex only takes namespace commands in service mode; the nodes answer (ARP, ping)
        # only while the port stays in it, which the user chooses (see op_service_mode).
        cmds = NSCmds()
        build(cmds)
        before = self._enter_service([port])
        try:
            c.set_namespace_start(port, cmds)
            res = c.wait_for_async_results(port) or []  # one result per command
        finally:
            self._restore_service(before)
        errors = [r["error"] for r in res if isinstance(r, dict) and "error" in r]
        if errors:
            raise RuntimeError("; ".join(map(str, errors)))
        return res

    def op_ns_nodes(self, port):
        # each command's reply is {"result": {"nodes": [...]}}: MACs for get_nodes,
        # node dicts (ether.src, ipv4.src/dst = gateway, vlan.tags, ipv6...) for get_nodes_info
        nodes = lambda res: ((res[-1] if res else {}).get("result") or {}).get("nodes") or []
        macs = nodes(self._ns(port, lambda cmds: cmds.get_nodes()))
        if not macs:
            return []
        return nodes(self._ns(port, lambda cmds: cmds.get_nodes_info(macs)))

    def op_ns_add(self, port, mac, ipv4=None, dg=None, ipv6=False, vlans=None, mtu=None):
        if ipv4 and not dg:
            raise RuntimeError("an IPv4 node needs a default gateway")

        def build(cmds):
            cmds.add_node(mac)
            if vlans:
                cmds.set_vlan(mac, [int(v) for v in vlans])
            if ipv4:
                cmds.set_ipv4(mac, ipv4, dg=dg)  # (subnet is for shared namespaces only)
            if ipv6:
                cmds.set_ipv6(mac, True)
            if mtu:
                cmds.set_mtu(mac, int(mtu))

        self._ns(port, build)
        return self.op_ns_nodes(port)

    def op_ns_remove(self, port, macs):
        self._ns(port, lambda cmds: [cmds.remove_node(m) for m in macs])
        return self.op_ns_nodes(port)

    def op_stop(self, ports):
        self._client.stop(ports=ports)
        for p in ports:
            self._paused.pop(p, None)
        return self.op_ports()

    def op_pause(self, ports):
        self._client.pause(ports=ports)
        return self.op_ports()

    def op_resume(self, ports):
        self._client.resume(ports=ports)
        return self.op_ports()

    def op_update(self, ports, mult):
        self._client.update(ports=ports, mult=mult)
        return self.op_ports()

    # --- TRex Python profiles (path vetted by profiles.ProfileDirs) ---

    def op_profile_info(self, path):
        from .profileops import info
        return info(path)

    def op_start_profile(self, path, ports, values, mult="1", duration=-1, force=False):
        from .profileops import load_streams
        c = self._client
        built = {}
        for port in ports:
            try:
                built[port] = load_streams(path, port, values or {})
            except SystemExit:
                raise RuntimeError("the profile exited while reading its parameters (check the values)")
            if not built[port]:
                raise RuntimeError(f"the profile produced no streams for port {port}")
        active = [p for p in ports if p in c.get_active_ports()]
        if active:
            if not force:
                raise RuntimeError(f"port(s) {', '.join(map(str, active))} already transmitting; stop them first")
            c.stop(ports=active)
        for port in ports:
            c.remove_all_streams(ports=[port])
            c.add_streams(built[port], ports=[port])
            self._forget_streams([port])
        c.start(ports=ports, mult=mult, force=force, duration=duration)
        return {"ports": self.op_ports(), "streams": {p: len(s) for p, s in built.items()}}

    def op_reset(self, ports):
        """Back to a clean idle port, still owned: stop, drop TRex-side streams, clear
        this port's counters, leave service mode. The GUI's stream definitions stay."""
        c = self._client
        active = [p for p in ports if p in c.get_active_ports()]
        if active:
            c.stop(ports=active)
        c.remove_all_streams(ports=ports)
        self._forget_streams(ports)
        # pg / latency / global counters are shared with other ports: leave them.
        c.clear_stats(ports=ports, clear_global=False, clear_flow_stats=False, clear_latency_stats=False)
        service = [p for p in ports if c.get_port(p).is_service_mode_on()]
        if service:
            c.set_service_mode(ports=service, enabled=False)
        return self.op_ports()

    # --- pcap ---

    def op_pcap_packets(self, path, start=0, count=100):
        from .pcapops import list_packets
        return list_packets(self.catalog(), path, start, count)

    def op_pcap_to_streams(self, path, indices, name):
        from .pcapops import to_streams
        return to_streams(self.catalog(), path, indices, name)

    def op_push_pcap(self, ports, path, remote, ipg_usec=None, speedup=1.0, count=1, duration=-1,
                     min_ipg_usec=None, src_mac_pcap=False, dst_mac_pcap=False, force=False, **_mock_only):
        c = self._client
        active = [p for p in ports if p in c.get_active_ports()]
        if active:
            if not force:
                raise RuntimeError(f"port(s) {', '.join(map(str, active))} already transmitting; stop them first")
            c.stop(ports=active)
        kw = dict(ports=ports, ipg_usec=ipg_usec, speedup=speedup, count=count, duration=duration,
                  min_ipg_usec=min_ipg_usec, src_mac_pcap=src_mac_pcap, dst_mac_pcap=dst_mac_pcap, force=force)
        self._forget_streams(ports)  # a replay replaces the port's streams on TRex
        if remote:
            c.push_remote(path, **kw)  # TRex reads the file itself: any size
        else:
            c.push_pcap(path, **kw)  # sent over RPC: TRex caps this at 1MB
        return self.op_ports()

    def op_capture_start(self, tx_ports, rx_ports, limit=1000, mode="fixed", bpf_filter="", service=False):
        c = self._client
        # Outside service mode a capture only sees what goes through the RX core: RX gets
        # just ARP/latency-type packets, TX only service packets, not the streams the DP
        # cores send. So the TX ports go into service mode too (as TRex's own tests do).
        ports = list(dict.fromkeys([*tx_ports, *rx_ports]))
        before = self._enter_service(ports) if service else {}
        try:
            r = c.start_capture(tx_ports=tx_ports, rx_ports=rx_ports, limit=limit, mode=mode, bpf_filter=bpf_filter or "")
        except Exception:
            self._restore_service(before)
            raise
        self._capture_service[r["id"]] = before
        return {"id": r["id"]}

    def op_capture_status(self):
        keep = ("id", "state", "count", "limit", "bytes", "mode")
        return [{k: v.get(k) for k in keep} for v in self._client.get_capture_status().values()]

    def op_capture_stop(self, capture_id, save=True):
        c = self._client
        packets = [] if save else None
        try:
            c.stop_capture(capture_id, output=packets)
        finally:
            self._restore_service(self._capture_service.pop(capture_id, {}))
        return [(p["ts"], p["binary"]) for p in packets or []]

    def _forget_streams(self, ports):
        """The GUI's streams are no longer what's on TRex for these ports."""
        for p in ports:
            self._stream_ids.pop(p, None)
            self._paused.pop(p, None)

    def heal_port_states(self):
        """Work around a TRex client inconsistency, checked before every op.

        After a pcap replay on an acquired port, the client sometimes marks the port
        idle but leaves its profile "active". stop() then skips the port as idle, while
        remove_all_streams, port config and reset refuse it ("port(s) [0._]: are active"),
        so the port is stuck until released. Port.sync() can't fix it: the client drops
        the server's IDLE profile state (STATE_IDLE is 0 and its setter ignores falsy
        states). A forced stop of that profile sets it back. The check is client-side;
        the RPC only happens when the state is stale."""
        c = self._client
        if not c.is_connected():
            return
        for pid in c.get_acquired_ports():
            port = c.ports[pid]
            if port.is_active():
                continue
            active = (port.STATE_TX, port.STATE_PAUSE, port.STATE_PCAP_TX)
            for profile_id, state in list(getattr(port, "profile_state_list", {}).items()):
                if state in active:
                    port.stop(force=True, profile_id=profile_id)

    def close(self):
        try:
            self.op_disconnect()
        except Exception:
            pass


def _num(v):
    # TRex fills missing values with StatNotAvailable objects.
    return v if isinstance(v, numbers.Number) else None


def port_warning(code: str, **params) -> dict:
    """A port-setting warning the UI translates (locales/ports.ts warn.<code>); message is the English fallback."""
    text = {
        "arpUnresolved": "Port {port}: gateway {gateway} did not answer ARP; traffic can't start until it resolves",
        "flowCtrlNotApplied": "Port {port}: the NIC did not apply the flow control setting",
    }[code]
    return {"code": code, "params": params, "message": text.format(**params)}


def pg_summary(flow_stats: dict, latency: dict) -> dict:
    """Reshape TRex pg-id stats into JSON: totals, per-port packet counts and latency."""
    pgids = {}
    for pg, fs in flow_stats.items():
        if not isinstance(pg, int):
            continue
        total = lambda key: _num((fs.get(key) or {}).get("total"))
        per_port = lambda key: {p: _num(v) for p, v in (fs.get(key) or {}).items() if isinstance(p, int)}
        pgids[pg] = {
            "tx_pkts": total("tx_pkts"), "rx_pkts": total("rx_pkts"),
            "tx_bytes": total("tx_bytes"), "rx_bytes": total("rx_bytes"),
            "tx_pps": total("tx_pps"), "rx_pps": total("rx_pps"),
            "tx_bps": total("tx_bps"), "rx_bps": total("rx_bps"),
            "tx_ports": per_port("tx_pkts"), "rx_ports": per_port("rx_pkts"),
            "latency": None,
        }
    for pg, lat in latency.items():
        if not isinstance(pg, int):
            continue
        entry = pgids.setdefault(pg, {"tx_pkts": None, "rx_pkts": None, "tx_ports": {}, "rx_ports": {}})
        inner, errs = lat.get("latency", {}), lat.get("err_cntrs", {})
        entry["latency"] = {
            **{k: _num(inner.get(k)) for k in ("average", "total_min", "total_max", "last_max", "jitter")},
            "histogram": {int(k): v for k, v in (inner.get("histogram") or {}).items()},
            **{k: _num(errs.get(k)) for k in ("dropped", "out_of_order", "dup", "seq_too_high", "seq_too_low")},
        }
    g_fs, g_lat = flow_stats.get("global", {}) or {}, latency.get("global", {}) or {}
    return {
        "pgids": pgids,
        "pg_global": {k: _num(d.get(k)) for d, keys in ((g_fs, ("rx_err", "tx_err")), (g_lat, ("old_flow", "bad_hdr"))) for k in keys},
    }


class BrokenAdapter:
    """Stands in when the TRex client could not be loaded, so every call reports why."""

    def __init__(self, error: str):
        self._error = error

    def __getattr__(self, name):
        if name.startswith("op_"):
            def fail(**_):
                raise RuntimeError(self._error)
            return fail
        raise AttributeError(name)

    def close(self):
        pass


def _make_adapter(cfg: dict):
    try:
        if cfg.get("mock"):
            from .mock import MockAdapter
            return MockAdapter(cfg)
        return TRexAdapter(cfg)
    except Exception as e:
        return BrokenAdapter(f"failed to load TRex client from {cfg.get('client_path')!r}: {type(e).__name__}: {e}")


def run(conn, cfg: dict):
    adapter = _make_adapter(cfg)
    try:
        while True:
            try:
                msg = conn.recv()
            except EOFError:
                break
            if msg is None:
                break
            try:
                fn = getattr(adapter, "op_" + msg["op"])
                if hasattr(adapter, "heal_port_states"):
                    adapter.heal_port_states()
                result = fn(**(msg.get("args") or {}))
                conn.send({"id": msg["id"], "ok": True, "result": result})
            except Exception as e:
                kind = type(e).__name__
                # Errors meant for the user read better without the class name.
                text = str(e) if kind in USER_ERRORS else f"{kind}: {e}"
                conn.send({"id": msg["id"], "ok": False, "error": text, "kind": kind})
    finally:
        adapter.close()
