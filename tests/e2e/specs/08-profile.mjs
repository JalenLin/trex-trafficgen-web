// Profile tab on a mock host: the shared folder is listed; mock hosts can't run profiles.
import fs from 'node:fs'
import path from 'node:path'
import { assert, shot, test, ui, until } from '../lib.mjs'
import { shared } from '../shared.mjs'

const G = '08 profile'

test(G, 'shared profile folder is listed, search filters, mock explains it cannot run profiles', async () => {
  const dir = path.join(process.env.E2E_DATA, 'profiles')
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(
    path.join(dir, 'e2e_udp.py'),
    `"""E2E test profile."""\nfrom trex_stl_lib.api import *\n\nclass STLS1:\n    def get_streams(self, direction=0, size=64, **kwargs):\n        return []\n\ndef register():\n    return STLS1()\n`,
  )
  const page = shared.page
  const u = ui(page)
  await u.tab('Profile')
  const pane = page.locator('.n-tab-pane:visible')
  await pane.getByRole('button', { name: '重新整理' }).click()
  await pane.locator('.items .item', { hasText: 'e2e_udp.py' }).waitFor()
  assert(!(await pane.getByRole('button', { name: /上傳 .py/ }).count()), 'upload button hidden while allow_profile_upload is off')
  await pane.locator('input[placeholder="搜尋檔名"]').fill('zzz')
  await until(async () => !(await pane.locator('.items .item').count()), 'filter hides everything')
  await pane.locator('input[placeholder="搜尋檔名"]').fill('e2e')
  await pane.locator('.items .item', { hasText: 'e2e_udp.py' }).click()
  await pane.locator('.n-alert', { hasText: '無法讀取這個 profile' }).waitFor()
  assert(/mock hosts can't run/.test(await pane.locator('.n-alert').innerText()), 'mock explains why')
  await shot(page, 'profile-tab')
}, { allowErrors: [/status of 4\d\d|50\d/] })
