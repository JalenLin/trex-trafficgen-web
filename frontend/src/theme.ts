// Light / dark / follow the OS. Chosen in the header, remembered per browser.
// Components with their own colors read `isDark` (or the `dark` class it puts
// on <html>) instead of `prefers-color-scheme`, so the toggle wins over the OS.
import { computed, ref, watchEffect } from 'vue'
import { persisted } from './utils/prefs'

export type ThemePref = 'system' | 'light' | 'dark'

export const themePref = persisted<ThemePref>('theme', 'system')

const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
const osDark = ref(media?.matches ?? false)
media?.addEventListener('change', (e) => (osDark.value = e.matches))

export const isDark = computed(() => (themePref.value === 'system' ? osDark.value : themePref.value === 'dark'))

watchEffect(() => {
  const root = document.documentElement
  root.classList.toggle('dark', isDark.value)
  // Native parts (scrollbars, form controls) follow too.
  root.style.colorScheme = isDark.value ? 'dark' : 'light'
})
