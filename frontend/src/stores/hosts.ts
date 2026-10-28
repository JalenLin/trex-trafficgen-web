import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type HostSummary, type PortConfig, type PortInfo } from '../api'
import { persisted } from '../utils/prefs'

export type TrafficAction = 'start' | 'stop' | 'pause' | 'resume' | 'reset'

export const useHostsStore = defineStore('hosts', () => {
  const hosts = ref<HostSummary[]>([])
  const ports = ref<Record<string, PortInfo[]>>({})
  // Remembered per browser: last host, and per host the ticked ports (bulk
  // actions) and the focused port (streams / settings shown).
  const selectedId = persisted<string | null>('selectedHost', null)
  const checked = persisted<Record<string, number[]>>('checkedPorts', {})
  const focused = persisted<Record<string, number | null>>('focusedPort', {})
  // Main area: one host's panel, or all hosts side by side.
  const view = persisted<'host' | 'overview'>('mainView', 'host')

  const selected = computed(() => hosts.value.find((h) => h.id === selectedId.value) ?? null)

  function upsert(summary: HostSummary) {
    const i = hosts.value.findIndex((h) => h.id === summary.id)
    if (i >= 0) hosts.value[i] = summary
    else hosts.value.push(summary)
  }

  async function load() {
    hosts.value = await api.listHosts()
    if (!hosts.value.some((h) => h.id === selectedId.value)) selectedId.value = hosts.value[0]?.id ?? null
  }

  async function connect(id: string) {
    try {
      upsert(await api.connect(id))
    } finally {
      // Connect failures are recorded server-side (last_error); pull them in either way.
      await load()
    }
    await refreshPorts(id)
  }

  async function disconnect(id: string) {
    upsert(await api.disconnect(id))
    delete ports.value[id]
  }

  function setPorts(id: string, list: PortInfo[]) {
    ports.value[id] = list
    // Remembered selections may name ports this host no longer has.
    const ids = new Set(list.map((p) => p.id))
    if (checked.value[id]?.some((p) => !ids.has(p))) checked.value[id] = checked.value[id].filter((p) => ids.has(p))
    if ((focused.value[id] == null || !ids.has(focused.value[id]!)) && list.length) focused.value[id] = list[0].id
  }

  /** Apply status/owner changes pushed with each stats sample (other users, finished bursts). */
  function mergePortStates(id: string, states: Record<string, Pick<PortInfo, 'status' | 'owner' | 'acquired'>>) {
    for (const p of ports.value[id] ?? []) {
      const s = states[p.id]
      if (s && (s.status !== p.status || s.owner !== p.owner || s.acquired !== p.acquired)) Object.assign(p, s)
    }
  }

  async function refreshPorts(id: string) {
    setPorts(id, await api.ports(id))
  }

  async function acquire(id: string, portIds: number[], force = false) {
    setPorts(id, await api.acquire(id, portIds, force))
  }

  async function release(id: string, portIds: number[]) {
    setPorts(id, await api.release(id, portIds))
  }

  async function traffic(
    id: string,
    action: TrafficAction,
    portIds: number[],
    opts: { mult?: string; force?: boolean; duration?: number | null } = {},
  ) {
    const list =
      action === 'start'
        ? await api.start(id, portIds, opts.mult ?? '1', opts.force ?? false, opts.duration && opts.duration > 0 ? opts.duration : -1)
        : await api.traffic(id, action, portIds)
    setPorts(id, list)
  }

  async function updateRate(id: string, portIds: number[], mult: string) {
    setPorts(id, await api.update(id, portIds, mult))
  }

  /** Returns warnings (e.g. gateway did not answer ARP); errors throw. */
  async function configurePort(id: string, port: number, cfg: PortConfig): Promise<string[]> {
    const r = await api.portConfig(id, port, cfg)
    setPorts(id, r.ports)
    return r.warnings
  }

  async function resolve(id: string, portIds: number[]): Promise<string[]> {
    const r = await api.resolve(id, portIds)
    setPorts(id, r.ports)
    return r.warnings
  }

  return {
    hosts, selectedId, selected, ports, checked, focused, view,
    load, connect, disconnect, refreshPorts, mergePortStates, acquire, release, traffic, updateRate,
    configurePort, resolve,
  }
})
