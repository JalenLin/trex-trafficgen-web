import { defineStore } from 'pinia'
import { markRaw, ref } from 'vue'
import { api, type ProtocolList, type ProtocolSchema, type StreamSpec } from '../api'

const key = (hostId: string, port: number) => `${hostId}:${port}`

export function newStream(name: string): StreamSpec {
  return {
    name,
    enabled: true,
    packet: {
      layers: [
        { proto: 'Ether', fields: {} },
        { proto: 'IP', fields: { src: '16.0.0.1', dst: '48.0.0.1' } },
        { proto: 'UDP', fields: { sport: 1025, dport: 12 } },
      ],
      frame_size: 64,
    },
    vm: [],
    mode: { type: 'continuous' },
    rate: { unit: 'percentage', value: 10 },
    flow_stats: { type: 'none' },
    self_start: true,
    next: null,
  }
}

export const useStreamsStore = defineStore('streams', () => {
  const byPort = ref<Record<string, StreamSpec[]>>({})

  // The catalog holds thousands of entries and never changes; keep it out of
  // Vue's deep reactivity.
  const catalogs = ref<Record<string, ProtocolList>>({})
  const schemas = new Map<string, Promise<ProtocolSchema>>()

  function get(hostId: string, port: number): StreamSpec[] | undefined {
    return byPort.value[key(hostId, port)]
  }

  async function load(hostId: string, port: number) {
    byPort.value[key(hostId, port)] = await api.getStreams(hostId, port)
    return byPort.value[key(hostId, port)]
  }

  async function ensure(hostId: string, port: number) {
    return get(hostId, port) ?? (await load(hostId, port))
  }

  async function save(hostId: string, port: number, streams: StreamSpec[]) {
    byPort.value[key(hostId, port)] = await api.putStreams(hostId, port, streams)
  }

  async function catalog(hostId: string): Promise<ProtocolList> {
    if (!catalogs.value[hostId]) catalogs.value[hostId] = markRaw(await api.protocols(hostId))
    return catalogs.value[hostId]
  }

  function schema(hostId: string, proto: string): Promise<ProtocolSchema> {
    const k = `${hostId}:${proto}`
    if (!schemas.has(k)) {
      const p = api.protocolSchema(hostId, proto)
      p.catch(() => schemas.delete(k))
      schemas.set(k, p)
    }
    return schemas.get(k)!
  }

  /** Latency pg_ids must be unique per TRex; pick one above every id in use on the given ports. */
  async function nextPgId(hostId: string, ports: number[]): Promise<number> {
    let max = 0
    for (const p of ports) {
      for (const s of await ensure(hostId, p)) {
        if (s.flow_stats.type !== 'none' && s.flow_stats.pg_id != null) max = Math.max(max, s.flow_stats.pg_id)
      }
    }
    return max + 1
  }

  return { byPort, catalogs, get, load, ensure, save, catalog, schema, nextPgId }
})
