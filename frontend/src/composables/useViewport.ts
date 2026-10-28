import { readonly, ref } from 'vue'

// One shared resize listener; components read the width reactively. Layout
// breakpoints that only change CSS live in media queries instead.
const width = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
if (typeof window !== 'undefined') {
  window.addEventListener('resize', () => (width.value = window.innerWidth), { passive: true })
}

export const viewportWidth = readonly(width)

/** Below this the host sidebar is forced closed and forms put labels on top. */
export const NARROW = 900
