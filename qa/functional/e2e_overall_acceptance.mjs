// L3 功能场景测试（Playwright E2E，Phase 1-6 整体验收 M23）
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
const kbResp = await api('POST', '/kb', { name: `E2E-OVERALL_${stamp}`, description: 'Phase 1-6 整体验收', domain_code: 'general' }, token)
const kbId = kbResp.body.data.id
createdKbs.push(kbId)

await scenario('L3M23-01', 'M23', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLE)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1500)
  if (!(await page.getByText('文档已上传').first().isVisible().catch(() => false))) throw new Error('上传未提示成功')
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  if (!doc) throw new Error('文档未出现在列表')
  await api('POST', `/kb/${kbId}/documents/${doc.id}/start`, null, token)
  await waitDocStatus(token, kbId, doc.id, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (!(await page.getByText('已完成').first().isVisible().catch(() => false))) throw new Error('未显示已完成')
  // 内页：左原文档 + 右三栏（版面块/MD/JSON）
  await page.locator(`[data-testid="view-${doc.id}"]`).click()
  await page.waitForURL('**/viewer', { timeout: 10000 })
  await page.waitForTimeout(1000)
  if (!(await page.locator('[data-testid="viewer-page"]').isVisible().catch(() => false))) throw new Error('左侧原文档缺失')
  const blockList = page.locator('[data-testid^="block-"]')
  await blockList.first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => undefined)
  if ((await blockList.count()) === 0) throw new Error('版面块列表为空')
  await page.locator('[data-testid="tab-md"]').click()
  await page.waitForTimeout(300)
  const md = await page.locator('[data-testid="viewer-md"]').innerText()
  if (!md.includes('优质 GH4169') || !md.includes('<table')) throw new Error('Markdown 产物异常')
  await page.locator('[data-testid="tab-json"]').click()
  await page.waitForTimeout(300)
  const layout = await page.locator('[data-testid="viewer-json"]').innerText()
  if (!layout.includes('"schema_version": "1.2"') || !layout.includes('document_tree')) throw new Error('JSON 栏异常')
  await page.screenshot({ path: `${OUT}overall_phase6_preview.png` })
  // 任务列表
  await page.goto(`${BASE}/kb/${kbId}/tasks`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  if ((await page.locator('[data-testid^="task-row-"]').count()) === 0) throw new Error('任务列表为空')
  // 重解析 + 删除
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator(`[data-testid="reparse-${doc.id}"]`).click()
  await page.waitForTimeout(900)
  await waitDocStatus(token, kbId, doc.id, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.locator(`[data-testid="delete-${doc.id}"]`).click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForTimeout(900)
  if ((await page.locator(`[data-testid="doc-row-${doc.id}"]`).count()) !== 0) throw new Error('删除后行仍存在')
  await page.screenshot({ path: `${OUT}overall_phase6_done.png` })
})

await scenario('L3M23-02', 'M23', async () => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } })
  const mp = await ctx.newPage()
  attachErrors(mp, 'mobile-overall')
  await sessionLogin(mp, 'admin', 'admin123')
  await mp.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await mp.waitForTimeout(800)
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (overflow > 2) throw new Error(`移动端横向溢出 ${overflow}px`)
  if (!(await mp.locator('[data-testid="open-upload"]').isVisible().catch(() => false))) throw new Error('移动端上传按钮不可见')
  await mp.screenshot({ path: `${OUT}overall_phase6_mobile.png` })
  await ctx.close()
})

for (const kbId2 of createdKbs) { await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined) }
await browser.close()
const failed = results.filter((r) => r.status === 'FAIL')
const summary = { total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }
writeFileSync(`${OUT}overall_phase6_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`OVERALL_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
