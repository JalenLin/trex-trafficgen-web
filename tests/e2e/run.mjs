// Browser end-to-end tests against mock hosts.
//   node tests/e2e/run.mjs [filter ...]
// Starts its own backend on E2E_PORT (default 8098) with a fresh data dir, runs every
// spec in order, prints a pass/fail table and exits non-zero on any failure.
// Screenshots go to $E2E_OUT/e2e-shots (default: <tmp>/trex-gui-e2e).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { BASE, OUT, SHOTS, buildFrontendIfStale, closeBrowser, launch, runAll, startServer, stopServer } from './lib.mjs'

const filter = process.argv.slice(2)
const specs = path.join(path.dirname(fileURLToPath(import.meta.url)), 'specs')

fs.mkdirSync(OUT, { recursive: true })
fs.rmSync(SHOTS, { recursive: true, force: true })
buildFrontendIfStale()

const t0 = Date.now()
let results = []
try {
  const { data } = await startServer()
  process.env.E2E_DATA = data
  console.log(`mock backend at ${BASE} (data ${data})`)
  await launch()
  for (const f of fs.readdirSync(specs).filter((f) => f.endsWith('.mjs')).sort()) await import(pathToFileURL(path.join(specs, f)))
  results = await runAll(filter.length ? filter : null)
} finally {
  await closeBrowser().catch(() => {})
  await stopServer()
}

const pad = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s.padEnd(n))
console.log('\n' + pad('Test', 78) + ' Result  Time')
console.log('-'.repeat(95))
for (const r of results) console.log(`${pad(r.id, 78)} ${r.status.padEnd(7)} ${(r.ms / 1000).toFixed(1)}s`)
const failed = results.filter((r) => r.status !== 'PASS')
console.log('-'.repeat(95))
console.log(`${results.length - failed.length}/${results.length} passed in ${((Date.now() - t0) / 1000).toFixed(0)}s; screenshots in ${SHOTS}`)
for (const r of failed) console.log(`FAIL ${r.id}\n     ${r.detail}`)
process.exit(failed.length || !results.length ? 1 : 0)
