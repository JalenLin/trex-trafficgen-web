// Namespace nodes in Port settings: service mode, validation, add, list, remove.
import { assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '10 namespace'
const demo = hostApi('demo')

const ns = () => shared.page.locator('.form').last()
const field = (label) =>
  ns().locator('.n-form-item').filter({ has: shared.page.locator('.n-form-item-label', { hasText: new RegExp(`^\\s*${label}\\s*$`) }) })

test(G, 'service mode radio switches the port mode', async () => {
  const page = shared.page
  const u = ui(page)
  await u.focus(4)
  await u.tab('Port 設定')
  await page.getByText('Namespace 節點（模擬主機）').scrollIntoViewIfNeeded()
  const radio = page.locator('.n-radio-group', { has: page.locator('.n-radio-button', { hasText: '過濾' }) })
  await radio.locator('.n-radio-button', { hasText: '全部' }).click()
  await until(async () => (await demo.get('/ports'))[4].layer.service === 'on', 'service on')
  await radio.locator('.n-radio-button', { hasText: '過濾' }).click()
  await until(async () => (await demo.get('/ports'))[4].layer.service === 'filtered', 'service filtered')
})

test(G, 'validation: bad MAC, bad VLAN, IPv4 without gateway disable Add', async () => {
  const page = shared.page
  const add = ns().getByRole('button', { name: '新增', exact: true })
  const mac = field('MAC').locator('input')
  const orig = await mac.inputValue()
  assert(/^02(:[0-9a-f]{2}){5}$/.test(orig), `random locally administered MAC prefilled: ${orig}`)
  await mac.fill('zz:zz')
  await field('MAC').getByText('MAC 格式應為').waitFor()
  eq(await add.isDisabled(), true, 'disabled for bad MAC')
  await field('MAC').getByRole('button', { name: '隨機' }).click()
  await field('VLAN').locator('input').fill('5000')
  await field('VLAN').getByText('VLAN 為 1~4094').waitFor()
  eq(await add.isDisabled(), true, 'disabled for bad VLAN')
  await field('VLAN').locator('input').fill('100')
  await field('IPv4').locator('input').fill('10.4.0.10')
  await field('Gateway').getByText('設定 IPv4 時需要 gateway').waitFor()
  eq(await add.isDisabled(), true, 'disabled without gateway')
  await field('Gateway').locator('input').fill('10.4.0.1')
  eq(await add.isDisabled(), false, 'enabled when valid')
  void page
})

test(G, 'add two nodes, list them, remove one, remove all', async () => {
  const page = shared.page
  const u = ui(page)
  const add = ns().getByRole('button', { name: '新增', exact: true })
  await add.click()
  await u.waitToast(/已新增節點/)
  await field('IPv4').locator('input').fill('10.4.0.11')
  await add.click()
  await until(async () => (await demo.get('/ports/4/ns')).length === 2, 'two nodes on backend')
  const table = page.locator('.n-data-table', { hasText: 'IPv4' }).last()
  await until(async () => (await table.locator('tbody tr').count()) === 2, 'two rows listed')
  assert((await table.innerText()).includes('10.4.0.10') && (await table.innerText()).includes('100'), 'row shows IP and VLAN')
  await shot(page, 'namespace-nodes')
  await table.locator('tbody tr').first().getByRole('button', { name: '移除' }).click()
  await u.confirmPop()
  await until(async () => (await demo.get('/ports/4/ns')).length === 1, 'one node left')
  // add one more to exercise "remove all"
  await add.click()
  await until(async () => (await demo.get('/ports/4/ns')).length === 2, 'two nodes again')
  await page.getByRole('button', { name: '全部移除' }).click()
  await u.confirmPop()
  await until(async () => (await demo.get('/ports/4/ns')).length === 0, 'all removed')
  const radio = page.locator('.n-radio-group', { has: page.locator('.n-radio-button', { hasText: '過濾' }) })
  await radio.locator('.n-radio-button', { hasText: '關閉' }).click()
  await until(async () => (await demo.get('/ports'))[4].layer.service === 'off', 'service off again')
})
