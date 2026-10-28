// Port settings: L3 / ARP, L2, VLAN validation, IPv6, switches, apply to others, link, ping, port profiles.
import { assert, eq, hostApi, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '03 port settings'
const demo = hostApi('demo')
const layer = async (p) => (await demo.get('/ports'))[p].layer
const port = async (p) => (await demo.get('/ports'))[p]

const form = (page) => page.locator('.form').first()
const item = (page, label) =>
  form(page).locator('.n-form-item').filter({ has: page.locator('.n-form-item-label', { hasText: new RegExp(`^\\s*${label}\\s*$`) }) })
const applyBtn = (page) => form(page).getByRole('button', { name: '套用', exact: true })

async function open(port) {
  const page = shared.page
  const u = ui(page)
  await u.focus(port)
  await u.tab('Port 設定')
  await page.locator('text=' + `Port ${port} 的 L2/L3 設定`).waitFor()
  return { page, u }
}

test(G, 'L3: change gateway, ARP resolves; unreachable gateway shows ARP unresolved', async () => {
  const { page, u } = await open(4)
  const gw = item(page, 'Gateway IPv4').locator('input')
  await gw.fill('10.4.0.9')
  await applyBtn(page).click()
  await until(async () => (await layer(4)).ipv4_dst === '10.4.0.9' && (await layer(4)).arp === 'resolved', 'gateway 10.4.0.9 resolved')
  await item(page, 'Gateway IPv4').locator('.n-tag', { hasText: '已解析' }).waitFor()
  await gw.fill('10.9.9.9')
  await applyBtn(page).click()
  await until(async () => (await layer(4)).arp === 'unresolved', 'gateway outside /24 unresolved')
  await u.row(4).locator('.n-tag', { hasText: 'ARP 未解析' }).waitFor()
  await shot(page, 'portcfg-arp-unresolved')
  await gw.fill('10.4.0.1')
  await applyBtn(page).click()
  await until(async () => (await layer(4)).arp === 'resolved', 'back to resolved')
  await item(page, 'Gateway IPv4').getByRole('button', { name: '重新解析' }).click()
  await page.waitForTimeout(400)
  eq((await layer(4)).arp, 'resolved', 're-resolve keeps it resolved')
}, { allowErrors: [/status of 4\d\d|50\d/] })

test(G, 'L2: set destination MAC; invalid MAC is rejected with a message', async () => {
  const { page, u } = await open(5)
  await item(page, '模式').locator('.n-radio', { hasText: 'L2' }).click()
  const mac = item(page, '目的 MAC').locator('input')
  await mac.fill('00:11:22:33:44')
  await applyBtn(page).click()
  await u.waitToast(/MAC|失敗|invalid/i)
  await mac.fill('00:11:22:33:44:55')
  await applyBtn(page).click()
  await until(async () => (await layer(5)).mode === 'L2' && (await layer(5)).dst_mac === '00:11:22:33:44:55', 'port 5 in L2 with dst MAC')
}, { allowErrors: [/status of 4\d\d|50\d/] })

test(G, 'VLAN validation: 5000 and three tags are refused, QinQ 100,200 applies', async () => {
  const { page } = await open(4)
  const v = item(page, 'VLAN').locator('input')
  for (const bad of ['5000', '1, 2, 3', 'abc']) {
    await v.fill(bad)
    await item(page, 'VLAN').locator('.n-form-item-feedback', { hasText: 'VLAN' }).waitFor()
    eq(await applyBtn(page).isDisabled(), true, `Apply disabled for "${bad}"`)
  }
  await v.fill('100, 200')
  await applyBtn(page).click()
  await until(async () => JSON.stringify((await layer(4)).vlan) === '[100,200]', 'QinQ applied')
  await v.fill('')
  await applyBtn(page).click()
  await until(async () => (await layer(4)).vlan.length === 0, 'VLAN cleared')
})

test(G, 'IPv6, promiscuous, multicast and flow control', async () => {
  const { page } = await open(4)
  await item(page, 'IPv6').locator('.n-switch').click()
  await item(page, 'IPv6').locator('input').fill('2001:db8::4')
  await item(page, 'Promiscuous').locator('.n-switch').click()
  await item(page, 'Multicast').locator('.n-switch').click()
  await ui(page).selectOption(item(page, 'Flow control').locator('.n-select'), /TX.*RX|full|全/i)
  await applyBtn(page).click()
  await until(async () => {
    const l = await layer(4)
    return l.ipv6 && l.ipv6_src === '2001:db8::4' && l.promiscuous && l.multicast && l.flow_ctrl === 3
  }, 'IPv6 + promisc + multicast + flow ctrl applied')
  // turn them back off
  await item(page, 'IPv6').locator('.n-switch').click()
  await item(page, 'Promiscuous').locator('.n-switch').click()
  await item(page, 'Multicast').locator('.n-switch').click()
  await applyBtn(page).click()
  await until(async () => {
    const l = await layer(4)
    return !l.ipv6 && !l.promiscuous && !l.multicast
  }, 'switched back off')
})

test(G, 'apply to other selected ports copies VLAN to them', async () => {
  const { page, u } = await open(4)
  await u.uncheckAll()
  for (const i of [4, 5, 6]) await u.check(i)
  await item(page, 'VLAN').locator('input').fill('300')
  const also = form(page).locator('.n-checkbox', { hasText: '同時套用到其他勾選的 port' })
  await also.waitFor()
  if (!(await also.getAttribute('class')).includes('checked')) await also.click()
  await applyBtn(page).click()
  await until(async () => {
    const ps = await demo.get('/ports')
    return [4, 5, 6].every((i) => JSON.stringify(ps[i].layer.vlan) === '[300]')
  }, 'VLAN 300 on ports 4, 5, 6')
  // clean up
  await item(page, 'VLAN').locator('input').fill('')
  await applyBtn(page).click()
  await until(async () => {
    const ps = await demo.get('/ports')
    return [4, 5, 6].every((i) => ps[i].layer.vlan.length === 0)
  }, 'VLAN cleared on all three')
  if ((await also.getAttribute('class')).includes('checked')) await also.click()
  await u.uncheckAll()
})

test(G, 'link down asks for confirmation; link back up', async () => {
  const { page } = await open(6)
  await item(page, 'Link').locator('.n-switch').click()
  assert(await item(page, 'Link').getByText('套用後實體連線會斷開').count(), 'link-down warning shown')
  await applyBtn(page).click()
  await page.locator('.n-popconfirm', { hasText: 'link 關掉' }).waitFor()
  await ui(page).confirmPop()
  await until(async () => (await port(6)).link === 'DOWN', 'port 6 link down')
  await item(page, 'Link').locator('.n-switch').click()
  await applyBtn(page).click()
  await until(async () => (await port(6)).link === 'UP', 'port 6 link up again')
})

test(G, 'ping the gateway shows replies with RTT', async () => {
  const { page } = await open(4)
  await page.getByRole('button', { name: 'Ping', exact: true }).click()
  const summary = page.getByText(/\d+\/\d+ 個回應|回應/)
  await until(async () => (await page.locator('table').filter({ hasText: 'RTT' }).locator('tbody tr').count()) >= 3, 'ping result rows')
  const txt = await page.locator('table').filter({ hasText: 'RTT' }).innerText()
  assert(/ok/i.test(txt) && /10\.4\.0\.1/.test(txt), `ping replies from gateway: ${txt.replace(/\s+/g, ' ').slice(0, 120)}`)
  void summary
})

test(G, 'port profiles: save, list, apply, rename, delete', async () => {
  const { page, u } = await open(4)
  await u.uncheckAll()
  await u.check(4)
  await u.check(5)
  await page.getByRole('button', { name: /把 Port 4, 5 存成設定檔/ }).click()
  const m = page.locator('.n-modal-container .n-card').last()
  await m.locator('input').fill('E2E 設定')
  await m.getByRole('button', { name: '儲存' }).click()
  await u.waitToast(/已存成設定檔/)
  const list = (await demo.get('/port-profiles')).profiles
  assert(list.some((p) => p.name === 'E2E 設定'), 'saved on backend')
  // change port 4, then apply the profile back
  await item(page, 'VLAN').locator('input').fill('42')
  await applyBtn(page).click()
  await until(async () => JSON.stringify((await layer(4)).vlan) === '[42]', 'VLAN 42 applied')
  await u.selectOption(page.locator('.profiles .n-select'), 'E2E 設定')
  await page.locator('.profiles').getByRole('button', { name: '套用…' }).click()
  const d = page.locator('.n-modal-container .n-card').last()
  await d.getByText('會套用').first().waitFor()
  await shot(page, 'portcfg-profile-apply')
  await d.getByRole('button', { name: /套用到 \d+ 個 port/ }).click()
  await until(async () => (await layer(4)).vlan.length === 0, 'profile restored VLAN')
  // manage: rename then delete
  await page.locator('.profiles').getByRole('button', { name: '管理…' }).click()
  const mg = page.locator('.n-modal-container .n-card').last()
  await mg.locator('.manage input').first().fill('E2E 改名')
  await mg.getByRole('button', { name: '改名' }).first().click()
  await until(async () => (await demo.get('/port-profiles')).profiles.some((p) => p.name === 'E2E 改名'), 'renamed')
  await mg.getByRole('button', { name: '刪除' }).first().click()
  await u.confirmPop()
  await until(async () => !(await demo.get('/port-profiles')).profiles.length, 'deleted')
  await page.keyboard.press('Escape')
  await u.uncheckAll()
})

test(G, 'restore port 5 to L3 for later tests', async () => {
  await demo.post('/ports/5/config', { l3: { src: '10.5.0.2', dst: '10.5.0.1' } }).catch(async () => {
    // field names differ between versions; fall back to the UI
    const { page } = await open(5)
    await item(page, '模式').locator('.n-radio', { hasText: 'L3' }).click()
    await item(page, '本機 IPv4').locator('input').fill('10.5.0.2')
    await item(page, 'Gateway IPv4').locator('input').fill('10.5.0.1')
    await applyBtn(page).click()
  })
  await until(async () => (await layer(5)).mode === 'L3' && (await layer(5)).arp === 'resolved', 'port 5 back in L3')
})

test(G, 'drift banner: settings changed outside the GUI after a profile was applied; Ignore hides it', async () => {
  const page = shared.page
  // port 5 was set back to L3 through the API after "E2E 设定" was applied to it; the GUI
  // learns about outside changes when it next reads the ports (here: a reload)
  await page.reload()
  await ui(page).rows().first().waitFor()
  const banner = page.locator('.n-alert', { hasText: '和上次套用的設定檔' })
  await banner.waitFor({ timeout: 10000 })
  assert(await banner.getByRole('button', { name: /重新套用/ }).count(), 'offers to re-apply')
  await shot(page, 'portcfg-drift-banner')
  await banner.getByRole('button', { name: '忽略' }).click()
  await banner.waitFor({ state: 'detached' })
})

// --- reproductions of app bugs (strict: no console errors allowed) ---
test(G, 'regression: opening the Port settings tab logs no console errors', async () => {
  const { openPage, BASE } = await import('../lib.mjs')
  const p = await openPage()
  await p.goto(BASE)
  const u = ui(p)
  await u.pickHost('Demo')
  await u.rows().first().waitFor()
  await u.focus(4)
  await u.tab('Port 設定')
  await p.getByText('Port 4 的 L2/L3 設定').waitFor()
  await p.waitForTimeout(500)
  const errs = p.errors.slice()
  await p.context().close()
  assert(!errs.length, `console errors on mount: ${errs.join(' | ').slice(0, 300)}`)
}, { strict: true })

test(G, 'regression: save, open Apply…, then delete a port profile: no console errors', async () => {
  const { openPage, BASE } = await import('../lib.mjs')
  const p = await openPage()
  await p.goto(BASE)
  const u = ui(p)
  await u.pickHost('Demo')
  await u.rows().first().waitFor()
  await u.focus(4)
  await u.tab('Port 設定')
  await p.getByText('Port 4 的 L2/L3 設定').waitFor()
  await p.waitForTimeout(300)
  p.errors.length = 0 // the tab-mount bug above is a separate test
  await u.uncheckAll()
  await u.check(4)
  await p.getByRole('button', { name: /存成設定檔/ }).click()
  await p.locator('.n-modal-container .n-card').last().locator('input').fill('strict')
  await p.locator('.n-modal-container .n-card').last().getByRole('button', { name: '儲存' }).click()
  await u.waitToast(/已存成設定檔/)
  const afterSave = p.errors.slice()
  await u.selectOption(p.locator('.profiles .n-select'), 'strict')
  await p.locator('.profiles').getByRole('button', { name: '套用…' }).click()
  await p.locator('.n-modal-container .n-card').last().getByRole('button', { name: '取消' }).click()
  await p.waitForTimeout(400)
  const afterChoose = p.errors.slice()
  await p.locator('.profiles').getByRole('button', { name: '管理…' }).click()
  await p.locator('.n-modal-container .n-card').last().getByRole('button', { name: '刪除' }).first().click()
  await u.confirmPop()
  await until(async () => !(await demo.get('/port-profiles')).profiles.length, 'deleted')
  await p.waitForTimeout(500)
  const errs = p.errors.slice()
  await p.context().close()
  assert(!errs.length, `console errors (after save: ${afterSave.length}, after choosing: ${afterChoose.length}, total ${errs.length}): ${[...new Set(errs)].join(' | ').slice(0, 300)}`)
}, { strict: true })
