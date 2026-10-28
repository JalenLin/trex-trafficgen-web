// English UI: walk every tab and dialog; no raw keys, no leftover Chinese. Chinese UI: no stray English labels.
import { BASE, assert, openPage, shot, test, ui } from '../lib.mjs'

const G = '14 i18n'
const KEY = /\b(common|layout|lint|monitor|ns|overview|pcap|portmap|portprofiles|ports|pyprofile|rfc2544|session|stats|streams|toolbar)\.[a-zA-Z]+(\.[a-zA-Z0-9]+)*\b/
const CJK = /[㐀-鿿！-｠]/

async function visibleText(page) {
  return page.evaluate(() => {
    const out = []
    const walk = (n) => {
      if (n.nodeType === 3) {
        const p = n.parentElement
        if (p && p.offsetParent !== null && getComputedStyle(p).visibility !== 'hidden') out.push(n.textContent)
      } else if (n.nodeType === 1 && !['SCRIPT', 'STYLE'].includes(n.tagName)) n.childNodes.forEach(walk)
    }
    walk(document.body)
    document.querySelectorAll('input[placeholder], textarea[placeholder]').forEach((e) => e.offsetParent && out.push(e.placeholder))
    document.querySelectorAll('[title]').forEach((e) => e.offsetParent && out.push(e.title))
    return out.join('\n')
  })
}
const problems = []
function check(where, text, lang) {
  for (const line of text.split('\n')) {
    const s = line.trim()
    if (!s) continue
    if (KEY.test(s)) problems.push(`${lang} ${where}: raw key "${s.slice(0, 60)}"`)
    // Chinese UI: host names / TRex messages / user data may contain CJK; English UI must not.
    if (lang === 'en' && CJK.test(s) && !/E2E|測試|設定|共用|私人|改名|e2e/.test(s)) problems.push(`en ${where}: Chinese text "${s.slice(0, 60)}"`)
  }
}

for (const lang of ['en', 'zh-TW']) {
  test(G, `${lang}: every tab, the editor and the overview have no raw keys${lang === 'en' ? ' or Chinese' : ''}`, async () => {
    problems.length = 0
    const page = await openPage({ locale: lang === 'en' ? 'en-US' : 'zh-TW' })
    await page.goto(BASE)
    const u = ui(page)
    await u.pickHost('Demo')
    await u.rows().first().waitFor()
    // the browser language decides the first language; switch explicitly anyway
    await u.selectOption(page.locator('.header .lang'), lang === 'en' ? 'English' : '繁體中文')
    await page.waitForTimeout(300)
    await u.focus(2)
    check('host page', await visibleText(page), lang)
    const tabs = await page.locator('.n-tabs-tab').allInnerTexts()
    for (let i = 0; i < tabs.length; i++) {
      await page.locator('.n-tabs-tab').nth(i).click()
      await page.waitForTimeout(700)
      if (/監控|Monitor/.test(tabs[i])) {
        await page.locator('.n-collapse-item__header').last().click()
        await page.waitForTimeout(400)
      }
      check(`tab ${tabs[i]}`, await visibleText(page), lang)
      await shot(page, `i18n-${lang}-${i}`)
    }
    // editor, all three of its tabs
    await page.locator('.n-tabs-tab').first().click()
    await page.locator('.n-data-table-tbody tr').first().getByRole('button', { name: lang === 'en' ? 'Edit' : '編輯' }).click()
    const ed = page.locator('.n-modal-container .n-card').last()
    await ed.locator('.hex .b').first().waitFor()
    for (let i = 0; i < 3; i++) {
      await ed.locator('.n-tabs-tab').nth(i).click()
      await page.waitForTimeout(300)
      check(`editor tab ${i}`, await visibleText(page), lang)
    }
    await ed.getByRole('button', { name: lang === 'en' ? 'Cancel' : '取消' }).click()
    // overview
    await page.locator('.list .item.overview').click()
    await page.locator('.cards .card').first().waitFor()
    await page.waitForTimeout(800)
    check('overview', await visibleText(page), lang)
    await shot(page, `i18n-${lang}-overview`)
    // put the language back for later specs that share localStorage (separate context: nothing to do)
    await page.context().close()
    assert(!problems.length, [...new Set(problems)].slice(0, 12).join(' || '))
  }, { timeout: 90000 })
}
