import { onBeforeUnmount, ref, shallowRef, watch, type Ref } from 'vue'
import { api, statsSocketUrl, type LogEvent, type MonitorExtra, type MonitorSettings, type StatsMessage } from '../api'

const RECONNECT_MS = 2000
/** Rate history kept in the browser for the charts (from samples already received, no extra polling). */
export const HISTORY_SECONDS = 15 * 60

export interface RateSample {
  ts: number
  ports: Record<string, { tx_bps: number; rx_bps: number; tx_pps: number; rx_pps: number }>
}

/** Live stats for one host over WebSocket; reconnects on drop and follows hostId changes. */
export function useStatsStream(hostId: Readonly<Ref<string | null>>) {
  // shallowRef: each message replaces the whole snapshot, no need for deep reactivity.
  const latest = shallowRef<Extract<StatsMessage, { type: 'stats' }> | null>(null)
  const error = ref<string | null>(null)
  const socketOpen = ref(false)
  /** The backend reports the host is no longer connected (e.g. TRex went away). */
  const disconnected = ref(false)
  const history = shallowRef<RateSample[]>([])
  const events = shallowRef<LogEvent[]>([])
  const monitor = ref<MonitorSettings | null>(null)
  const extra = shallowRef<MonitorExtra | null>(null)

  let ws: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined

  function close() {
    clearTimeout(retry)
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    socketOpen.value = false
  }

  function addEvents(list: LogEvent[]) {
    const last = events.value.at(-1)?.seq ?? 0
    const fresh = list.filter((e) => e.seq > last)
    if (fresh.length) events.value = [...events.value, ...fresh].slice(-1000)
  }

  function record(msg: Extract<StatsMessage, { type: 'stats' }>) {
    const ports: RateSample['ports'] = {}
    for (const [id, p] of Object.entries(msg.ports)) {
      ports[id] = { tx_bps: p.tx_bps, rx_bps: p.rx_bps, tx_pps: p.tx_pps, rx_pps: p.rx_pps }
    }
    const cutoff = msg.ts - HISTORY_SECONDS
    const kept = history.value.length && history.value[0].ts < cutoff ? history.value.filter((s) => s.ts >= cutoff) : history.value
    history.value = [...kept, { ts: msg.ts, ports }]
  }

  function open(id: string) {
    close()
    // The backend keeps the log; on (re)connect start from its copy.
    api.events(id).then(addEvents, () => undefined)
    ws = new WebSocket(statsSocketUrl(id))
    ws.onopen = () => (socketOpen.value = true)
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as StatsMessage
      disconnected.value = msg.type === 'disconnected'
      monitor.value = msg.monitor
      addEvents(msg.events ?? [])
      if (msg.type === 'stats') {
        latest.value = msg
        error.value = null
        record(msg)
        if (msg.extra) extra.value = msg.extra
        if (!msg.monitor.cpu && !msg.monitor.xstats) extra.value = null
      } else if (msg.type === 'error') {
        error.value = msg.error
      } else {
        latest.value = null
      }
    }
    ws.onclose = () => {
      socketOpen.value = false
      retry = setTimeout(() => open(id), RECONNECT_MS)
    }
  }

  watch(
    hostId,
    (id) => {
      latest.value = null
      error.value = null
      history.value = []
      events.value = []
      extra.value = null
      if (id) open(id)
      else close()
    },
    { immediate: true },
  )

  onBeforeUnmount(close)

  return { latest, error, socketOpen, disconnected, history, events, monitor, extra }
}
