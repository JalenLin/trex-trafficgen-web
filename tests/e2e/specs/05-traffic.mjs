// Toolbar traffic control and per-stream control while transmitting.
import { assert, eq, hostApi, shot, statsOnce, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '05 traffic'
const demo = hostApi('demo')
const status = async (p) => (await demo.get('/ports'))[p].status
const txPps = async (p) => (await statsOnce('demo', 2)).ports[p].tx_pps

async function select(ports) {
  const u = ui(shared.page)
  await u.uncheckAll()
  for (const p of ports) await u.check(p)
  return u
}
async function setMult(page, v) {
  const inp = page.locator('.toolbar .n-auto-complete input')
  await inp.fill(v)
  await page.keyboard.press('Escape')
}

test(G, 'Start with multiplier 2 on ports 2-3, rates follow the streams', async () => {
  const page = shared.page
  const u = await select([2, 3])
  await setMult(page, '2')
  await u.start()
  await until(async () => (await status(2)) === 'TRANSMITTING' && (await status(3)) === 'TRANSMITTING', 'ports 2, 3 transmitting')
  const pps = await txPps(2)
  assert(Math.abs(pps - 60000) < 6000, `port 2 tx ≈ 2 × (10k + 20k) pps, got ${pps}`)
  await until(async () => (await u.row(2).locator('.n-tag').first().innerText()).includes('TX'), 'row tag TX')
  await shot(page, 'traffic-running')
})

test(G, 'Pause and Resume', async () => {
  const page = shared.page
  const u = ui(page)
  await u.tb(/^暫停$/).click()
  await until(async () => (await status(2)) === 'PAUSE', 'paused')
  await u.tb(/^繼續$/).click()
  await until(async () => (await status(2)) === 'TRANSMITTING', 'resumed')
})

test(G, 'Change rate to 50% while transmitting', async () => {
  const page = shared.page
  const u = ui(page)
  await setMult(page, '0.5')
  await u.tb(/^調整$/).click()
  await until(async () => Math.abs((await txPps(2)) - 15000) < 2000, 'port 2 tx ≈ 15 kpps after ×0.5')
})

test(G, 'per-stream pause, rate and resume in the Streams tab', async () => {
  const page = shared.page
  const u = ui(page)
  await u.focus(2)
  await u.tab('Streams')
  const rowA = page.locator('.n-data-table-tbody tr').nth(0)
  await rowA.getByRole('button', { name: '暫停' }).waitFor()
  assert(await page.getByText('送流中可以個別暫停').count(), 'experimental-feature note shown')
  await rowA.getByRole('button', { name: '暫停' }).click()
  await until(async () => (await demo.get('/ports/2/streams/state')).paused.length === 1, 'one stream paused')
  await until(async () => (await rowA.innerText()).includes('已暫停'), 'row shows 已暫停')
  const rowB = page.locator('.n-data-table-tbody tr').nth(1)
  var lastStates = await demo.get('/ports/2/streams/state')
  await rowB.getByRole('button', { name: '調速' }).click()
  const pop = page.locator('.n-popover:visible')
  await pop.locator('input').fill('40kpps')
  await pop.getByRole('button', { name: '套用' }).click()
  let seen
  await until(async () => Math.abs((seen = await txPps(2)) - 40000) < 4000, () => `port 2 ≈ 40 kpps with A paused, B at 40k (tx ${seen}, states ${JSON.stringify(lastStates)})`)
  await rowA.getByRole('button', { name: '繼續' }).click()
  await until(async () => (await demo.get('/ports/2/streams/state')).paused.length === 0, 'resumed')
  await shot(page, 'traffic-per-stream')
})

test(G, 'Start while running asks to restart', async () => {
  const page = shared.page
  const u = ui(page)
  await setMult(page, '')
  await u.tb(/開始/).click()
  await page.locator('.n-popconfirm', { hasText: '會先停止再用目前的 streams 重新開始' }).waitFor()
  await u.confirmPop()
  await until(async () => Math.abs((await txPps(2)) - 30000) < 3000, 'restarted at ×1 (30 kpps)')
})

test(G, 'Stop', async () => {
  const u = ui(shared.page)
  await u.tb(/停止/).click()
  await until(async () => (await status(2)) === 'IDLE' && (await status(3)) === 'IDLE', 'stopped')
  eq(await u.tb(/^暫停$/).isDisabled(), true, 'Pause disabled when idle')
})

test(G, 'duration: traffic stops by itself after 2 s', async () => {
  const page = shared.page
  const u = ui(page)
  const dur = page.locator('.toolbar .n-input-number input')
  await dur.fill('2')
  await dur.blur()
  await u.start()
  await until(async () => (await status(2)) === 'TRANSMITTING', 'started')
  await until(async () => (await status(2)) === 'IDLE', 'stopped on its own', 8000)
  await dur.fill('')
  await dur.blur()
})

test(G, 'Reset asks for confirmation, stops and removes streams from TRex, keeps the ports', async () => {
  const page = shared.page
  const u = ui(page)
  await u.start()
  await until(async () => (await status(2)) === 'TRANSMITTING', 'started')
  await u.tb(/重設/).click()
  await page.locator('.n-popconfirm', { hasText: '清掉 TRex 上的 streams' }).waitFor()
  await u.confirmPop()
  await until(async () => (await status(2)) === 'IDLE', 'idle after reset')
  const st = await demo.get('/ports/2/streams/state')
  eq(st.on_trex.length, 0, 'no streams left on TRex')
  const p2 = (await demo.get('/ports'))[2]
  eq(p2.acquired, true, 'port 2 still mine')
  eq((await demo.get('/ports/2/streams')).length, 2, 'GUI streams kept')
})
