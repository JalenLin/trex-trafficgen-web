// UI language: chosen in the header, remembered per browser; the first visit
// follows the browser's language (Chinese -> zh-TW, anything else -> English).
import { createI18n } from 'vue-i18n'
import { messages, type Lang } from './locales'
import { loadPref, savePref } from './utils/prefs'

export type { Lang }

export const LANGS: { value: Lang; label: string }[] = [
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'en', label: 'English' },
]

function initialLang(): Lang {
  const saved = loadPref<string | null>('lang', null)
  if (saved === 'zh-TW' || saved === 'en') return saved
  const prefs = typeof navigator === 'undefined' ? [] : navigator.languages ?? [navigator.language]
  return prefs.some((l) => l?.toLowerCase().startsWith('zh')) ? 'zh-TW' : 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLang(),
  fallbackLocale: 'en',
  messages,
})

/** For plain .ts modules. Call at render time, never at import time, or the text won't follow a language switch. */
export const t = i18n.global.t

export function currentLang(): Lang {
  return i18n.global.locale.value as Lang
}

export function setLang(lang: Lang) {
  i18n.global.locale.value = lang
  savePref('lang', lang)
  document.documentElement.lang = lang
}
document.documentElement.lang = initialLang()

/** Backend lint/check warnings carry a code + params; the message is an English fallback for unknown codes. */
export interface Coded {
  code?: string
  params?: Record<string, unknown>
  message: string
}

export function codedText(w: Coded, prefix = 'lint'): string {
  const key = `${prefix}.${w.code}`
  return w.code && i18n.global.te(key) ? t(key, (w.params ?? {}) as Record<string, unknown>) : w.message
}
