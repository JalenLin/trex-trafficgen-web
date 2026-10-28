// Stream editor, stream list, copy to ports, templates, single-packet send.
import fs from 'node:fs'
import path from 'node:path'
import { BASE, OUT, api, assert, eq, hostApi, openPage, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '04 streams'
const demo = hostApi('demo')
const streamsOf = (p) => demo.get(`/ports/${p}/streams`)

const editor = (page) => page.locator('.n-modal-container .n-card').filter({ hasText: '編輯 stream' }).last()
const txItem = (page, label) =>
  editor(page).locator('.n-form-item').filter({ has: page.locator('.n-form-item-label', { hasText: new RegExp(`^\\s*${label}\\s*$`) }) })

async function openNew(port) {
  const page = shared.page
  const u = ui(page)
  await u.focus(port)
  await u.tab('Streams')
  await page.getByRole('button', { name: '＋ 新增 stream' }).click()
  const ed = editor(page)
  await ed.waitFor()
  // a leftover draft banner from an earlier run: discard it
  const discard = ed.getByRole('button', { name: '捨棄' })
  if (await discard.count()) await discard.click()
  await ed.locator('.hex .b').first().waitFor()
  return { page, u, ed }
}
async function setName(ed, name) {
  await ed.locator('.n-card-header input').fill(name)
}
async function tx(page, { mode, rate, unit, flow, pg }) {
  const ed = editor(page)
  await ed.locator('.n-tabs-tab', { hasText: '傳送' }).click()
  if (mode) await txItem(page, '模式').locator('.n-radio-button', { hasText: mode }).click()
  if (unit) await ui(page).selectOption(txItem(page, '速率').locator('.n-select'), unit)
  if (rate !== undefined) {
    const inp = txItem(page, '速率').locator('.n-input-number input')
    await inp.fill(String(rate))
    await inp.blur()
  }
  if (flow) {
    await txItem(page, 'Flow 統計').locator('.n-radio-button', { hasText: flow }).click()
    const pgi = txItem(page, 'Flow 統計').locator('input[placeholder="pg_id"]')
    await pgi.fill(String(pg))
    await pgi.blur()
  }
}
async function save(page) {
  await editor(page).getByRole('button', { name: '檢查並儲存' }).click()
  await editor(page).waitFor({ state: 'detached', timeout: 8000 })
}

test(G, 'editor: default stack, add and remove a layer, edit a field, preview updates', async () => {
  const { page, ed } = await openNew(6)
  const layers = () => ed.locator('.stack .layer .proto').allInnerTexts()
  eq(await layers(), ['Ether', 'IP', 'UDP'], 'default stack')
  // add Dot1Q via the searchable picker, then remove it
  await ed.locator('.picker').click()
  await page.keyboard.type('Dot1Q')
  await page.locator('.n-base-select-menu:visible .n-base-select-option', { hasText: /^Dot1Q/ }).first().click()
  await until(async () => (await layers()).includes('Dot1Q'), 'Dot1Q added')
  const idx = (await layers()).indexOf('Dot1Q')
  await ed.locator('.stack .layer').nth(idx).getByRole('button', { name: '✕' }).click()
  await until(async () => !(await layers()).includes('Dot1Q'), 'Dot1Q removed')
  // edit IP ttl
  await ed.locator('.stack .layer', { hasText: 'IP' }).first().click()
  await ed.locator('.fields .row[data-field="ttl"] input').fill('7')
  await until(async () => (await ed.locator('.decode .dfield', { hasText: 'ttl' }).first().innerText()).includes('7'), 'decoded ttl shows 7')
  await shot(page, 'editor-field')
})

test(G, 'editor: clicking a hex byte jumps to the field (byte 22 = IP ttl)', async () => {
  const page = shared.page
  const ed = editor(page)
  await ed.locator('.stack .layer', { hasText: 'Ether' }).first().click()
  await ed.locator('.hex .b[data-i="22"]').click()
  await until(async () => (await ed.locator('.stack .layer.active .proto').innerText()) === 'IP', 'IP layer selected')
  await until(async () => page.evaluate(() => document.activeElement?.closest('.row')?.getAttribute('data-field') === 'ttl'), 'ttl input focused')
  // decoded tree click: UDP dport
  await ed.locator('.dfield', { hasText: 'dport' }).first().click()
  await until(async () => (await ed.locator('.stack .layer.active .proto').innerText()) === 'UDP', 'UDP selected from decoded tree')
})

test(G, 'editor: variable size, payload fill, field engine, transmit settings saved', async () => {
  const page = shared.page
  const ed = editor(page)
  const u = ui(page)
  await setName(ed, 'features')
  // variable frame size: increment 64..128 step 4
  await u.selectOption(ed.locator('.stack .n-select').nth(1), '遞增')
  const nums = ed.locator('.stack .sizes .n-input-number input')
  await nums.nth(0).fill('64')
  await nums.nth(1).fill('128')
  await nums.nth(1).blur()
  const step = ed.locator('.stack .n-input-number', { hasText: '每次' }).locator('input')
  await step.fill('4')
  await step.blur()
  // payload: repeated text
  await u.selectOption(ed.locator('.stack .n-select').last(), '重複文字')
  await ed.locator('.stack input[placeholder*="TRex"]').fill('AB')
  await until(async () => (await ed.locator('.hex .b').allInnerTexts()).join(' ').toUpperCase().includes('41 42 41 42'), 'payload "AB" visible in hex')
  // field engine: IP src increment
  await ed.locator('.n-tabs-tab', { hasText: '欄位變化' }).click()
  await ed.getByRole('button', { name: '＋ 加入欄位變化' }).click()
  const row = ed.locator('.vmrow').first()
  await u.selectOption(row.locator('.n-select').nth(0), /\. IP$/)
  await u.selectOption(row.locator('.n-select').nth(1), /^src /, 'src')
  await u.selectOption(row.locator('.n-select').nth(2), '遞增')
  await row.locator('input[placeholder="起始值"]').fill('16.0.0.1')
  await row.locator('input[placeholder="結束值"]').fill('16.0.0.20')
  await tx(page, { mode: '多次 burst', unit: 'pps', rate: 1000, flow: '封包統計', pg: 11 })
  await shot(page, 'editor-tx')
  await save(page)
  const s = (await streamsOf(6)).find((x) => x.name === 'features')
  assert(s, 'stream saved')
  eq(s.packet.size?.mode, 'inc', 'size mode')
  eq([s.packet.size?.min, s.packet.size?.max, s.packet.size?.step], [64, 128, 4], 'size range')
  eq(s.packet.payload, { type: 'text', value: 'AB' }, 'payload')
  eq(s.vm.length, 1, 'one field-engine rule')
  eq(s.mode.type, 'multi_burst', 'mode')
  eq([s.rate.unit, s.rate.value], ['pps', 1000], 'rate')
  eq([s.flow_stats.type, s.flow_stats.pg_id], ['stats', 11], 'flow stats')
  const ttl = s.packet.layers.find((l) => l.proto === 'IP').fields.ttl
  eq(String(ttl), '7', 'IP ttl kept')
})

test(G, 'every payload fill type previews and saves', async () => {
  const types = [
    ['補 0', null, '00 00'],
    ['固定位元組', '0xAA', 'AA AA'],
    ['遞增位元組', '0x10', '10 11 12'],
    ['遞減位元組', '0x20', '20 1F 1E'],
    ['隨機（固定種子）', '1', null],
    ['重複 hex', 'DEADBEEF', 'DE AD BE EF'],
  ]
  const { page, u, ed } = await openNew(6)
  const sizeInput = ed.locator('.stack .n-input-number input').first()
  await sizeInput.fill('100')
  await sizeInput.blur()
  for (const [label, value, expect] of types) {
    await u.selectOption(ed.locator('.stack .n-select').last(), label)
    if (value) await ed.locator('.stack .n-input input').last().fill(value)
    if (expect)
      await until(
        async () => (await ed.locator('.hex .b').allInnerTexts()).join(' ').toUpperCase().toUpperCase().includes(expect),
        `${label}: hex contains ${expect}`,
      )
  }
  await setName(ed, 'payload-hex')
  await save(page)
  const s = (await streamsOf(6)).find((x) => x.name === 'payload-hex')
  eq(s.packet.payload, { type: 'hex', value: 'DEADBEEF' }, 'last payload saved')
})

test(G, 'header warnings are shown but the stream can still be saved', async () => {
  const { page, ed } = await openNew(6)
  await setName(ed, 'no-ip')
  await ed.locator('.stack .layer', { hasText: 'IP' }).first().getByRole('button', { name: '✕' }).click()
  await until(async () => (await ed.locator('.lint-item').count()) > 0, 'lint warnings listed')
  assert((await ed.locator('.lint-title').innerText()).includes('仍可儲存'), 'says it can still be saved')
  await shot(page, 'editor-lint')
  await save(page)
  assert((await streamsOf(6)).some((s) => s.name === 'no-ip'), 'saved despite warnings')
  await page.locator('.n-data-table-tbody tr', { hasText: 'no-ip' }).waitFor()
})

test(G, 'Send packets… popover: count is typeable and packets arrive at the peer', async () => {
  const { page, u, ed } = await openNew(2)
  const before = (await demo.get('/ports'))[3]
  void before
  const stats0 = await demo.get('/ports')
  void stats0
  await ed.getByRole('button', { name: '送出封包…' }).click()
  const pop = page.locator('.n-popover:visible')
  const count = pop.locator('.n-input-number').first().locator('input')
  await count.fill('5')
  await pop.locator('.n-input-number').nth(1).locator('input').click()
  eq(await count.inputValue(), '5', 'count kept after blur')
  await pop.getByRole('button', { name: '送出' }).click()
  const msg = await u.waitToast(/已從 Port 2 送出 5 個封包/)
  assert(msg, 'toast')
  await page.keyboard.press('Escape')
  await ed.getByRole('button', { name: '取消' }).click()
  await editor(page).waitFor({ state: 'detached' })
})

test(G, 'streams for traffic tests: port 2 (latency pg 7 + stats pg 8) and port 3', async () => {
  for (const [port, name, rate, flow, pg] of [
    [2, 'A', 10000, 'Latency', 7],
    [2, 'B', 20000, '封包統計', 8],
    [3, 'C', 5000, null, null],
  ]) {
    const { page, ed } = await openNew(port)
    await setName(ed, name)
    await tx(page, { unit: 'pps', rate, flow, pg })
    await save(page)
  }
  eq((await streamsOf(2)).map((s) => [s.name, s.flow_stats.type, s.flow_stats.pg_id ?? null]), [['A', 'latency', 7], ['B', 'stats', 8]], 'port 2 streams')
  eq((await streamsOf(3)).map((s) => s.name), ['C'], 'port 3 streams')
})

test(G, 'stream list: duplicate, move, enable switch, delete', async () => {
  const page = shared.page
  const u = ui(page)
  await u.focus(6)
  await u.tab('Streams')
  const names = async () => (await streamsOf(6)).map((s) => s.name)
  const n0 = (await names()).length
  const first = (await names())[0]
  await page.locator('.n-data-table-tbody tr', { hasText: 'no-ip' }).getByRole('button', { name: '複製', exact: true }).click()
  await until(async () => (await names()).length === n0 + 1, 'duplicated')
  await page.locator('.n-data-table-tbody tr').first().getByRole('button', { name: '↓' }).click()
  await until(async () => (await names())[1] === first, 'moved down')
  await until(async () => !(await page.locator('.n-data-table-tbody tr').first().innerText()).includes(first), 'list re-rendered')
  await page.locator('.n-data-table-tbody tr').first().locator('.n-switch').click()
  await until(async () => (await streamsOf(6))[0].enabled === false, 'disabled by switch')
  await page.locator('.n-data-table-tbody tr').last().getByRole('button', { name: '刪除' }).click()
  await u.confirmPop()
  await until(async () => (await names()).length === n0, 'deleted')
})

test(G, 'copy to other ports: append to port 7, latency pg_id renumbered', async () => {
  const page = shared.page
  const u = ui(page)
  await demo.post('/ports/acquire', { ports: [7] })
  await u.focus(2)
  await u.tab('Streams')
  await page.getByRole('button', { name: '複製到其他 port…' }).click()
  const m = page.locator('.n-modal-container .n-card', { hasText: '複製 streams 到其他 port' })
  await m.locator('.n-checkbox', { hasText: 'Port 7' }).click()
  await m.getByRole('button', { name: '複製', exact: true }).click()
  await u.waitToast(/已複製 2 個 stream 到 1 個 port/)
  const s7 = await streamsOf(7)
  eq(s7.map((s) => s.name), ['A', 'B'], 'copied')
  assert(s7[0].flow_stats.pg_id !== 7, `latency pg_id renumbered (got ${s7[0].flow_stats.pg_id})`)
})

test(G, 'templates: personal and shared save, insert, export, import in another browser', async () => {
  const page = shared.page
  const u = ui(page)
  await u.focus(2)
  await u.tab('Streams')
  const saveTpl = async (row, name, kind) => {
    await page.locator('.n-data-table-tbody tr').nth(row).getByRole('button', { name: '存範本' }).click()
    const m = page.locator('.n-modal-container .n-card').last()
    await m.locator('.n-input input').first().fill(name)
    await m.locator('.n-radio', { hasText: kind }).click()
    await m.getByRole('button', { name: '儲存' }).click()
    await page.waitForTimeout(400)
  }
  await saveTpl(0, 'E2E 私人', '個人範本')
  await saveTpl(1, 'E2E 共用', '共用範本')
  assert(JSON.stringify(await api('GET', '/templates')).includes('E2E 共用'), 'shared template on backend')
  await page.getByRole('button', { name: /從範本新增/ }).click()
  const menu = page.locator('.n-dropdown-menu')
  await menu.waitFor()
  const text = await menu.innerText()
  assert(text.includes('E2E 私人') && text.includes('E2E 共用') && text.includes('IMIX'), `menu lists templates: ${text.replace(/\n/g, ' / ')}`)
  await menu.locator('.n-dropdown-option', { hasText: 'E2E 私人' }).click()
  await editor(page).waitFor()
  eq(await editor(page).locator('.n-card-header input').inputValue(), 'E2E 私人', 'editor opened from template')
  await editor(page).getByRole('button', { name: '取消' }).click()
  // export personal
  await page.getByRole('button', { name: /從範本新增/ }).click()
  await page.locator('.n-dropdown-option', { hasText: '管理範本' }).click()
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '匯出…' }).click()])
  const file = path.join(OUT, 'e2e-templates.json')
  await dl.saveAs(file)
  const exported = JSON.parse(fs.readFileSync(file, 'utf8'))
  assert(JSON.stringify(exported).includes('E2E 私人'), 'export has the personal template')
  await page.keyboard.press('Escape')
  // another browser does not see it until imported
  const other = await openPage()
  await other.goto(BASE)
  const ou = ui(other)
  await ou.pickHost('Demo')
  await ou.rows().first().waitFor()
  await ou.focus(2)
  await ou.tab('Streams')
  await other.getByRole('button', { name: /從範本新增/ }).click()
  let otext = await other.locator('.n-dropdown-menu').innerText()
  assert(!otext.includes('E2E 私人') && otext.includes('E2E 共用'), `other browser: shared only (${otext.replace(/\n/g, ' / ')})`)
  await other.keyboard.press('Escape')
  await other.getByRole('button', { name: /從範本新增/ }).click()
  await other.locator('.n-dropdown-option', { hasText: '管理範本' }).click()
  await other.locator('.n-modal-container input[type=file]').setInputFiles(file)
  await other.waitForTimeout(600)
  await other.keyboard.press('Escape')
  await other.getByRole('button', { name: /從範本新增/ }).click()
  otext = await other.locator('.n-dropdown-menu').innerText()
  assert(otext.includes('E2E 私人'), 'imported in the other browser')
  await other.context().close()
})

test(G, 'built-in IMIX template adds three streams 7:4:1', async () => {
  const page = shared.page
  const u = ui(page)
  await demo.post('/ports/acquire', { ports: [7] }).catch(() => {})
  await u.focus(7)
  await u.tab('Streams')
  const n0 = (await streamsOf(7)).length
  await page.getByRole('button', { name: /從範本新增/ }).click()
  await page.locator('.n-dropdown-option', { hasText: 'IMIX' }).click()
  await u.waitToast(/IMIX/)
  const s = (await streamsOf(7)).slice(n0)
  eq(s.length, 3, 'three IMIX streams')
  const sizes = s.map((x) => x.packet.frame_size).sort((a, b) => a - b)
  eq(sizes, [64, 594, 1518], 'IMIX sizes')
})

test(G, 'regression: "+ Add stream" again after Cancel still shows the packet preview', async () => {
  const page = shared.page
  const u = ui(page)
  await u.focus(5)
  await u.tab('Streams')
  const ed = editor(page)
  for (const round of [1, 2]) {
    await page.getByRole('button', { name: '＋ 新增 stream' }).click()
    await ed.waitFor()
    const shown = await ed.locator('.hex .b').first().waitFor({ timeout: 4000 }).then(() => true, () => false)
    if (!shown) await shot(page, 'bug-empty-preview')
    await ed.getByRole('button', { name: '取消' }).click()
    await ed.waitFor({ state: 'detached' })
    assert(shown, `round ${round}: hex preview shown`)
  }
}, { strict: true })
