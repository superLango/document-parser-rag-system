// L4 边界异常测试（Playwright E2E，Phase 5 前端校验与移动端）
import { chromium } from '/tmp/uitools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })
const SAMPLE = join(__dirname, '../../test_doc/a62820a10c1c33f40ede554498d7bdf1.pdf')
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
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(([a, rf]) => {
    localStorage.removeItem('hansondoc-auth')
    localStorage.setItem('access_token', a)
    localStorage.setItem('refresh_token', rf || '')
  }, [r.body.data.access_token, r.body.data.refresh_token])
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
}
async function scenario(id, module, fn) {
  try { await fn(); results.push({ id, module, status: 'PASS' }); console.log(`PASS ${id}`) }
  catch (e) { results.push({ id, module, status: 'FAIL', error: String(e).slice(0, 400) }); console.log(`FAIL ${id}: ${String(e).slice(0, 250)}`) }
}

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
attachErrors(page, 'desktop')
const token = await adminToken()
const kb = await api('POST', '/kb', { name: `E2E-P5B_${stamp}`, domain_code: 'general' }, token)
const kbId = kb.body.data.id
createdKbs.push(kbId)

// 通过 API 预置一份真实样本用于搜索过滤
const form = new FormData()
form.append('file', new Blob([readFileSync(SAMPLE)], { type: 'application/pdf' }), '边界样本.pdf')
await fetch(`${API}/kb/${kbId}/documents`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form })

await sessionLogin(page, 'admin', 'admin123')
await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
await page.waitForTimeout(800)

await scenario('L4M21-01', 'M21', async () => {
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', { name: 'a.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') })
  await page.waitForTimeout(300)
  const err = await page.locator('[data-testid="upload-error"]').innerText()
  if (!err.includes('仅支持 PDF')) throw new Error(`错误提示异常：${err}`)
  const disabled = await page.locator('[data-testid="confirm-upload"]').isDisabled()
  if (!disabled) throw new Error('非 PDF 时确认按钮应禁用')
})

await scenario('L4M21-02', 'M21', async () => {
  await page.setInputFiles('[data-testid="upload-input"]', { name: 'empty.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(0) })
  await page.waitForTimeout(300)
  const err = await page.locator('[data-testid="upload-error"]').innerText()
  if (!err.includes('文件为空')) throw new Error(`错误提示异常：${err}`)
})

await scenario('L4M21-03', 'M21', async () => {
  const bigFile = '/tmp/phase5_big.pdf'
  writeFileSync(bigFile, Buffer.alloc(101 * 1024 * 1024))
  await page.setInputFiles('[data-testid="upload-input"]', bigFile)
  await page.waitForTimeout(500)
  const err = await page.locator('[data-testid="upload-error"]').innerText()
  if (!err.includes('100MB')) throw new Error(`错误提示异常：${err}`)
  await page.getByRole('button', { name: '取消' }).click()
  await page.waitForTimeout(300)
})

await scenario('L4M21-04', 'M21', async () => {
  // 确保上传弹窗已关闭
  if (await page.locator('[data-testid="confirm-upload"]').count() > 0) {
    await page.getByRole('button', { name: '取消' }).click().catch(() => undefined)
    await page.waitForTimeout(300)
  }
  await page.getByPlaceholder('搜索文件名').fill('边界样本')
  await page.getByRole('button', { name: '搜索' }).click()
  await page.waitForTimeout(900)
  const rows = await page.locator('[data-testid^="doc-row-"]').count()
  if (rows !== 1) throw new Error(`搜索应只返回 1 行，实际 ${rows}`)
  if (!(await page.getByText('边界样本.pdf').first().isVisible().catch(() => false))) throw new Error('搜索结果未显示匹配文件')
})

await scenario('L4M21-05', 'M21', async () => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } })
  const mp = await ctx.newPage()
  attachErrors(mp, 'mobile-tasks')
  await sessionLogin(mp, 'admin', 'admin123')
  await mp.goto(`${BASE}/kb/${kbId}/tasks`, { waitUntil: 'networkidle' })
  await mp.waitForTimeout(800)
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (overflow > 2) throw new Error(`移动端任务页横向溢出 ${overflow}px`)
  await mp.screenshot({ path: `${OUT}parsing_phase5_boundary_mobile_tasks.png` })
  await ctx.close()
})

for (const kbId2 of createdKbs) { await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined) }
await browser.close()
const failed = results.filter((r) => r.status === 'FAIL')
writeFileSync(`${OUT}parsing_phase5_boundary_results.json`, JSON.stringify({ total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }, null, 2))
console.log(`PHASE5_BOUNDARY_DONE total=${results.length} passed=${results.length - failed.length} failed=${failed.length}`)
if (failed.length) process.exitCode = 1
