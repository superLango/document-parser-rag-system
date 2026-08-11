// L3 功能场景测试（Playwright E2E，Phase 3：PP-DocLayoutV3 + GLM-OCR 真实解析）
import { chromium } from '/tmp/uitools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const SAMPLES = {
  lsam: join(__dirname, '../../test_doc/LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf'),
  sample: join(__dirname, '../../test_doc/462a2e2857face94b2c800d3a8492740.pdf'),
}

const results = []
const errors = []
const createdKbs = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token, raw = false) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  if (raw) return { status: resp.status, text: await resp.text() }
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
    if (r.status === 200 && (r.body.data.status === target || r.body.data.process_status === target)) {
      return r.body.data
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`文档 ${docId} 未在 ${timeout}ms 内达到 ${target}`)
}

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await context.newPage()
attachErrors(page, 'desktop')
const token = await adminToken()

const kbResp = await api('POST', '/kb', { name: `E2E-P3_${stamp}`, description: 'Phase 3 GLM-OCR', domain_code: 'general' }, token)
const kbId = kbResp.body.data.id
createdKbs.push(kbId)

// ---------- L3M19-01 真实 ppdoclayoutv3+OCR：LSAM 样本 ----------
await scenario('L3M19-01', 'M19', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLES.lsam)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  await page.waitForTimeout(1500)
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  if (!doc) throw new Error('文档未出现在列表')
  await api('POST', `/kb/${kbId}/documents/${doc.id}/start`, null, token)
  await waitDocStatus(token, kbId, doc.id, 'completed')
  const detail = await api('GET', `/kb/${kbId}/documents/${doc.id}`, null, token)
  if (detail.body.data.process_status !== 'completed') throw new Error('应完整完成（非 partial）')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  await page.locator(`[data-testid="view-${doc.id}"]`).click()
  await page.waitForURL('**/viewer', { timeout: 10000 })
  await page.waitForTimeout(1000)
  await page.locator('[data-testid="tab-md"]').click()
  await page.waitForTimeout(300)
  const text = await page.locator('[data-testid="viewer-md"]').innerText()
  if (!text.includes('优质 GH4169')) throw new Error('内页缺少 GLM-OCR 识别标题')
  if (!text.includes('<table')) throw new Error('内页缺少 GLM-OCR 表格 HTML')
  if (text.includes('Page 1 of 10')) throw new Error('页眉内容泄漏进 Markdown')
  await page.locator('[data-testid="tab-json"]').click()
  await page.waitForTimeout(300)
  const json = await page.locator('[data-testid="viewer-json"]').innerText()
  if (!json.includes('"schema_version": "1.2"')) throw new Error('JSON 栏异常')
  await page.screenshot({ path: `${OUT}parsing_phase3_ocr_markdown.png` })
})

// ---------- L3M19-02 真实 ppdoclayoutv3+OCR：第二个样本 ----------
await scenario('L3M19-02', 'M19', async () => {
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLES.sample)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  await page.waitForTimeout(1500)
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('462a2e28'))
  if (!doc) throw new Error('第二份文档未上传')
  await api('POST', `/kb/${kbId}/documents/${doc.id}/start`, null, token)
  await waitDocStatus(token, kbId, doc.id, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  await page.locator(`[data-testid="view-${doc.id}"]`).click()
  await page.waitForURL('**/viewer', { timeout: 10000 })
  await page.waitForTimeout(1000)
  await page.locator('[data-testid="tab-md"]').click()
  await page.waitForTimeout(300)
  const md = await page.locator('[data-testid="viewer-md"]').innerText()
  if (!md.trim()) throw new Error('OCR 产物为空')
  await page.locator('[data-testid="tab-json"]').click()
  await page.waitForTimeout(300)
  const json = await page.locator('[data-testid="viewer-json"]').innerText()
  if (!json.includes('document_tree')) throw new Error('JSON 栏缺少结构树')
  await page.screenshot({ path: `${OUT}parsing_phase3_second_sample.png` })
})

// ---------- 清理 ----------
for (const kbId2 of createdKbs) {
  await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined)
}
await browser.close()

const failed = results.filter((r) => r.status === 'FAIL')
const summary = { total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }
writeFileSync(`${OUT}parsing_phase3_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`PHASE3_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
