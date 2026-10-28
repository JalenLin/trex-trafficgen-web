// RFC 2544: configure a short run, refusal while running, results, export, history.
import fs from 'node:fs'
import path from 'node:path'
import { OUT, assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '11 rfc2544'
const demo = hostApi('demo')
const pane = () => shared.page.locator('.n-tab-pane:visible')
const item = (label) =>
  pane().locator('.rfc-form .n-form-item').filter({ has: shared.page.locator('.n-form-item-label', { hasText: new RegExp(`^\\s*${label}\\s*$`) }) })
async function num(label, v) {
  const inp = item(label).locator('.n-input-number input').first()
  await inp.fill(String(v))
  await inp.blur()
}

test(G, 'configure: pair 2→3, one way, 512 B, all four tests, 1 s trials', async () => {
  const page = shared.page
  const u = ui(page)
  await u.uncheckAll()
  await u.tab('RFC 2544')
  const form = pane().locator('.rfc-form')
  await form.getByRole('button', { name: '恢復預設設定' }).click()
  const row = form.locator('.pair-row').first()
  await u.selectOption(row.locator('.n-select').nth(0), /^Port 2（/)
  await u.selectOption(row.locator('.n-select').nth(1), /^Port 3（/)
  const bi = item('雙向').locator('.n-switch')
  if ((await bi.getAttribute('aria-checked')) === 'true') await bi.click()
  // sizes: drop every tag, then type a custom size
  const sizes = item('封包大小').locator('.n-select')
  await sizes.click()
  for (let i = 0; i < 12; i++) await page.keyboard.press('Backspace')
  await page.keyboard.type('512')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await until(async () => (await sizes.locator('.n-tag').allInnerTexts()).join(',') === '512', 'sizes = 512 only')
  for (const name of ['封包遺失率', '背對背']) {
    const cb = item('測試項目').locator('.n-checkbox', { hasText: name })
    if (!(await cb.getAttribute('class')).includes('checked')) await cb.click()
  }
  await num('每次試驗時間', 1)
  await num('解析度', 10)
  await num('遺失率步進', 50)
  await num('最長突發', 0.05)
  await item('預估時間').locator('.help').first().waitFor()
  await shot(page, 'rfc-form')
})

test(G, 'run: start, other traffic on its ports is refused, runs to completion', async () => {
  const page = shared.page
  const u = ui(page)
  await pane().getByRole('button', { name: '開始測試' }).click()
  await until(async () => (await demo.get('/rfc2544'))?.state === 'running', 'test running')
  await pane().locator('.rfc-run .log-row').first().waitFor()
  // the toolbar can't start port 2 while the test uses it
  await u.check(2)
  // the Start button flips between plain and "restart?" while trials run: retry until refused
  await until(async () => {
    await u.start()
    return /RFC 2544/.test(await u.toasts().catch(() => ''))
  }, 'start refused with an RFC 2544 message', 15000, 1500)
  await u.uncheckAll()
  eq((await demo.get('/rfc2544')).state, 'running', 'still running after the refused start')
  await shot(page, 'rfc-running')
  try {
    await until(async () => (await demo.get('/rfc2544')).state !== 'running', 'test finished', 170000, 1000)
  } finally {
    if ((await demo.get('/rfc2544'))?.state === 'running') await demo.post('/rfc2544/stop')
  }
  const job = await demo.get('/rfc2544')
  eq(job.state, 'done', `final state (error: ${job.error})`)
  for (const k of ['throughput', 'latency', 'frame_loss', 'back_to_back']) assert(job.results[k]?.length, `${k} results present`)
}, { timeout: 200000, allowErrors: [/status of 4\d\d/] })

test(G, 'results: tables, chart and JSON / CSV export', async () => {
  const page = shared.page
  const res = pane().locator('.rfc-results')
  await res.waitFor()
  for (const title of ['吞吐量', '延遲', '封包遺失率', '背對背']) await res.locator('.test-title', { hasText: title }).waitFor()
  assert(await res.locator('svg').count(), 'chart drawn')
  const tp = await res.locator('.test').first().innerText()
  assert(/512/.test(tp) && /%/.test(tp), `throughput row for 512 B: ${tp.replace(/\s+/g, ' ').slice(0, 120)}`)
  await shot(page, 'rfc-results')
  for (const [btn, ext] of [['匯出 JSON', 'json'], ['匯出 CSV', 'csv']]) {
    const [dl] = await Promise.all([page.waitForEvent('download'), res.getByRole('button', { name: btn }).click()])
    const f = path.join(OUT, `e2e-rfc.${ext}`)
    await dl.saveAs(f)
    const body = fs.readFileSync(f, 'utf8')
    if (ext === 'json') assert(JSON.parse(body).results?.throughput?.length, 'JSON has throughput')
    else assert(body.split('\n').length > 2 && /512/.test(body), 'CSV has rows')
  }
})

test(G, 'history: listed, view, delete with confirmation', async () => {
  const page = shared.page
  const u = ui(page)
  const hist = pane().locator('.n-collapse-item', { hasText: '歷史紀錄' }).last()
  await until(async () => (await hist.locator('tbody tr').count()) >= 1, 'history row')
  await hist.locator('tbody tr').first().getByRole('button', { name: /檢視|查看|View/ }).click()
  await pane().locator('div.viewing').waitFor()
  const n0 = (await demo.get('/rfc2544/history')).length
  await hist.locator('tbody tr').first().getByRole('button', { name: '刪除' }).click()
  await u.confirmPop()
  await until(async () => (await demo.get('/rfc2544/history')).length === n0 - 1, 'history entry deleted')
})
