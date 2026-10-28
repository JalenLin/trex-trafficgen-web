// Session export, then import with port remapping.
import fs from 'node:fs'
import path from 'node:path'
import { OUT, assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '13 session'
const demo = hostApi('demo')
let file

test(G, 'export session: one JSON with every port, streams and settings', async () => {
  const page = shared.page
  await ui(page).pickHost('Demo')
  await ui(page).rows().first().waitFor()
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '匯出 session' }).click()])
  file = path.join(OUT, 'e2e-session.json')
  await dl.saveAs(file)
  const s = JSON.parse(fs.readFileSync(file, 'utf8'))
  eq(s.ports.length, 8, 'eight ports in the file')
  eq(s.ports[2].streams.map((x) => x.name), ['A', 'B'], 'port 2 streams')
  assert(s.ports[2].settings || s.ports[2].layer || s.ports[2].config, 'port settings included')
})

test(G, 'import: map port 2 → port 5, settings box unticks itself, streams land on port 5', async () => {
  const page = shared.page
  const u = ui(page)
  await page.locator('input[type=file][accept*=json]').setInputFiles(file)
  const m = page.locator('.n-modal-container .n-card', { hasText: '匯入 session' })
  await m.locator('.n-data-table').waitFor()
  const settings = m.locator('.n-checkbox', { hasText: '套用 L2/L3' })
  assert((await settings.getAttribute('class')).includes('checked'), 'settings ticked before remapping')
  const rows = m.locator('tbody tr')
  const n = await rows.count()
  for (let i = 0; i < n; i++) {
    const sel = rows.nth(i).locator('.n-select')
    await sel.click()
    const menu = page.locator('.n-base-select-menu:visible').last()
    await menu.waitFor()
    await menu.evaluate((el) => el.querySelectorAll('*').forEach((e) => e.scrollHeight > e.clientHeight && (e.scrollTop = 0)))
    await page.waitForTimeout(150)
    await menu.locator('.n-base-select-option', { hasText: i === 2 ? /^Port 5/ : '略過' }).first().click()
    await page.waitForTimeout(150)
  }
  await until(async () => !(await settings.getAttribute('class')).includes('checked'), 'settings unticked after remapping')
  await shot(page, 'session-import')
  await m.getByRole('button', { name: /匯入 1 個 port/ }).click()
  await m.locator('.rep').first().waitFor()
  assert(/Port 2 → Port 5/.test(await m.innerText()), 'result lists the mapping')
  eq((await demo.get('/ports/5/streams')).map((s) => s.name), ['A', 'B'], 'streams imported to port 5')
  await m.getByRole('button', { name: '關閉' }).click()
  void u
})
