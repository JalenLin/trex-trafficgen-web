// Preferences remembered in the browser: host, ticked ports, tab, unsaved editor draft.
import { BASE, assert, eq, openPage, test, ui } from '../lib.mjs'

const G = '16 preferences'

test(G, 'host, ticked ports, focused port and tab survive a reload; unsaved draft can be restored', async () => {
  const p = await openPage()
  await p.goto(BASE)
  const u = ui(p)
  await u.pickHost('Demo')
  await u.rows().first().waitFor()
  await u.uncheckAll()
  await u.check(3)
  await u.check(6)
  await u.focus(6)
  await u.tab('Port 詳細')
  await p.reload()
  await u.rows().first().waitFor()
  await p.waitForTimeout(500)
  assert((await p.locator('.panel').innerText()).includes('Demo'), 'Demo still selected')
  const ticked = []
  for (let i = 0; i < 8; i++) if ((await u.row(i).locator('.n-checkbox').getAttribute('class')).includes('checked')) ticked.push(i)
  eq(ticked, [3, 6], 'ticked ports remembered')
  eq((await p.locator('.port-list .row.focused .name').innerText()).trim(), 'Port 6', 'focused port remembered')
  eq((await p.locator('.n-tabs-tab--active').innerText()).trim(), 'Port 詳細', 'tab remembered')
  // draft
  await u.tab('Streams')
  await p.getByRole('button', { name: '＋ 新增 stream' }).click()
  const ed = p.locator('.n-modal-container .n-card').last()
  await ed.locator('.n-card-header input').fill('還沒存的 stream')
  await p.waitForTimeout(1000)
  await p.reload()
  await u.rows().first().waitFor()
  await u.tab('Streams')
  await p.getByRole('button', { name: '＋ 新增 stream' }).click()
  await ed.getByText('有上次沒儲存的編輯').waitFor()
  await ed.getByRole('button', { name: '還原' }).click()
  eq(await ed.locator('.n-card-header input').inputValue(), '還沒存的 stream', 'draft restored')
  await ed.getByRole('button', { name: '取消' }).click()
  await u.uncheckAll()
  await p.context().close()
})
