// Small test harness: a mock backend of our own, a browser, page error collection,
// and a registry of named tests that run in order and report pass/fail.
import { spawn, execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
export const PORT = Number(process.env.E2E_PORT ?? 8098)
export const BASE = `http://127.0.0.1:${PORT}/`
export const OUT = process.env.E2E_OUT ?? path.join(os.tmpdir(), 'trex-gui-e2e')
export const SHOTS = path.join(OUT, 'e2e-shots')
// Chromium: $CHROME if set, else the one `npx playwright-core install chromium` put in place.
const CHROME = process.env.CHROME || undefined
// Python with the backend installed: $E2E_PYTHON, else the repo's backend/.venv.
const PYTHON = process.env.E2E_PYTHON || path.join(ROOT, 'backend/.venv/bin/python')

// ---------- assertions ----------
export class AssertionError extends Error {}
export function assert(cond, msg) {
  if (!cond) throw new AssertionError(msg)
}
export function eq(actual, expected, msg) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  if (a !== e) throw new AssertionError(`${msg}: expected ${e}, got ${a}`)
}
export async function until(fn, msg, timeout = 8000, every = 200) {
  const end = Date.now() + timeout
  let last
  while (Date.now() < end) {
    try {
      last = await fn()
      if (last) return last
    } catch (e) {
      last = e.message
    }
    await new Promise((r) => setTimeout(r, every))
  }
  throw new AssertionError(`${typeof msg === 'function' ? msg() : msg} (timed out; last: ${typeof last === 'string' ? last : JSON.stringify(last)})`)
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ---------- API ----------
export async function api(method, p, body) {
  const r = await fetch(BASE + 'api' + p, {
    method,
    headers: body !== undefined ? { 'content-type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const text = await r.text()
  let data
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!r.ok) throw new Error(`${method} ${p} -> ${r.status}: ${text.slice(0, 200)}`)
  return data
}
export const hostApi = (host) => ({
  get: (p) => api('GET', `/hosts/${host}${p}`),
  post: (p, b = {}) => api('POST', `/hosts/${host}${p}`, b),
  put: (p, b) => api('PUT', `/hosts/${host}${p}`, b),
  del: (p) => api('DELETE', `/hosts/${host}${p}`),
})

// ---------- mock backend ----------
let server = null
export async function startServer() {
  const busy = execSync(`ss -ltnp | grep ':${PORT} ' || true`).toString().trim()
  if (busy) throw new Error(`port ${PORT} is already in use: ${busy}`)
  const data = path.join(OUT, `e2e-data-${Date.now()}`)
  fs.mkdirSync(data, { recursive: true })
  const cfg = path.join(OUT, 'e2e.yaml')
  fs.writeFileSync(
    cfg,
    `server: {host: 127.0.0.1, port: ${PORT}, stats_interval: 0.5, data_dir: ${data}}
hosts:
  - {id: demo, name: Demo, mock: true, mock_ports: 8}
  - {id: lab-b, name: Lab B, mock: true, mock_ports: 4}
  - {id: far, name: Far TRex, server: 192.0.2.10, client_path: /nonexistent}
`,
  )
  const log = fs.openSync(path.join(OUT, 'e2e-server.log'), 'w')
  server = spawn(PYTHON, ['-m', 'trex_gui', '-c', cfg], {
    cwd: ROOT,
    stdio: ['ignore', log, log],
  })
  server.on('exit', (code) => {
    if (server) console.log(`!! mock backend exited with ${code}; see ${path.join(OUT, 'e2e-server.log')}`)
  })
  await until(async () => (await fetch(BASE + 'api/hosts')).ok, 'mock backend did not start', 20000)
  return { data, cfg }
}
export async function stopServer() {
  if (!server) return
  const s = server
  server = null
  s.kill('SIGTERM')
  await new Promise((r) => {
    const t = setTimeout(() => {
      s.kill('SIGKILL')
      r()
    }, 5000)
    s.on('exit', () => {
      clearTimeout(t)
      r()
    })
  })
}

export function buildFrontendIfStale() {
  const newest = (dir) => {
    let m = 0
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      m = Math.max(m, e.isDirectory() ? newest(p) : fs.statSync(p).mtimeMs)
    }
    return m
  }
  const index = path.join(ROOT, 'frontend/dist/index.html')
  const built = fs.existsSync(index) ? fs.statSync(index).mtimeMs : 0
  if (built < newest(path.join(ROOT, 'frontend/src'))) {
    console.log('frontend/dist is older than frontend/src: building…')
    execSync('npm run build', { cwd: path.join(ROOT, 'frontend'), stdio: 'inherit' })
  }
}

// ---------- browser ----------
let browser = null
export async function launch() {
  browser = await chromium.launch({ executablePath: CHROME })
  return browser
}
export async function closeBrowser() {
  await browser?.close()
}

// Every page records page errors, console errors and vue-i18n "not found" warnings.
const pages = new Set()
export async function openPage({ locale = 'zh-TW', width = 1500, height = 950, colorScheme = 'light', storage } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, locale, colorScheme, acceptDownloads: true, storageState: storage })
  const page = await ctx.newPage()
  page.setDefaultTimeout(8000)
  page.errors = []
  page.on('pageerror', (e) => page.errors.push(`pageerror: ${e.message}`))
  page.on('console', (m) => {
    const text = m.text()
    if (m.type() === 'error') page.errors.push(`console.error: ${text}`)
    else if (m.type() === 'warning' && /intlify|Not found '|Cannot translate/i.test(text)) page.errors.push(`i18n: ${text}`)
  })
  pages.add(page)
  ctx.on('close', () => pages.delete(page))
  return page
}
export function takeErrors() {
  const out = []
  for (const p of pages) {
    out.push(...p.errors)
    p.errors = []
  }
  return out
}

let shotN = 0
export async function shot(page, name) {
  fs.mkdirSync(SHOTS, { recursive: true })
  const file = path.join(SHOTS, `${String(++shotN).padStart(3, '0')}-${name.replace(/[^\w.-]+/g, '_')}.png`)
  await page.screenshot({ path: file, fullPage: false }).catch(() => {})
  return file
}

// ---------- UI helpers ----------
export const ui = (page) => ({
  rows: () => page.locator('.port-list .row'),
  row: (i) => page.locator('.port-list .row').nth(i),
  async pickHost(name) {
    const item = page.locator('.list .item', { hasText: name })
    if (!(await item.count())) {
      // collapsed sider (narrow screens)
      await page.locator('.burger').click()
    }
    await page.locator('.list .item', { hasText: name }).first().click()
  },
  async check(i, on = true) {
    const cb = page.locator('.port-list .row').nth(i).locator('.n-checkbox')
    const checked = (await cb.getAttribute('class')).includes('n-checkbox--checked')
    if (checked !== on) await cb.click()
  },
  async uncheckAll() {
    const n = await page.locator('.port-list .row').count()
    for (let i = 0; i < n; i++) await this.check(i, false)
  },
  async focus(i) {
    await page.locator('.port-list .row').nth(i).locator('.name').click()
  },
  async tab(name) {
    await page.locator('.n-tabs-tab', { hasText: name }).first().click()
    await page.waitForTimeout(250)
  },
  toolbar: () => page.locator('.toolbar'),
  // Start; if the UI still thinks a port is running it asks to restart, which we accept.
  async start() {
    await page.locator('.toolbar').getByRole('button', { name: /開始|Start/ }).click()
    const ok = page.locator('.n-popconfirm__action .n-button--primary-type:visible').last()
    if (await ok.waitFor({ timeout: 700 }).then(() => true, () => false)) await ok.click({ timeout: 2000 }).catch(() => {})
  },
  tb: (name) => page.locator('.toolbar').getByRole('button', { name, exact: false }),
  async confirmPop() {
    const btn = page.locator('.n-popconfirm__action .n-button--primary-type:visible').last()
    await btn.waitFor()
    await btn.click()
  },
  async selectOption(selectLocator, text, typed) {
    await selectLocator.click()
    if (typed) await page.keyboard.type(typed)
    const menu = page.locator('.n-base-select-menu:visible').last()
    await menu.waitFor()
    await menu.locator('.n-base-select-option', { hasText: text }).first().click()
  },
  async toasts() {
    return (await page.locator('.n-message').allInnerTexts()).join(' | ')
  },
  async waitToast(re, timeout = 6000) {
    return until(async () => {
      const t = await this.toasts()
      return re.test(t) ? t : false
    }, `toast ${re}`, timeout)
  },
  modal: () => page.locator('.n-modal-container .n-card, .n-modal-container .n-dialog').last(),
})

// ---------- registry ----------
// App bugs already reported: other tests filter these console errors out so they still
// test their own feature; the tests that reproduce each bug run with { strict: true }.
// App bugs whose console errors other tests may ignore until they are fixed (none now).
export const KNOWN_BUGS = []

// After a failure, close whatever dialog is left open so the next test starts clean.
async function recover(page) {
  for (let i = 0; i < 3; i++) {
    const btn = page.locator('.n-modal-container .n-button:visible', { hasText: /^(取消|Cancel|關閉|Close)$/ }).last()
    if (await btn.count()) await btn.click({ timeout: 2000 }).catch(() => {})
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(200)
  }
}

const tests = []
export function test(group, name, fn, opts = {}) {
  tests.push({ group, name, fn, opts })
}
export async function runAll(filter) {
  const results = []
  for (const t of tests) {
    const id = `${t.group} › ${t.name}`
    // 01 basics opens the shared page every other spec uses, so it always runs
    if (filter && !t.group.startsWith('01') && !filter.some((f) => id.toLowerCase().includes(f.toLowerCase()))) continue
    const t0 = Date.now()
    let status = 'PASS'
    let detail = ''
    try {
      takeErrors()
      await Promise.race([
        t.fn(),
        new Promise((_, rej) => setTimeout(() => rej(new Error(`test timed out after ${t.opts.timeout ?? 60000} ms`)), t.opts.timeout ?? 60000)),
      ])
      const allow = [...(t.opts.allowErrors ?? []), ...(t.opts.strict ? [] : KNOWN_BUGS)]
      const errs = takeErrors().filter((e) => !allow.some((re) => re.test(e)))
      if (errs.length) {
        status = 'FAIL'
        detail = `page errors: ${[...new Set(errs)].slice(0, 4).join(' || ')}`
      }
    } catch (e) {
      status = 'FAIL'
      detail = (e instanceof AssertionError ? e.message : e.stack?.split('\n').slice(0, 3).join(' ') ?? String(e)).slice(0, 400)
      takeErrors()
      for (const p of pages) await shot(p, `FAIL-${t.group}-${t.name}`)
      for (const p of pages) await recover(p)
    }
    const ms = Date.now() - t0
    results.push({ id, status, ms, detail })
    console.log(`${status === 'PASS' ? '✔' : '✘'} ${id} (${(ms / 1000).toFixed(1)}s)${detail ? `\n    ${detail}` : ''}`)
  }
  return results
}

// One 'stats' message from the shared stats stream (Node 22 has a global WebSocket).
export function statsOnce(host, skip = 1) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/api/hosts/${host}/stats`)
    let seen = 0
    const timer = setTimeout(() => {
      ws.close()
      reject(new Error('no stats message within 8 s'))
    }, 8000)
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.type !== 'stats' || ++seen <= skip) return
      clearTimeout(timer)
      ws.close()
      resolve(m)
    }
    ws.onerror = () => reject(new Error('stats websocket error'))
  })
}
