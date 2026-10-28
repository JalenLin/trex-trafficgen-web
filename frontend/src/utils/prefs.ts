// Per-browser conveniences kept in localStorage: UI state, recent values, drafts.
// Shared or durable data (streams, templates) lives on the backend instead.
// Storage can be unavailable (private mode, blocked site data); everything here
// degrades to "not remembered" rather than failing.
import { ref, watch, type Ref } from 'vue'

const PREFIX = 'trex-gui:'

export function loadPref<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function savePref(key: string, value: unknown) {
  try {
    if (value === undefined) localStorage.removeItem(PREFIX + key)
    else localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    /* not remembered */
  }
}

/** A ref that starts from, and writes back to, localStorage. */
export function persisted<T>(key: string, fallback: T): Ref<T> {
  const r = ref(loadPref(key, fallback)) as Ref<T>
  watch(r, (v) => savePref(key, v), { deep: true })
  return r
}

/** Most-recent-first list without duplicates, capped at `max`. */
export function pushRecent<T>(list: Ref<T[]>, value: T, max = 10) {
  list.value = [value, ...list.value.filter((v) => JSON.stringify(v) !== JSON.stringify(value))].slice(0, max)
}
