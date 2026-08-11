// L3 功能场景测试（Playwright E2E，Phase 4：页面预览缩略图 + 结构树产物）
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

const kbResp = await api('POST', '/kb', { name: `E2E-P4_${stamp}`, description: 'Phase 4 预览', domain_code: 'general' }, token)
const kbId = kbResp.body.data.id
createdKbs.push(kbId)

// ---------- L3M20-01 预览对话框显示页面缩略图 ----------
await scenario('L3M20-01', 'M20', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLE)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  await page.waitForTimeout(1500)
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  if (!doc) throw new Error('文档未上传')
  await api('POST', `/kb/${kbId}/documents/${doc.id}/start`, null, token)
  await waitDocStatus(token, kbId, doc.id, 'completed')
  const layout = await api('GET', `/kb/${kbId}/documents/${doc.id}/layout`, null, token)
  if (layout.body.data.schema_version !== '1.2') throw new Error('layout schema 应升级为 1.2')
  if (!layout.body.data.rebuild.document_tree) throw new Error('结构树产物缺失')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  await page.locator(`[data-testid="view-${doc.id}"]`).click()
  await page.waitForURL('**/viewer', { timeout: 10000 })
  await page.waitForTimeout(1200)
  const preview = page.locator('[data-testid="viewer-page"]')
  if (!(await preview.isVisible().catch(() => false))) throw new Error('左侧原文档未显示')
  const src1 = await preview.getAttribute('src')
  if (!src1) throw new Error('文档页 src 为空')
  const blocks = await page.locator('[data-testid^="block-"]').count()
  if (blocks === 0) throw new Error('版面块列表为空')
  const markdown = await page.locator('[data-testid="viewer-md"]').innerText()
  if (!markdown.trim()) throw new Error('Markdown 当前页为空')
  const json = await page.locator('[data-testid="viewer-json"]').innerText()
  if (!json.includes('"schema_version": "1.2"')) throw new Error('JSON 栏异常')
  await page.screenshot({ path: `${OUT}parsing_phase4_page_preview.png` })
})

// ---------- L3M20-02 翻页到第 2 页（文档/MD/块同步） ----------
await scenario('L3M20-02', 'M20', async () => {
  const preview = page.locator('[data-testid="viewer-page"]')
  const src1 = await preview.getAttribute('src')
  await page.getByRole('button', { name: '下一页' }).click()
  await page.waitForTimeout(1200)
  if (!(await preview.isVisible().catch(() => false))) throw new Error('第 2 页文档未显示')
  const src2 = await preview.getAttribute('src')
  if (src2 === src1) throw new Error('翻页后文档图未更新')
  const indicator = await page.getByText(/第 \d+ \/ \d+ 页/).innerText()
  if (!indicator.includes('第 2')) throw new Error(`页码未切换：${indicator}`)
  await page.screenshot({ path: `${OUT}parsing_phase4_page_2.png` })
})

for (const kbId2 of createdKbs) {
  await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined)
}
await browser.close()

const failed = results.filter((r) => r.status === 'FAIL')
const summary = { total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }
writeFileSync(`${OUT}parsing_phase4_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`PHASE4_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
