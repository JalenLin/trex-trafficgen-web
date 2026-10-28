// Overview & port map: host cards, cross-host pairs, port map, layout at several widths.
import { BASE, assert, eq, hostApi, openPage, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '12 overview'
const demo = hostApi('demo')
const labb = hostApi('lab-b')

test(G, 'host cards for every host; connect Lab B from its card; Open goes to the host', async () => {
  const page = shared.page
  await page.locator('.list .item.overview').click()
  await page.locator('.cards .card').first().waitFor()
  eq(await page.locator('.cards .card').count(), 3, 'three host cards')
  const lab = page.locator('.cards .card', { hasText: 'Lab B' })
  await lab.getByRole('button', { name: '連線' }).click()
  await until(async () => (await labb.get('')).connected, 'Lab B connected from the card')
  await lab.locator('tbody tr').first().waitFor()
  eq(await lab.locator('tbody tr').count(), 4, 'Lab B card lists 4 ports')
  const far = page.locator('.cards .card', { hasText: 'Far TRex' })
  assert((await far.innerText()).includes('未連線'), 'Far TRex card says not connected')
  await page.locator('.cards .card', { hasText: 'Demo' }).getByRole('button', { name: /開啟/ }).click()
  await page.locator('.panel').getByText('Demo').first().waitFor()
  await page.locator('.list .item.overview').click()
  await page.locator('.cards .card').first().waitFor()
  await shot(page, 'overview-cards')
})

test(G, 'cross-host pair Demo p2 ↔ Lab B p0: sent / received / loss while running', async () => {
  const page = shared.page
  const u = ui(page)
  await labb.post('/ports/acquire', { ports: [0, 1], force: true })
  const form = page.locator('.n-card', { hasText: '跨主機 port 配對' }).locator('.form')
  const sel = form.locator('.n-select')
  await u.selectOption(sel.nth(0), 'Demo')
  await u.selectOption(sel.nth(1), /^Port 2/)
  await u.selectOption(sel.nth(2), 'Lab B')
  await u.selectOption(sel.nth(3), /^Port 0/)
  await form.getByRole('button', { name: '加入配對' }).click()
  const card = page.locator('.n-card', { hasText: '跨主機 port 配對' })
  await until(async () => (await card.locator('tbody tr').count()) >= 2, 'two direction rows')
  await demo.post('/traffic/start', { ports: [2], force: true })
  await until(async () => /送流中/.test(await card.locator('tbody').innerText()), 'running direction marked 送流中')
  await shot(page, 'overview-pairs')
  await demo.post('/traffic/stop', { ports: [2] })
  await card.getByRole('button', { name: '清除相關主機的統計' }).click()
  await u.confirmPop()
  await u.waitToast(/已清除/)
  await card.locator('tbody tr').first().getByRole('button', { name: '移除' }).click()
  await until(async () => !(await card.locator('tbody tr').count()) || /還沒有配對/.test(await card.innerText()), 'pair removed')
})

test(G, 'port map renders nodes and links, tooltip on hover, table view', async () => {
  const page = shared.page
  const map = page.locator('.portmap-root')
  await map.locator('.node.port').first().waitFor()
  assert((await map.locator('.node.port').count()) >= 12, 'Demo + Lab B port nodes')
  assert((await map.locator('.edges .edge').count()) > 0, 'links drawn')
  await map.locator('.node.port').nth(2).hover()
  await map.locator('.tooltip').waitFor()
  assert((await map.locator('.tooltip .tip-title').innerText()).length > 0, 'tooltip title')
  await map.getByRole('button', { name: '以表格顯示' }).click()
  await until(async () => (await map.locator('table').count()) > 0, 'table view')
  await map.locator('.bar .n-button').click()
  await map.locator('.node.port').first().waitFor()
  await shot(page, 'overview-portmap')
})

test(G, 'overview layout: no horizontal page overflow at 1920 / 1440 / 1024 / 390', async () => {
  for (const width of [1920, 1440, 1024, 390]) {
    const p = await openPage({ width, height: 900 })
    await p.goto(BASE)
    await p.locator('.list .item, .compact .citem').first().waitFor()
    const item = p.locator('.list .item.overview, .compact .citem').first()
    await item.click()
    await p.locator('.cards .card').first().waitFor()
    await p.waitForTimeout(1200)
    const over = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    await shot(p, `overview-${width}`)
    await p.context().close()
    assert(over <= 1, `${width}px: page overflows by ${over}px`)
  }
})
