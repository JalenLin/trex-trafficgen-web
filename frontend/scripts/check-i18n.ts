// Compiles every UI message with vue-i18n's compiler and compares the zh-TW and en key sets.
// The type check already catches missing keys; this also catches message syntax errors
// (e.g. an unescaped { or @), which otherwise only show up at runtime.
//   npx tsx scripts/check-i18n.ts
import { baseCompile } from '@intlify/message-compiler'
import { messages } from '../src/locales/index'

let n = 0
let bad = 0
function walk(o: unknown, path: string) {
  if (typeof o === 'string') {
    n++
    try {
      baseCompile(o, { onError: (e) => { throw e } })
    } catch (e) {
      bad++
      console.log('BAD', path, JSON.stringify(o), (e as Error).message)
    }
  } else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) walk(v, `${path}.${k}`)
}
for (const [lang, m] of Object.entries(messages)) walk(m, lang)

const keys = (o: unknown, p = ''): string[] =>
  typeof o === 'string' ? [p] : Object.entries(o as object).flatMap(([k, v]) => keys(v, p ? `${p}.${k}` : k))
const zh = new Set(keys(messages['zh-TW']))
const en = new Set(keys(messages.en))
const mismatched = [...zh].filter((k) => !en.has(k)).concat([...en].filter((k) => !zh.has(k)))
console.log(`${n} messages, ${bad} syntax errors; zh ${zh.size} keys, en ${en.size} keys, mismatched: ${mismatched.join(', ') || 'none'}`)
process.exit(bad || mismatched.length ? 1 : 0)
