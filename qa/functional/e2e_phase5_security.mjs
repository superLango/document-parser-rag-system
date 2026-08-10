// L5 安全渗透测试（Playwright E2E，Phase 5 权限 UI 与 API 越权）
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
const createdUsers = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  return { status: resp.status, body: await resp.json().catch(() => null) }
}
async function adminToken() {
  let r = await api('POST', '/auth/login', { username: 'admin', password: 'admin123' })
  for (let i = 0; (r.status !== 200 || !r.body?.data) && i < 8; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3000))
    r = await api('POST', '/auth/login', { username: 'admin', password: 'admin123' })
  }
  if (r.status !== 200 || !r.body?.data) throw new Error(`admin login failed ${r.status}`)
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
const kb = await api('POST', '/kb', { name: `E2E-P5S_${stamp}`, domain_code: 'general' }, token)
const kbId = kb.body.data.id
createdKbs.push(kbId)

const viewerName = `p5_viewer_${stamp}`
const vuser = await api('POST', '/users', { username: viewerName, password: 'Test@1234', role_codes: ['member'], full_name: 'P5 查看者' }, token)
createdUsers.push(vuser.body.data.id)
await api('POST', `/kb/${kbId}/invitations`, { username: viewerName, role: 'viewer' }, token)
const vlogin = await api('POST', '/auth/login', { username: viewerName, password: 'Test@1234' })
const viewerToken = vlogin.body.data.access_token
const mine = await api('GET', '/kb/invitations/mine', null, viewerToken)
await api('POST', `/kb/invitations/${mine.body.data.find((i) => i.kb_id === kbId).token}/accept`, null, viewerToken)

const form = new FormData()
form.append('file', new Blob([readFileSync(SAMPLE)], { type: 'application/pdf' }), '安全样本.pdf')
const up = await fetch(`${API}/kb/${kbId}/documents`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form })
const docId = (await up.json()).data.document.id

const outsiderName = `p5_outsider_${stamp}`
await api('POST', '/users', { username: outsiderName, password: 'Test@1234', role_codes: ['member'] }, token)
const ologin = await api('POST', '/auth/login', { username: outsiderName, password: 'Test@1234' })
const outsiderToken = ologin.body.data.access_token

await scenario('L5M21-01', 'M21', async () => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const vp = await ctx.newPage()
  attachErrors(vp, 'viewer')
  await sessionLogin(vp, viewerName, 'Test@1234')
  await vp.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await vp.waitForTimeout(900)
  if ((await vp.locator('[data-testid="open-upload"]').count()) !== 0) throw new Error('viewer 不应看到上传按钮')
  if ((await vp.locator('[data-testid^="delete-"]').count()) !== 0) throw new Error('viewer 不应看到删除按钮')
  if ((await vp.locator('[data-testid^="reparse-"]').count()) !== 0) throw new Error('viewer 不应看到重解析按钮')
  if (!(await vp.getByText('安全样本.pdf').first().isVisible().catch(() => false))) throw new Error('viewer 应看到文档列表')
  await vp.screenshot({ path: `${OUT}parsing_phase5_security_viewer.png` })
  await ctx.close()
})

await scenario('L5M21-02', 'M21', async () => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const vp = await ctx.newPage()
  await sessionLogin(vp, viewerName, 'Test@1234')
  await vp.goto(`${BASE}/kb/${kbId}/tasks`, { waitUntil: 'networkidle' })
  await vp.waitForTimeout(900)
  if ((await vp.locator('[data-testid^="task-row-"]').count()) === 0) throw new Error('viewer 应看到任务列表')
  await ctx.close()
})

await scenario('L5M21-03', 'M21', async () => {
  const resp = await api('GET', `/kb/${kbId}/documents/tasks`, null, outsiderToken)
  if (resp.status !== 403) throw new Error(`外部人 tasks 应 403，实际 ${resp.status}`)
  const layoutResp = await api('GET', `/kb/${kbId}/documents/${docId}/layout`, null, outsiderToken)
  if (layoutResp.status !== 403) throw new Error(`外部人 layout 应 403，实际 ${layoutResp.status}`)
})

await scenario('L5M21-04', 'M21', async () => {
  const resp = await api('POST', `/kb/${kbId}/documents/${docId}/reparse`, null, viewerToken)
  if (resp.status !== 403) throw new Error(`viewer reparse 应 403，实际 ${resp.status}`)
})

await scenario('L5M21-05', 'M21', async () => {
  if (errors.length > 0) throw new Error(`存在控制台错误：${JSON.stringify(errors)}`)
})

for (const kbId2 of createdKbs) { await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined) }
for (const uid of createdUsers) { await api('DELETE', `/users/${uid}`, null, token).catch(() => undefined) }
await browser.close()
const failed = results.filter((r) => r.status === 'FAIL')
writeFileSync(`${OUT}parsing_phase5_security_results.json`, JSON.stringify({ total: results.length, passed: results.length - failed.length, failed: failed.length, consoleErrors: errors, results }, null, 2))
console.log(`PHASE5_SECURITY_DONE total=${results.length} passed=${results.length - failed.length} failed=${failed.length}`)
if (failed.length) process.exitCode = 1
