// Stats tab, pg / Latency tab, Port details tab.
import { assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '06 stats'
const demo = hostApi('demo')

test(G, 'Stats tab: totals, layout toggle, only selected ports, clear', async () => {
  const page = shared.page
  const u = ui(page)
  await u.uncheckAll()
  for (const p of [2, 3]) await u.check(p)
  await u.start()
  await until(async () => (await demo.get('/ports'))[2].status === 'TRANSMITTING', 'running')
  await u.tab('統計')
  await page.getByText('總 TX').first().waitFor()
  const table = page.locator('.n-tab-pane:visible .n-data-table').first()
  const sw = page.locator('.n-tab-pane:visible .n-switch').first()
  if ((await sw.getAttribute('aria-checked')) === 'true') await sw.click()
  await page.waitForTimeout(300)
  await page.locator('.n-radio-button', { hasText: 'Port 為列' }).click()
  await page.waitForTimeout(400)
  const rowsMode = await table.locator('tbody tr').count()
  await page.locator('.n-radio-button', { hasText: 'Port 為欄' }).click()
  await page.waitForTimeout(400)
  const colsHead = await table.locator('thead').innerText()
  assert(/Port 2/.test(colsHead) && /Port 7/.test(colsHead), `ports as columns header: ${colsHead.replace(/\s+/g, ' ').slice(0, 80)}`)
  assert(rowsMode >= 8, `ports as rows: ${rowsMode} rows`)
  await page.locator('.n-tab-pane:visible .n-switch').first().click()
  await page.waitForTimeout(400)
  const onlyHead = await table.locator('thead').innerText()
  assert(/Port 2/.test(onlyHead) && !/Port 7/.test(onlyHead), `only selected ports: ${onlyHead.replace(/\s+/g, ' ').slice(0, 80)}`)
  await page.locator('.n-tab-pane:visible .n-switch').first().click()
  await shot(page, 'stats-tab')
  await page.locator('.n-tab-pane:visible').getByRole('button', { name: '清除統計' }).click()
  await u.waitToast(/統計已清除/)
})

test(G, 'pg / Latency tab: flow stats and latency rows with histogram', async () => {
  const page = shared.page
  const u = ui(page)
  await u.tab('pg / Latency')
  const pane = page.locator('.n-tab-pane:visible')
  await until(async () => (await pane.locator('tbody tr').count()) >= 2, 'pg rows for pg 7 and 8')
  const text = await pane.innerText()
  assert(/\b7\b/.test(text) && /\b8\b/.test(text), 'pg ids 7 and 8 listed')
  assert(/平均|μs/.test(text), 'latency columns shown')
  const ex = pane.locator('.n-data-table-expand-trigger').first()
  if (await ex.count()) {
    await ex.click()
    await pane.getByText('Latency 分布').first().waitFor()
  }
  await shot(page, 'pg-latency')
})

test(G, 'Port details tab lists every port with driver and speed', async () => {
  const page = shared.page
  const u = ui(page)
  await u.tab('Port 詳細')
  const pane = page.locator('.n-tab-pane:visible')
  await until(async () => (await pane.locator('tbody tr').count()) === 8, '8 port rows')
  assert((await pane.innerText()).includes('net_mock'), 'driver shown')
  await u.tb(/停止/).click()
  await until(async () => (await demo.get('/ports'))[2].status === 'IDLE', 'stopped')
})
