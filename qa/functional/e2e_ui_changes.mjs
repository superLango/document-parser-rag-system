// L3 功能场景测试（Playwright E2E，四项 UI 改造：菜单高亮/手动解析/去除版面按钮/内页联动）
import { chromium } from '/tmp/uitools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })
const SAMPLE = join(__dirname, '../../test_doc/LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf')
const results = []
const errors = []
const createdKbs = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  return { status: resp.status, body: await resp.json().catch(() => null) }
}
async function adminToken() {
  const r = await api('POST', '/auth/login', { username: 'admin', password: 'admin123' })
  if (r.status !== 200 || !r.body?.data) throw new Error('admin login failed')
  return r.body.data.access_token
}
function attachErrors(page, label) {
  page.on('pageerror', (e) => errors.push(`[${label}] pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    if (/401|429/.test(m.text())) return
    errors.push(`[${label}] console: ${m.text()}`)
  })
}
async function sessionLogin(page, username, password) {
  let r = await api('POST', '/auth/login', { username, password })
  for (let i = 0; r.status === 429 && i < 6; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3000))
    r = await api('POST', '/auth/login', { username, password })
  }
  if (r.status !== 200) throw new Error(`登录失败 ${r.status}`)
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(([a, rf]) => {
    localStorage.removeItem('hansondoc-auth')
    localStorage.setItem('access_token', a)
    localStorage.setItem('refresh_token', rf || '')
  }, [r.body.data.access_token, r.body.data.refresh_token])
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
}
async function scenario(id, module, fn) {
  try { await fn(); results.push({ id, module, status: 'PASS' }); console.log(`PASS ${id}`) }
  catch (e) { results.push({ id, module, status: 'FAIL', error: String(e).slice(0, 500) }); console.log(`FAIL ${id}: ${String(e).slice(0, 300)}`) }
}
async function waitDocStatus(token, kbId, docId, target, timeout = 180000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const r = await api('GET', `/kb/${kbId}/documents/${docId}`, null, token)
    if (r.status === 200 && (r.body.data.status === target || r.body.data.process_status === target)) return r.body.data
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`文档未在 ${timeout}ms 内完成`)
}

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await context.newPage()
attachErrors(page, 'desktop')
const token = await adminToken()

// ---------- 场景 1：菜单高亮修复 ----------
await scenario('L3UI-01', 'M8', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/invitations`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const activeLinks = await page.locator('aside a[aria-current="page"]').allInnerTexts()
  if (activeLinks.length !== 1 || !activeLinks[0].includes('我的邀请')) {
    throw new Error(`菜单高亮异常：${JSON.stringify(activeLinks)}`)
  }
  await page.goto(`${BASE}/kb`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const activeLinks2 = await page.locator('aside a[aria-current="page"]').allInnerTexts()
  if (activeLinks2.length !== 1 || !activeLinks2[0].includes('知识库')) {
    throw new Error(`知识库菜单高亮异常：${JSON.stringify(activeLinks2)}`)
  }
  await page.screenshot({ path: `${OUT}ui_menu_active.png` })
})

// 准备：建库
const kbResp = await api('POST', '/kb', { name: `E2E-UI_${stamp}`, description: '四项 UI 改造', domain_code: 'general' }, token)
const kbId = kbResp.body.data.id
createdKbs.push(kbId)

// ---------- 场景 2：上传后待解析 + 手动解析按钮 ----------
await scenario('L3UI-02', 'M18', async () => {
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLE)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  if (!doc) throw new Error('文档未出现在列表')
  if (doc.status !== 'queued') throw new Error(`上传后应为待解析，实际 ${doc.status}`)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (!(await page.getByText('待解析').first().isVisible().catch(() => false))) throw new Error('未显示待解析状态')
  const startBtn = page.locator(`[data-testid="start-${doc.id}"]`)
  if (!(await startBtn.isVisible().catch(() => false))) throw new Error('未显示开始解析按钮')
  if ((await page.locator('[data-testid^="layout-"]').count()) !== 0) throw new Error('仍存在版面结构按钮')
  await page.screenshot({ path: `${OUT}ui_queued_start.png` })
  globalThis.__docId = doc.id
})

// ---------- 场景 3：点击开始解析 → 完成 ----------
await scenario('L3UI-03', 'M18', async () => {
  await page.locator(`[data-testid="start-${globalThis.__docId}"]`).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('解析已开始').first().isVisible().catch(() => false))) throw new Error('开始解析未提示')
  await waitDocStatus(token, kbId, globalThis.__docId, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (!(await page.getByText('已完成').first().isVisible().catch(() => false))) throw new Error('未显示已完成')
})

// ---------- 场景 4：内页（左文档 + 右三栏联动） ----------
await scenario('L3UI-04', 'M18', async () => {
  await page.locator(`[data-testid="view-${globalThis.__docId}"]`).click()
  await page.waitForURL('**/viewer', { timeout: 10000 })
  await page.waitForTimeout(1200)
  if (!(await page.locator('[data-testid="viewer-page"]').isVisible().catch(() => false))) throw new Error('左侧原文档未显示')
  const blockCount = await page.locator('[data-testid^="block-"]').count()
  if (blockCount === 0) throw new Error('版面块列表为空')
  const mdText = await page.locator('[data-testid="viewer-md"]').innerText()
  if (!mdText.includes('优质 GH4169')) throw new Error('Markdown 当前页内容异常')
  const jsonText = await page.locator('[data-testid="viewer-json"]').innerText()
  if (!jsonText.includes('"schema_version": "1.2"')) throw new Error('JSON 栏内容异常')
  // 点击第一个版面块 → 文档矩形高亮
  const firstBlock = page.locator('[data-testid^="block-"]').first()
  const blockId = (await firstBlock.getAttribute('data-testid')).replace('block-', '')
  await firstBlock.click()
  await page.waitForTimeout(300)
  const rect = page.locator(`[data-testid="doc-rect-${blockId}"]`)
  const rectCount = await page.locator('[data-testid^="doc-rect-"]').count()
  if (!(await rect.isVisible().catch(() => false))) {
    const info = await page.locator(`[data-testid="block-${blockId}"]`).evaluate((el) => ({
      cls: el.className,
      text: el.innerText,
    })).catch(() => null)
    throw new Error(`版面块未在文档中高亮 blockId=${blockId} rectCount=${rectCount} info=${JSON.stringify(info)}`)
  }
  // 点击文档矩形 → 仍选中
  await rect.click()
  await page.waitForTimeout(300)
  const activeBlock = await page.locator(`[data-testid="block-${blockId}"]`).evaluate((el) => el.className)
  if (!activeBlock.includes('rose')) throw new Error('文档矩形点击未联动到块列表')
  // 翻页同步
  const pageIndicator = await page.getByText(/第 \d+ \/ \d+ 页/).innerText()
  await page.getByRole('button', { name: '下一页' }).click()
  await page.waitForTimeout(900)
  const indicator2 = await page.getByText(/第 \d+ \/ \d+ 页/).innerText()
  if (indicator2 === pageIndicator) throw new Error('翻页未生效')
  await page.screenshot({ path: `${OUT}ui_viewer_linked.png` })
})

// ---------- 场景 5：控制台无错误 + 清理 ----------
await scenario('L3UI-05', 'M18', async () => {
  if (errors.length > 0) throw new Error(`存在控制台错误：${JSON.stringify(errors)}`)
})

for (const kbId2 of createdKbs) { await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined) }
await browser.close()
const failed = results.filter((r) => r.status === 'FAIL')
const summary = { total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }
writeFileSync(`${OUT}ui_changes_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`UI_CHANGES_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (failed.length) process.exitCode = 1
