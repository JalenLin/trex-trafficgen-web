// Load, host list, connect / disconnect, unreachable host.
import { BASE, assert, eq, hostApi, openPage, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '01 basics'
let page, u

test(G, 'page loads with header, host list and overview entry', async () => {
  page = await openPage()
  u = ui(page)
  await page.goto(BASE)
  await page.locator('.list .item').first().waitFor()
  eq(await page.title() !== '', true, 'document title set')
  const hosts = (await page.locator('.list .item:not(.overview)').allInnerTexts()).map((s) => s.split('\n')[0].trim())
  eq(hosts, ['Demo', 'Lab B', 'Far TRex'], 'host list')
  assert(await page.locator('.list .item.overview, .list .overview').count(), 'overview entry present')
  assert(await page.locator('.header .theme').isVisible(), 'theme select')
  assert(await page.locator('.header .lang').isVisible(), 'language select')
  await shot(page, 'basics-load')
})

test(G, 'unreachable host shows the connection error and reason', async () => {
  await u.pickHost('Far TRex')
  await page.locator('.panel').getByRole('button', { name: '連線' }).click()
  const alert = page.locator('.panel .n-alert', { hasText: '連線失敗' })
  await alert.waitFor({ timeout: 20000 })
  const text = await alert.innerText()
  assert(/nonexistent|client|not found|No such/i.test(text), `alert explains why: ${text.replace(/\s+/g, ' ').slice(0, 160)}`)
  assert(await page.locator('.panel .n-tag', { hasText: '未連線' }).count(), 'shows 未連線 tag')
  await shot(page, 'basics-unreachable')
}, { allowErrors: [/Failed to load resource|50\d|status of 4\d\d/i], timeout: 40000 })

test(G, 'connect and disconnect a mock host', async () => {
  await u.pickHost('Lab B')
  await page.locator('.panel').getByRole('button', { name: '連線' }).click()
  await page.locator('.panel .n-tag', { hasText: '已連線' }).waitFor()
  await u.rows().first().waitFor()
  eq(await u.rows().count(), 4, 'Lab B has 4 ports')
  eq((await hostApi('lab-b').get('')).connected, true, 'backend says connected')
  await page.locator('.panel').getByRole('button', { name: '中斷連線' }).click()
  await page.locator('.panel .n-tag', { hasText: '未連線' }).waitFor()
  eq((await hostApi('lab-b').get('')).connected, false, 'backend says disconnected')
  assert(!(await page.locator('.toolbar').count()), 'toolbar hidden when disconnected')
})

test(G, 'connect Demo for the following tests: 8 ports, 0/1 owned by someone else', async () => {
  await u.pickHost('Demo')
  await page.locator('.panel').getByRole('button', { name: '連線' }).click()
  await u.rows().first().waitFor()
  eq(await u.rows().count(), 8, 'Demo has 8 ports')
  const r0 = await u.row(0).innerText()
  assert(/TX|送/.test(r0) && !/我/.test(r0), `port 0 transmitting and not mine: ${r0.replace(/\s+/g, ' ')}`)
  await until(async () => (await u.row(0).locator('.rate').innerText()).trim().length > 0, 'rate shown on port 0 row')
  shared.page = page
  await shot(page, 'basics-demo')
})
