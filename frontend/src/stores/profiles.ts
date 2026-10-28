import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type PortProfile, type PortProfilesDoc, type PortSettings } from '../api'

/** Port L2/L3 profiles, kept on the backend per TRex host (they follow its cabling). */
export const useProfilesStore = defineStore('portProfiles', () => {
  const docs = ref<Record<string, PortProfilesDoc>>({})

  async function load(hostId: string) {
    docs.value[hostId] = await api.getPortProfiles(hostId)
    return docs.value[hostId]
  }

  // Re-read before every write so a teammate's change made meanwhile isn't lost.
  async function edit(hostId: string, change: (doc: PortProfilesDoc) => PortProfilesDoc) {
    docs.value[hostId] = await api.putPortProfiles(hostId, change(await api.getPortProfiles(hostId)))
  }

  const add = (hostId: string, name: string, ports: Record<string, PortSettings>) =>
    edit(hostId, (d) => ({ ...d, profiles: [...d.profiles, { name, saved_at: new Date().toISOString(), ports }] }))

  const remove = (hostId: string, id: string) => edit(hostId, (d) => ({ ...d, profiles: d.profiles.filter((p) => p.id !== id) }))

  const rename = (hostId: string, id: string, name: string) =>
    edit(hostId, (d) => ({ ...d, profiles: d.profiles.map((p) => (p.id === id ? { ...p, name } : p)) }))

  /** Remember what was applied, so a later TRex restart or outside change can be noticed. */
  const recordApplied = (hostId: string, profile: Pick<PortProfile, 'id' | 'name' | 'ports'>, serverStarted: string | null) =>
    edit(hostId, (d) => ({
      ...d,
      last_applied: { profile_id: profile.id, name: profile.name, at: new Date().toISOString(), server_started: serverStarted, ports: profile.ports },
    }))

  /** A port changed by hand in the GUI no longer follows the last applied profile. */
  async function forgetPorts(hostId: string, ports: number[]) {
    const la = docs.value[hostId]?.last_applied
    if (!la || !ports.some((p) => String(p) in la.ports)) return
    await edit(hostId, (d) => {
      if (!d.last_applied) return d
      const kept = Object.fromEntries(Object.entries(d.last_applied.ports).filter(([p]) => !ports.includes(Number(p))))
      return { ...d, last_applied: Object.keys(kept).length ? { ...d.last_applied, ports: kept } : null }
    })
  }

  return { docs, load, add, remove, rename, recordApplied, forgetPorts }
})
