// PCAP library: upload, preview, to streams, rename, download, delete, replay, capture.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { OUT, ROOT, api, assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '09 pcap'
const demo = hostApi('demo')
const pane = () => shared.page.locator('.n-tab-pane:visible')
const lib = () => api('GET', '/pcaps')

test(G, 'upload a pcap: it appears in the library with its packet count', async () => {
  const file = path.join(OUT, 'e2e.pcap')
  execFileSync(path.join(ROOT, 'backend/.venv/bin/python'), ['-c', `
from scapy.all import Ether, IP, UDP, ICMP, Raw, wrpcap
pk = [Ether(dst='00:11:22:33:44:55')/IP(src='10.0.0.%d' % i, dst='10.0.1.1')/UDP(sport=1000+i, dport=53)/Raw(b'x'*20) for i in range(20)]
pk += [Ether()/IP(dst='10.0.1.1')/ICMP() for _ in range(2)]
for i, p in enumerate(pk): p.time = 1700000000 + i * 0.01
wrpcap(${JSON.stringify(file)}, pk)
`])
  const page = shared.page
  const u = ui(page)
  await u.uncheckAll()
  await u.check(4)
  await u.focus(4)
  await u.tab('PCAP')
  await pane().locator('input[type=file][accept*=pcap]').setInputFiles(file)
  await u.waitToast(/已上傳「e2e(\.pcap)?」：22 個封包/)
  const row = pane().locator('.n-data-table-tbody tr', { hasText: '22' }).first()
  await row.waitFor()
  assert((await lib()).some((m) => /^e2e/.test(m.name) && m.packets === 22), 'library entry on backend')
  await shot(page, 'pcap-library')
})

test(G, 'preview and convert two packets to streams on port 4', async () => {
  const page = shared.page
  const u = ui(page)
  const n0 = (await demo.get('/ports/4/streams')).length
  await pane().getByRole('button', { name: '預覽 / 轉成 stream' }).first().click()
  const m = page.locator('.n-modal-container .n-card').last()
  await m.locator('.n-data-table-tbody tr').first().waitFor()
  const first = await m.locator('.n-data-table-tbody tr').first().innerText()
  assert(/UDP|10\.0\.0\.0/.test(first), `preview row decoded: ${first.replace(/\s+/g, ' ').slice(0, 80)}`)
  await m.locator('.n-data-table-tbody tr').nth(0).locator('.n-checkbox').click()
  await m.locator('.n-data-table-tbody tr').nth(21).locator('.n-checkbox').click()
  await m.getByRole('button', { name: /把 2 個封包轉成 stream，加入 Port 4/ }).click()
  await u.waitToast(/已把 2 個封包加入 Port 4/)
  await m.getByRole('button', { name: '關閉' }).click()
  eq((await demo.get('/ports/4/streams')).length, n0 + 2, 'two streams added')
})

test(G, 'rename (on blur) and download', async () => {
  const page = shared.page
  const u = ui(page)
  const name = pane().locator('.n-data-table-tbody tr').first().locator('input').first()
  await name.fill('e2e-renamed')
  await name.blur()
  await u.waitToast(/已改名/)
  assert((await lib()).some((m) => m.name === 'e2e-renamed'), 'renamed on backend')
  const [dl] = await Promise.all([page.waitForEvent('download'), pane().getByRole('button', { name: '下載' }).first().click()])
  const out = path.join(OUT, 'e2e-download.pcap')
  await dl.saveAs(out)
  const head = fs.readFileSync(out).subarray(0, 4).toString('hex')
  assert(['d4c3b2a1', 'a1b2c3d4', '4d3cb2a1', 'a1b23c4d'].includes(head), `downloaded a pcap (magic ${head})`)
})

test(G, 'replay dialog: replay on port 4, then stop', async () => {
  const page = shared.page
  const u = ui(page)
  await pane().getByRole('button', { name: '重播…' }).first().click()
  const m = page.locator('.n-modal-container .n-card').last()
  await m.getByText('一次 22 個封包').first().waitFor()
  await m.locator('.n-checkbox', { hasText: '一直重播' }).click()
  await m.getByRole('button', { name: '開始重播' }).click()
  await u.waitToast(/開始在 Port 4 重播/)
  await until(async () => (await demo.get('/ports'))[4].status === 'TRANSMITTING', 'port 4 transmitting the pcap')
  await shot(page, 'pcap-replay')
  await u.tb(/停止/).click()
  await until(async () => (await demo.get('/ports'))[4].status === 'IDLE', 'stopped')
})

test(G, 'capture TX 2 / RX 3 with service mode, save to the library', async () => {
  const page = shared.page
  const u = ui(page)
  const form = pane().locator('.capform')
  await form.locator('.n-checkbox-group').nth(0).locator('.n-checkbox', { hasText: 'Port 2' }).click()
  await form.locator('.n-checkbox-group').nth(1).locator('.n-checkbox', { hasText: 'Port 3' }).click()
  const svc = form.locator('.n-checkbox', { hasText: '擷取期間開啟' })
  if (!(await svc.getAttribute('class')).includes('checked')) await svc.click()
  await pane().getByRole('button', { name: '開始擷取' }).click()
  await pane().locator('.capture').first().waitFor()
  // (the mock ignores the capture's service flag, so service mode itself is checked on real TRex only)
  // send something so the capture has packets
  await u.uncheckAll()
  await u.check(2)
  await u.start()
  await until(async () => /[1-9][\d,]* \/ [\d,]+ 個封包/.test(await pane().locator('.capture').first().innerText()), 'capture counts packets', 10000)
  // stop the capture while traffic still runs: the mock rebuilds captured packets from
  // the running flows, so stopping traffic first would leave it nothing to save
  await pane().locator('.capture input').first().fill('e2e-capture')
  await pane().getByRole('button', { name: '停止並存進檔案庫' }).click()
  const toast = await u.waitToast(/已存成|capture|失敗|error|no /i)
  assert(/已存成「e2e-capture」/.test(toast), `saved toast: ${toast}`)
  await u.tb(/停止/).click()
  assert((await lib()).some((m) => m.name === 'e2e-capture' && m.source === 'capture'), 'capture saved')
})

test(G, 'delete asks for confirmation', async () => {
  const page = shared.page
  const u = ui(page)
  const n0 = (await lib()).length
  await pane().getByRole('button', { name: '刪除' }).first().click()
  await u.confirmPop()
  await until(async () => (await lib()).length === n0 - 1, 'one pcap deleted')
})
