// // L3 功能场景测试（Playwright E2E，Phase 5 文档解析前端完整化）
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
const createdUsers = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  return { status: resp.status, body: await resp.json().catch(() => null) }
}
async function adminToken() {
  const r = await api('POST', '/auth/login', { username: 'admin', password: 'admin123' })
  if (r.status !== 200) throw new Error('admin login failed')
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
  try {
    await fn()
    results.push({ id, module, status: 'PASS' })
    console.log(`PASS ${id}`)
  } catch (e) {
    results.push({ id, module, status: 'FAIL', error: String(e).slice(0, 500) })
    console.log(`FAIL ${id}: ${String(e).slice(0, 300)}`)
  }
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
const kbResp = await api('POST', '/kb', { name: `E2E-P5_${stamp}`, description: 'Phase 5 前端完整化', domain_code: 'general' }, token)
const kbId = kbResp.body.data.id
createdKbs.push(kbId)


await scenario('L3M21-01', 'M21', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(400)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLE)
  await page.waitForTimeout(400)
  const name = await page.locator('[data-testid="upload-filename"]').innerText()
  if (!name.includes('LSAM-JD01-0016')) throw new Error('上传弹窗未显示文件名')
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  if (!(await page.getByText('文档已上传').first().isVisible().catch(() => false))) throw new Error('上传未提示成功')
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  if (!doc) throw new Error('文档未出现在列表')
  await page.screenshot({ path: `${OUT}parsing_phase5_upload_dialog.png` })
  globalThis.__docId = doc.id
})

await scenario('L3M21-02', 'M21', async () => {
  // 解析可能很快完成：立即尝试捕获进度条，未捕获仅记录（功能由 L1 契约与后端状态机覆盖）
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  const progress = page.locator('[data-testid^="progress-"]')
  const seen = (await progress.count().catch(() => 0)) > 0
  await waitDocStatus(token, kbId, globalThis.__docId, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (!(await page.getByText('已完成').first().isVisible().catch(() => false))) throw new Error('未显示已完成')
  if ((await page.locator('[data-testid^="progress-"]').count().catch(() => 0)) !== 0) throw new Error('完成后不应再显示进度条')
  if (!seen) console.log('NOTE: 解析过快未捕获进度条，由 L1 契约+后端状态机覆盖')
  await page.screenshot({ path: `${OUT}parsing_phase5_progress_completed.png` })
})

await scenario('L3M21-03', 'M21', async () => {
  const docId = globalThis.__docId
  await page.locator(`[data-testid="preview-${docId}"]`).click()
  await page.waitForTimeout(1000)
  const md = await page.locator('pre').innerText()
  if (!md.includes('<!-- page: 1 -->')) throw new Error('Markdown 预览缺失')
  await page.locator('[data-testid="open-layout"]').click()
  await page.waitForTimeout(800)
  const json = await page.locator('[data-testid="layout-json"]').innerText()
  if (!json.includes('"schema_version": "1.2"')) throw new Error('layout 调试视图缺少 schema 1.2')
  if (!json.includes('document_tree')) throw new Error('layout 调试视图缺少结构树')
  await page.screenshot({ path: `${OUT}parsing_phase5_layout_debug.png` })
  await page.getByRole('button', { name: '关闭' }).last().click()
  await page.getByRole('button', { name: '关闭' }).last().click()
})

await scenario('L3M21-04', 'M21', async () => {
  await page.goto(`${BASE}/kb/${kbId}/tasks`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  const rows = page.locator('[data-testid^="task-row-"]')
  if ((await rows.count()) === 0) throw new Error('任务列表无行')
  if (!(await page.getByText('LSAM-JD01-0016').first().isVisible().catch(() => false))) throw new Error('任务列表未显示文件名')
  await page.screenshot({ path: `${OUT}parsing_phase5_tasks.png` })
})

await scenario('L3M21-05', 'M21', async () => {
  const docId = globalThis.__docId
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator(`[data-testid="reparse-${docId}"]`).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('重新解析已启动').first().isVisible().catch(() => false))) throw new Error('重解析未提示')
  await waitDocStatus(token, kbId, docId, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.locator(`[data-testid="delete-${docId}"]`).click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('文档已删除').first().isVisible().catch(() => false))) throw new Error('删除未提示')
  if ((await page.locator(`[data-testid="doc-row-${docId}"]`).count()) !== 0) throw new Error('删除后行仍存在')
})

await scenario('L3M21-06', 'M21', async () => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } })
  const mp = await ctx.newPage()
  attachErrors(mp, 'mobile')
  await sessionLogin(mp, 'admin', 'admin123')
  await mp.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await mp.waitForTimeout(800)
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (overflow > 2) throw new Error(`移动端横向溢出 ${overflow}px`)
  if (!(await mp.locator('[data-testid="open-upload"]').isVisible().catch(() => false))) throw new Error('移动端上传按钮不可见')
  await mp.screenshot({ path: `${OUT}parsing_phase5_mobile.png` })
  await ctx.close()
})


for (const kbId2 of createdKbs) {
  await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined)
}
for (const uid of createdUsers) {
  await api('DELETE', `/users/${uid}`, null, token).catch(() => undefined)
}
await browser.close()
const failed = results.filter((r) => r.status === 'FAIL')
const summary = { total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }
writeFileSync(`${OUT}parsing_phase5_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`PHASE5_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
