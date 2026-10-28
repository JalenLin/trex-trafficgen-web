// Monitor tab: rate chart, legend, table, event log, advanced monitoring opt-in.
import { assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '07 monitor'
const demo = hostApi('demo')

test(G, 'rate chart draws lines; legend toggles a line; table view', async () => {
  const page = shared.page
  const u = ui(page)
  await u.uncheckAll()
  for (const p of [2, 3]) await u.check(p)
  await u.start()
  await u.tab('監控')
  const pane = page.locator('.n-tab-pane:visible')
  await until(async () => (await pane.locator('.plot svg path').count()) >= 2, 'chart has lines', 10000)
  const item = pane.locator('.legend .item').first()
  await item.click()
  await until(async () => (await item.getAttribute('class')).includes('off'), 'legend item off')
  await item.click()
  await pane.locator('.table-toggle .n-switch').click()
  await until(async () => (await pane.locator('.n-collapse-item').first().locator('table').count()) > 0, 'table view')
  await pane.locator('.table-toggle .n-switch').click()
  await pane.locator('.n-radio-button', { hasText: '各 port TX' }).click()
  await pane.locator('.n-radio-button', { hasText: /^5 分鐘$/ }).click()
  await shot(page, 'monitor-chart')
})

test(G, 'event log lists GUI actions and filters work', async () => {
  const page = shared.page
  const pane = page.locator('.n-tab-pane:visible')
  const ev = pane.locator('.n-collapse-item').nth(1)
  await until(async () => (await ev.locator('tbody tr').count()) > 3, 'events listed')
  const all = await ev.innerText()
  assert(/開始送流/.test(all) && /has started/.test(all), `has GUI start and TRex events: ${all.replace(/\s+/g, ' ').slice(0, 160)}`)
  assert(/127\.0\.0\.1/.test(all), 'source IP shown')
  await ev.locator('.n-radio-button', { hasText: 'TRex 事件' }).click()
  await page.waitForTimeout(300)
  const trexOnly = await ev.locator('tbody').innerText()
  assert(!/開始送流/.test(trexOnly), 'TRex filter hides GUI actions')
  await ev.locator('.n-radio-button', { hasText: '只看警告' }).click()
  await page.waitForTimeout(300)
  const warn = await ev.locator('tbody').innerText()
  assert(!/開始送流 Port/.test(warn), 'warning filter hides normal actions')
  await ev.locator('.n-radio-button', { hasText: '全部' }).click()
})

test(G, 'advanced monitoring is off by default, warns, turns on CPU and xstats, turns off', async () => {
  const page = shared.page
  const pane = page.locator('.n-tab-pane:visible')
  eq(await demo.get('/monitor').then((m) => !!(m.cpu || m.xstats)), false, 'off by default')
  await pane.locator('.n-collapse-item__header', { hasText: '進階監控' }).click()
  await pane.locator('.n-alert', { hasText: '會增加 TRex 的負擔' }).waitFor()
  await pane.locator('.opt', { hasText: '每核心' }).locator('.n-switch').click()
  await pane.locator('.opt', { hasText: 'xstats' }).locator('.n-switch').click()
  await until(async () => {
    const m = await demo.get('/monitor')
    return m.cpu && m.xstats
  }, 'backend monitor on')
  await until(async () => (await pane.locator('.core').count()) > 0, 'cores shown', 10000)
  await shot(page, 'monitor-extra')
  await pane.locator('.opt', { hasText: '每核心' }).locator('.n-switch').click()
  await pane.locator('.opt', { hasText: 'xstats' }).locator('.n-switch').click()
  await until(async () => {
    const m = await demo.get('/monitor')
    return !m.cpu && !m.xstats
  }, 'backend monitor off')
  await ui(page).tb(/停止/).click()
})
