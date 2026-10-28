// Light / dark / system theme, dark screenshots of each tab, phone-width navigation.
import { BASE, assert, eq, openPage, shot, test, ui } from '../lib.mjs'

const G = '15 theme & mobile'
const isDark = (p) => p.evaluate(() => document.documentElement.classList.contains('dark'))
const bg = (p) => p.evaluate(() => getComputedStyle(document.body).backgroundColor)

test(G, 'theme: dark, light, system (follows the OS), remembered after reload', async () => {
  const p = await openPage({ colorScheme: 'light' })
  await p.goto(BASE)
  const u = ui(p)
  await u.pickHost('Demo')
  await u.rows().first().waitFor()
  eq(await isDark(p), false, 'system + OS light = light')
  await u.selectOption(p.locator('.header .theme'), '深色')
  eq(await isDark(p), true, 'dark picked')
  const darkBg = await bg(p)
  await p.reload()
  await u.rows().first().waitFor()
  eq(await isDark(p), true, 'dark remembered after reload')
  await u.focus(2)
  const tabs = await p.locator('.n-tabs-tab').allInnerTexts()
  for (let i = 0; i < tabs.length; i++) {
    await p.locator('.n-tabs-tab').nth(i).click()
    await p.waitForTimeout(600)
    await shot(p, `dark-${i}-${tabs[i]}`)
  }
  await p.locator('.list .item.overview').click()
  await p.locator('.cards .card').first().waitFor()
  await p.waitForTimeout(800)
  await shot(p, 'dark-overview')
  await u.selectOption(p.locator('.header .theme'), '淺色')
  eq(await isDark(p), false, 'light picked')
  assert((await bg(p)) !== darkBg, 'background changes with the theme')
  await u.selectOption(p.locator('.header .theme'), '跟隨系統')
  await p.emulateMedia({ colorScheme: 'dark' })
  await p.waitForTimeout(300)
  eq(await isDark(p), true, 'system follows OS dark')
  await p.context().close()
})

test(G, 'phone width 390: burger opens the host list, host page and tabs usable, no page overflow', async () => {
  const p = await openPage({ width: 390, height: 844 })
  await p.goto(BASE)
  await p.locator('.list .item, .compact .citem').first().waitFor()
  const u = ui(p)
  await u.pickHost('Demo')
  await p.locator('.panel').waitFor()
  await u.rows().first().waitFor()
  await u.focus(2)
  for (const name of ['Streams', '統計', 'Port 設定']) {
    await u.tab(name)
    await p.waitForTimeout(500)
    const over = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    await shot(p, `phone-${name}`)
    assert(over <= 1, `${name}: page overflows by ${over}px`)
  }
  await p.locator('.burger').click()
  await p.waitForTimeout(300)
  await shot(p, 'phone-burger')
  await p.context().close()
})
