// Acquire, force acquire (with confirmation), release; buttons follow ownership.
import { assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '02 acquire'
const demo = hostApi('demo')
const mine = async () => (await demo.get('/ports')).filter((p) => p.acquired).map((p) => p.id)

test(G, 'toolbar buttons are disabled until ports are acquired', async () => {
  const page = shared.page
  const u = ui(page)
  await u.uncheckAll()
  await u.check(2)
  await u.check(3)
  eq(await u.tb(/^取得$/).isDisabled(), false, 'Acquire enabled for free ports')
  eq(await u.tb(/釋放/).isDisabled(), true, 'Release disabled')
  eq(await u.tb(/開始/).isDisabled(), true, 'Start disabled')
  eq(await u.tb(/重設/).isDisabled(), true, 'Reset disabled')
  assert(await page.locator('.toolbar .hint', { hasText: '先取得 port 才能送流' }).count(), 'hint asks to acquire first')
})

test(G, 'acquire ports 2-7 and release one', async () => {
  const page = shared.page
  const u = ui(page)
  for (const i of [4, 5, 6, 7]) await u.check(i)
  await u.tb(/^取得$/).click()
  await until(async () => (await mine()).length === 6, 'ports 2-7 acquired')
  await until(async () => (await u.row(2).innerText()).includes('我'), 'row shows 我')
  eq(await u.tb(/開始/).isDisabled(), false, 'Start enabled after acquire')
  await u.uncheckAll()
  await u.check(7)
  await u.tb(/釋放/).click()
  await until(async () => !(await mine()).includes(7), 'port 7 released')
  eq(await mine(), [2, 3, 4, 5, 6], 'ports still mine')
})

test(G, 'force acquire asks for confirmation and takes port 0 from its owner', async () => {
  const page = shared.page
  const u = ui(page)
  await u.uncheckAll()
  await u.check(0)
  await u.tb(/強制取得/).click()
  const pop = page.locator('.n-popconfirm', { hasText: '強制取得會中斷對方的測試' })
  await pop.waitFor()
  await shot(page, 'acquire-force-confirm')
  // cancel first: nothing happens
  await page.locator('.n-popconfirm__action .n-button:not(.n-button--primary-type):visible').last().click()
  await page.waitForTimeout(300)
  assert(!(await mine()).includes(0), 'cancel keeps port 0 with its owner')
  await u.tb(/強制取得/).click()
  await u.confirmPop()
  await until(async () => (await mine()).includes(0), 'port 0 force-acquired')
  // give it back by releasing (mock keeps its traffic running? whatever; we only need it gone from us)
  await u.tb(/釋放/).click()
  await until(async () => !(await mine()).includes(0), 'port 0 released')
  await u.uncheckAll()
})
