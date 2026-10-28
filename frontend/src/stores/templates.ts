import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type StreamSpec, type StreamTemplate } from '../api'
import { t } from '../i18n'
import { persisted } from '../utils/prefs'
import { clone } from '../utils/streams'

/**
 * Two template libraries:
 *  - personal: this browser's localStorage, visible only to this user
 *  - shared:   the backend, visible to everyone on every TRex host
 */
export type TemplateScope = 'personal' | 'shared'

// crypto.randomUUID needs a secure context, which http://<trex-host>:8080 is not.
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8)

function strip(stream: StreamSpec): StreamSpec {
  const s = clone(stream)
  delete s.id
  delete s.lint
  s.next = null // links point at stream ids on the original port
  return s
}

export const useTemplatesStore = defineStore('templates', () => {
  const personal = persisted<StreamTemplate[]>('templates.personal', [])
  const shared = ref<StreamTemplate[]>([])
  const sharedLoaded = ref(false)

  async function loadShared() {
    shared.value = await api.getTemplates()
    sharedLoaded.value = true
  }

  async function ensure() {
    if (!sharedLoaded.value) await loadShared()
  }

  // Shared edits re-read first so a teammate's change made meanwhile isn't overwritten.
  async function editShared(change: (list: StreamTemplate[]) => StreamTemplate[]) {
    await loadShared()
    shared.value = await api.putTemplates(change(shared.value))
  }

  async function add(scope: TemplateScope, name: string, stream: StreamSpec) {
    const t: StreamTemplate = { name, saved_at: new Date().toISOString(), stream: strip(stream) }
    if (scope === 'personal') personal.value = [...personal.value, { ...t, id: newId() }]
    else await editShared((list) => [...list, t])
  }

  async function remove(scope: TemplateScope, id: string) {
    if (scope === 'personal') personal.value = personal.value.filter((t) => t.id !== id)
    else await editShared((list) => list.filter((t) => t.id !== id))
  }

  async function rename(scope: TemplateScope, id: string, name: string) {
    const apply = (list: StreamTemplate[]) => list.map((t) => (t.id === id ? { ...t, name } : t))
    if (scope === 'personal') personal.value = apply(personal.value)
    else await editShared(apply)
  }

  /** Copy a template to the other library (the original stays). */
  async function copyTo(target: TemplateScope, t: StreamTemplate) {
    await add(target, t.name, t.stream)
  }

  function exportPersonal(): Blob {
    return new Blob([JSON.stringify({ kind: 'trex-gui-templates', version: 1, templates: personal.value }, null, 1)], {
      type: 'application/json',
    })
  }

  /** Adds the file's templates to the personal library; returns how many. */
  async function importPersonal(file: File): Promise<number> {
    const data = JSON.parse(await file.text())
    const list: StreamTemplate[] = Array.isArray(data) ? data : data?.templates
    if (!Array.isArray(list) || !list.every((t) => t && typeof t.name === 'string' && t.stream?.packet)) {
      throw new Error(t('streams.templates.notTemplateFile'))
    }
    personal.value = [...personal.value, ...list.map((t) => ({ ...t, id: newId(), stream: strip(t.stream) }))]
    return list.length
  }

  return { personal, shared, sharedLoaded, loadShared, ensure, add, remove, rename, copyTo, exportPersonal, importPersonal }
})
