// Typed client for the backend REST/WebSocket API (backend/trex_gui/app.py).
import { t, type Coded } from './i18n'

export interface HostSummary {
  id: string
  name: string
  server: string
  mock: boolean
  connected: boolean
  server_version: Record<string, string> | null
  server_started: string | null
  last_error: string | null
}

export interface PortLayer {
  mode: 'L2' | 'L3'
  src_mac: string
  dst_mac: string
  ipv4_src: string | null
  ipv4_dst: string | null
  /** 'none' in L2 mode; in L3 whether the gateway answered ARP. */
  arp: 'none' | 'unresolved' | 'resolved' | string
  ipv6: boolean
  ipv6_src: string | null
  vlan: number[]
  promiscuous: boolean
  multicast: boolean
  link_up: boolean
  link_supported: boolean
  /** 0 none, 1 tx, 2 rx, 3 full; null when the NIC has no flow control. */
  flow_ctrl: number | null
  /** off; filtered = only non-TCP/UDP (ARP, ping, namespace nodes) to the CPU; on = everything */
  service?: ServiceMode
}

export type ServiceMode = 'off' | 'filtered' | 'on'

/** A port's L2/L3 settings as saved in a profile (link state is never saved). */
export interface PortSettings {
  mode: 'L2' | 'L3'
  dst_mac?: string
  ipv4_src?: string
  ipv4_dst?: string
  vlan: number[]
  ipv6: boolean
  ipv6_src?: string | null
  promiscuous: boolean
  multicast: boolean
  flow_ctrl?: number | null
}

export interface PortProfile {
  id?: string
  name: string
  saved_at: string
  ports: Record<string, PortSettings>
}

export interface PortProfilesDoc {
  profiles: PortProfile[]
  /** What was last applied from a profile, to notice when TRex settings drift from it. */
  last_applied: {
    profile_id?: string
    name: string
    at: string
    /** TRex start time when applied; a different one means TRex restarted since. */
    server_started: string | null
    ports: Record<string, PortSettings>
  } | null
}

export interface PortInfo {
  id: number
  driver: string
  description: string
  speed_gbps: number
  link: string
  status: string
  vlan: string
  hw_mac: string
  owner: string
  acquired: boolean
  layer?: PortLayer
}

export interface PortStats {
  opackets: number
  ipackets: number
  obytes: number
  ibytes: number
  oerrors: number
  ierrors: number
  tx_bps: number
  tx_pps: number
  tx_bps_L1: number
  tx_util: number
  rx_bps: number
  rx_pps: number
  rx_bps_L1: number
  rx_util: number
}

// --- protocols & packets (schema comes from the Scapy bundled with each TRex version) ---

export interface ProtocolInfo {
  id: string
  name: string
  desc: string
  module: string
}

export interface ProtocolList {
  scapy_version: string
  common: string[]
  protocols: ProtocolInfo[]
  failed_contrib: string[]
}

export type FieldKind = 'int' | 'enum' | 'flags' | 'ip' | 'ip6' | 'mac' | 'bytes' | 'packet' | 'list' | 'other'

export interface FieldSchema {
  name: string
  kind: FieldKind
  type: string
  conditional: boolean
  default: string | null
  bits?: number
  enum?: { value: number; label: string }[]
  flags?: string[]
}

export interface ProtocolSchema {
  id: string
  name: string
  desc: string
  module: string
  fields: FieldSchema[]
  next: string[]
}

/** A field value as typed; {hex} for raw bytes, {py} for a Python literal. */
export type FieldValue = string | number | boolean | { hex: string } | { py: string }

export interface LayerSpec {
  proto: string
  fields: Record<string, FieldValue>
}

export interface PacketSpec {
  layers: LayerSpec[]
  /** Bytes on the wire including FCS; the packet is zero-padded up to it. */
  frame_size?: number | null
  /** Varying frame size (incl. FCS); overrides frame_size unless mode is 'fixed'. */
  size?: { mode: 'fixed' | 'inc' | 'dec' | 'random'; min?: number; max?: number; step?: number }
  /** Fill for the padding up to the frame size (default zeros). Same bytes in every packet. */
  payload?: PayloadSpec
}

export type PayloadType = 'zeros' | 'byte' | 'inc' | 'dec' | 'random' | 'text' | 'hex'
export interface PayloadSpec {
  type: PayloadType
  /** byte/inc/dec: start byte (0xAA or 170); random: seed; text: string; hex: bytes (DEADBEEF) */
  value?: string
}

/** Which of the GUI's streams are on TRex for a port, and which were paused one by one. */
export interface StreamStates {
  running: boolean
  on_trex: string[]
  paused: string[]
}

/** A host emulated behind a port (TRex namespaces, needs `stack: linux_based`). */
export interface NsNode {
  ether?: { src?: string }
  vlan?: { tags?: number[] }
  /** dst = the node's default gateway */
  ipv4?: { src?: string; dst?: string }
  ipv6?: { enabled?: boolean; src?: string }
  mtu?: number
  [k: string]: unknown
}
export interface NsNodeSpec {
  mac: string
  ipv4?: string | null
  /** required with ipv4 (TRex namespaces only take a gateway, no subnet) */
  dg?: string | null
  ipv6?: boolean
  vlans?: number[]
  mtu?: number | null
}

// --- RFC 2544 (backend/trex_gui/rfc2544.py) ---
export type Rfc2544Test = 'throughput' | 'latency' | 'frame_loss' | 'back_to_back'
export interface Rfc2544Config {
  pairs: { tx: number; rx: number }[]
  bidirectional: boolean
  frame_sizes: number[]
  tests: Rfc2544Test[]
  trial_s: number
  resolution_pct: number
  max_rate_pct: number
  loss_tolerance_pct: number
  frame_loss_step_pct: number
  b2b_max_s: number
}
export interface Rfc2544Dir {
  tx: number
  rx: number
  sent?: number
  received?: number
  /** % of line rate TRex actually sent in the trial */
  offered_pct?: number
  loss_pct: number | null
  latency?: { total_min: number | null; average: number | null; total_max: number | null; jitter: number | null; dropped: number | null }
}
export interface Rfc2544Results {
  /** rate_pct = requested load that passed; offered_pct = what TRex actually sent (lower when TRex itself can't reach the rate, tx_limited). Mpps/Gbps are from offered_pct. */
  throughput?: { size: number; rate_pct: number; offered_pct: number; tx_limited: boolean; mpps: number; gbps_l1: number; gbps_l2: number; trial: { dirs: Rfc2544Dir[] } | null }[]
  latency?: { size: number; rate_pct: number; dirs: Rfc2544Dir[] }[]
  frame_loss?: { size: number; points: { rate_pct: number; offered_pct: number; loss_pct: number | null }[] }[]
  back_to_back?: { size: number; frames: number; seconds: number; capped: boolean }[]
}
/** Log line: code + params, worded by the UI (locales/rfc2544.ts log.*). */
export interface Rfc2544Log {
  ts: number
  code: 'start' | 'trial' | 'result' | 'done' | 'stopped' | 'error'
  params: Record<string, unknown>
}
export interface Rfc2544Summary {
  id: string
  state: 'running' | 'done' | 'stopped' | 'error'
  started: number
  finished: number | null
  client: string | null
  tests: Rfc2544Test[]
  frame_sizes: number[]
  pairs: { tx: number; rx: number }[]
  bidirectional: boolean
}
export interface Rfc2544Job extends Rfc2544Summary {
  config: Rfc2544Config
  progress: { test?: Rfc2544Test; size?: number; rate_pct?: number; burst?: number }
  log: Rfc2544Log[]
  results: Rfc2544Results
  trials: number
  error: string | null
  speeds: Record<string, number>
}

export interface DescField {
  name: string
  repr: string
  bit_offset: number
  bits: number
  kind: FieldKind
  writable: boolean
}

export interface DescLayer {
  proto: string
  name: string
  desc: string
  index: number
  offset: number
  length: number
  /** Auto-added padding, not one of the user's layers. */
  padding: boolean
  fields: DescField[]
}

/** A sanity-check finding. Never blocks saving: malformed packets are a valid test. */
export interface LintItem {
  level: 'warning' | 'info'
  /** Index into the stream's layers, when the finding is about one layer. */
  layer: number | null
  field: string | null
  /** Translate with codedText() from i18n.ts; message is the English fallback. */
  code?: string
  params?: Record<string, unknown>
  message: string
}

export interface PacketDescription {
  hex: string
  length: number
  frame_length: number
  layers: DescLayer[]
  warnings?: LintItem[]
}

export interface VmRow {
  layer: number
  field: string
  op: 'inc' | 'dec' | 'random'
  start: string
  end: string
  step: number
}

export interface StreamSpec {
  id?: string
  name: string
  enabled: boolean
  packet: PacketSpec
  vm: VmRow[]
  mode: { type: 'continuous' | 'single_burst' | 'multi_burst'; total_pkts?: number; pkts_per_burst?: number; ibg_usec?: number; count?: number }
  rate: { unit: 'pps' | 'bps_L1' | 'bps_L2' | 'percentage'; value: number }
  isg_usec?: number
  flow_stats: { type: 'none' | 'stats' | 'latency'; pg_id?: number }
  self_start?: boolean
  next?: string | null
  /** Findings from the last save, shown in the stream list. */
  lint?: LintItem[]
}

export interface LatencyStats {
  average: number | null
  total_min: number | null
  total_max: number | null
  last_max: number | null
  jitter: number | null
  /** Bucket lower bound in μs -> packets. */
  histogram: Record<string, number>
  dropped: number | null
  out_of_order: number | null
  dup: number | null
  seq_too_high: number | null
  seq_too_low: number | null
}

export interface PgStats {
  tx_pkts: number | null
  rx_pkts: number | null
  tx_pps?: number | null
  rx_pps?: number | null
  tx_ports: Record<string, number | null>
  rx_ports: Record<string, number | null>
  latency: LatencyStats | null
}

export interface PortConfig {
  vlan?: number[]
  l2?: { dst_mac: string }
  l3?: { src: string; dst: string }
  ipv6?: { enabled: boolean; src?: string | null }
  promiscuous?: boolean
  multicast?: boolean
  link_up?: boolean
  flow_ctrl?: number
}

export interface PingRecord {
  state: 'ok' | 'timeout' | 'unreachable' | string
  responder: string
  rtt_ms: number | null
  ttl: number | null
}

export interface StreamTemplate {
  id?: string
  name: string
  saved_at: string
  /** A stream without its port-specific bits (id, next link, lint). */
  stream: StreamSpec
}

export interface PcapMeta {
  id: string
  name: string
  source: 'upload' | 'capture'
  size: number
  created_at: string
  packets: number
  duration_s: number
  avg_frame: number
}

export interface PcapPacket {
  index: number
  /** Seconds since the first packet. */
  ts: number
  length: number
  summary: string
}

export interface PushOptions {
  ports: number[]
  ipg_usec?: number | null
  speedup?: number
  count?: number
  duration?: number
  min_ipg_usec?: number | null
  src_mac_pcap?: boolean
  dst_mac_pcap?: boolean
  force?: boolean
}

export interface CaptureStatus {
  id: number
  state: string
  count: number
  limit: number
  mode: string
}

export const MAX_PUSH_COUNT = 0x3fffffff

export interface ProfileFile {
  /** "<source>:<file name>"; the backend resolves it inside its own folders. */
  id: string
  name: string
  source: 'trex' | 'shared'
  /** Folder on the GUI server the file is in. */
  folder: string
  size: number
  modified: string
}

export interface ProfileOption {
  name: string
  flag: string
  kind: 'bool' | 'choice' | 'number' | 'text'
  default: string | number | boolean | null
  choices: string[] | null
  help: string
}

export interface ProfileInfo {
  style: 'argparse' | 'kwargs'
  doc: string
  description: string
  options: ProfileOption[]
}

export interface ProfileRun {
  id: string
  values: Record<string, unknown>
  streams: number | null
}

export interface StreamCheck {
  describe: PacketDescription
  vm: Record<string, unknown>[]
  warnings: LintItem[]
}

export type StatsMessage =
  | {
      type: 'stats'
      ts: number
      global: Record<string, number>
      ports: Record<string, PortStats>
      port_states: Record<string, Pick<PortInfo, 'status' | 'owner' | 'acquired'>>
      pgids: Record<string, PgStats>
      pg_global: Record<string, number | null>
      monitor: MonitorSettings
      events: LogEvent[]
      /** Only when opt-in monitoring is on, and only on ticks where it was fetched. */
      extra?: MonitorExtra
    }
  | { type: 'error'; error: string; monitor: MonitorSettings; events: LogEvent[] }
  | { type: 'disconnected'; monitor: MonitorSettings; events: LogEvent[] }

/** Opt-in monitoring. Each part costs RPC time on the TRex master thread; all off by default. */
export interface MonitorSettings {
  cpu: boolean
  xstats: boolean
  interval: number
}

export interface MonitorExtra {
  ts: number
  error?: string
  /** One entry per TRex data-plane thread: the ports it serves (-1 = none) and the last 20 s of utilization %. */
  cpu?: { ports: number[]; history: number[] }[]
  mbuf?: Record<string, Record<string, { used: number; total: number }>>
  xstats?: Record<string, Record<string, number>>
}

/** Event log entry: an action done through the GUI (code + params, translated by the UI) or a TRex async event (English message). */
export interface LogEvent {
  seq: number
  ts: number
  source: 'gui' | 'trex'
  level: 'info' | 'warning'
  code: string
  params: Record<string, unknown>
  client: string | null
  message: string
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText)
  return data as T
}

const host = (id: string) => `/hosts/${encodeURIComponent(id)}`

export const api = {
  listHosts: () => request<HostSummary[]>('GET', '/hosts'),
  connect: (id: string) => request<HostSummary>('POST', `${host(id)}/connect`),
  disconnect: (id: string) => request<HostSummary>('POST', `${host(id)}/disconnect`),
  ports: (id: string) => request<PortInfo[]>('GET', `${host(id)}/ports`),
  acquire: (id: string, ports: number[], force = false) =>
    request<PortInfo[]>('POST', `${host(id)}/ports/acquire`, { ports, force }),
  release: (id: string, ports: number[]) => request<PortInfo[]>('POST', `${host(id)}/ports/release`, { ports }),
  clearStats: (id: string, ports?: number[]) => request<{ ok: true }>('POST', `${host(id)}/stats/clear`, { ports }),

  protocols: (id: string) => request<ProtocolList>('GET', `${host(id)}/protocols`),
  protocolSchema: (id: string, proto: string) =>
    request<ProtocolSchema>('GET', `${host(id)}/protocols/${encodeURIComponent(proto)}`),
  buildPacket: (id: string, packet: PacketSpec, flowStats?: StreamSpec['flow_stats']) =>
    request<PacketDescription>('POST', `${host(id)}/packet`, { packet, flow_stats: flowStats }),
  checkStream: (id: string, stream: StreamSpec) => request<StreamCheck>('POST', `${host(id)}/streams/check`, { stream }),

  getTemplates: () => request<StreamTemplate[]>('GET', '/templates'),
  putTemplates: (templates: StreamTemplate[]) => request<StreamTemplate[]>('PUT', '/templates', { templates }),

  getStreams: (id: string, port: number) => request<StreamSpec[]>('GET', `${host(id)}/ports/${port}/streams`),
  putStreams: (id: string, port: number, streams: StreamSpec[]) =>
    request<StreamSpec[]>('PUT', `${host(id)}/ports/${port}/streams`, { streams }),

  start: (id: string, ports: number[], mult = '1', force = false, duration = -1) =>
    request<PortInfo[]>('POST', `${host(id)}/traffic/start`, { ports, mult, force, duration }),
  traffic: (id: string, action: 'stop' | 'pause' | 'resume' | 'reset', ports: number[]) =>
    request<PortInfo[]>('POST', `${host(id)}/traffic/${action}`, { ports }),
  update: (id: string, ports: number[], mult: string) =>
    request<PortInfo[]>('POST', `${host(id)}/traffic/update`, { ports, mult }),

  portConfig: (id: string, port: number, cfg: PortConfig) =>
    request<{ ports: PortInfo[]; warnings: Coded[] }>('POST', `${host(id)}/ports/${port}/config`, cfg),
  resolve: (id: string, ports: number[]) =>
    request<{ ports: PortInfo[]; warnings: Coded[] }>('POST', `${host(id)}/ports/resolve`, { ports }),
  getPortProfiles: (id: string) => request<PortProfilesDoc>('GET', `${host(id)}/port-profiles`),
  putPortProfiles: (id: string, doc: PortProfilesDoc) => request<PortProfilesDoc>('PUT', `${host(id)}/port-profiles`, doc),
  listPcaps: () => request<PcapMeta[]>('GET', '/pcaps'),
  renamePcap: (pcapId: string, name: string) => request<PcapMeta>('POST', `/pcaps/${pcapId}/rename`, { name }),
  deletePcap: (pcapId: string) => request<{ ok: true }>('DELETE', `/pcaps/${pcapId}`),
  pcapDownloadUrl: (pcapId: string) => `api/pcaps/${pcapId}/download`,
  pcapPackets: (id: string, pcapId: string, start = 0, count = 200) =>
    request<PcapPacket[]>('GET', `${host(id)}/pcaps/${pcapId}/packets?start=${start}&count=${count}`),
  pcapToStreams: (id: string, pcapId: string, indices: number[]) =>
    request<(StreamSpec & { import_note: string | null; import_note_code: string | null })[]>('POST', `${host(id)}/pcaps/${pcapId}/to-streams`, { indices }),
  pushPcap: (id: string, pcapId: string, opts: PushOptions) =>
    request<PortInfo[]>('POST', `${host(id)}/traffic/push`, { pcap_id: pcapId, ...opts }),
  startCapture: (id: string, body: { tx_ports: number[]; rx_ports: number[]; limit: number; mode: string; bpf_filter: string; service: boolean }) =>
    request<{ id: number }>('POST', `${host(id)}/captures`, body),
  captures: (id: string) => request<CaptureStatus[]>('GET', `${host(id)}/captures`),
  stopCapture: (id: string, captureId: number, save: boolean, name: string) =>
    request<PcapMeta | null>('POST', `${host(id)}/captures/${captureId}/stop`, { save, name }),

  profiles: (id: string) => request<{ profiles: ProfileFile[]; upload_allowed: boolean }>('GET', `${host(id)}/profiles`),
  profileInfo: (id: string, profileId: string) =>
    request<ProfileInfo>('GET', `${host(id)}/profiles/info?id=${encodeURIComponent(profileId)}`),
  startProfile: (id: string, body: { id: string; ports: number[]; values: Record<string, unknown>; mult: string; duration: number; force: boolean }) =>
    request<{ ports: PortInfo[]; streams: Record<string, number> }>('POST', `${host(id)}/traffic/start-profile`, body),
  profileRuns: (id: string) => request<Record<string, ProfileRun>>('GET', `${host(id)}/profile-runs`),
  events: (id: string) => request<LogEvent[]>('GET', `${host(id)}/events`),
  streamStates: (id: string, port: number) => request<StreamStates>('GET', `${host(id)}/ports/${port}/streams/state`),
  streamControl: (id: string, port: number, streamIds: string[], action: 'pause' | 'resume' | 'update', mult?: string) =>
    request<StreamStates>('POST', `${host(id)}/ports/${port}/streams/control`, { stream_ids: streamIds, action, mult }),
  pushPacket: (id: string, port: number, packet: PacketSpec, count: number, ipgUsec = 0) =>
    request<{ sent: number; bytes: number }>('POST', `${host(id)}/ports/${port}/push`, { packet, count, ipg_usec: ipgUsec }),
  setServiceMode: (id: string, port: number, mode: ServiceMode) =>
    request<PortInfo[]>('POST', `${host(id)}/ports/${port}/service`, { mode }),
  nsNodes: (id: string, port: number) => request<NsNode[]>('GET', `${host(id)}/ports/${port}/ns`),
  nsAdd: (id: string, port: number, node: NsNodeSpec) => request<NsNode[]>('POST', `${host(id)}/ports/${port}/ns`, node),
  nsRemove: (id: string, port: number, macs: string[]) => request<NsNode[]>('POST', `${host(id)}/ports/${port}/ns/remove`, { macs }),
  rfcStart: (id: string, cfg: Rfc2544Config) => request<Rfc2544Job>('POST', `${host(id)}/rfc2544`, cfg),
  rfcCurrent: (id: string) => request<Rfc2544Job | null>('GET', `${host(id)}/rfc2544`),
  rfcStop: (id: string) => request<Rfc2544Job | null>('POST', `${host(id)}/rfc2544/stop`),
  rfcHistory: (id: string) => request<Rfc2544Summary[]>('GET', `${host(id)}/rfc2544/history`),
  rfcResult: (id: string, runId: string) => request<Rfc2544Job>('GET', `${host(id)}/rfc2544/history/${runId}`),
  rfcDelete: (id: string, runId: string) => request<{ ok: true }>('DELETE', `${host(id)}/rfc2544/history/${runId}`),
  setMonitor: (id: string, settings: MonitorSettings) => request<MonitorSettings>('PUT', `${host(id)}/monitor`, settings),
  uploadProfile: async (file: File) => {
    const res = await fetch(`api/profiles?name=${encodeURIComponent(file.name)}`, { method: 'POST', body: file })
    const data = await res.json().catch(() => null)
    if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText)
  },
  deleteProfile: (name: string) => request<{ ok: true }>('DELETE', `/profiles/${encodeURIComponent(name)}`),

  ping: (id: string, port: number, dst_ip: string, count = 3) =>
    request<PingRecord[]>('POST', `${host(id)}/ports/${port}/ping`, { dst_ip, count }),
}

/** Upload with progress (fetch can't report upload progress). The body is the raw file. */
export function uploadPcap(file: File, onProgress: (fraction: number) => void): Promise<PcapMeta> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `api/pcaps?name=${encodeURIComponent(file.name)}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      let data: { detail?: string } | null = null
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as unknown as PcapMeta)
      else reject(new ApiError(xhr.status, data?.detail ?? xhr.statusText))
    }
    xhr.onerror = () => reject(new ApiError(0, t('common.uploadNetworkError')))
    xhr.send(file)
  })
}

export function statsSocketUrl(id: string): string {
  const url = new URL(`api${host(id)}/stats`, window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}
