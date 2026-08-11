// L3 功能场景测试（Playwright E2E，Phase 2 文档解析：上传/预览/重解析/失败/权限 UI）
import { chromium } from '/tmp/uitools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const SAMPLE = join(__dirname, '../../test_doc/LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf')
const BROKEN = '/tmp/phase2_broken.pdf'
writeFileSync(BROKEN, '%PDF-1.4 this is broken content')

const results = []
const errors = []
const createdKbs = []
const createdUsers = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token, raw = false) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
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

async function waitDocStatus(token, kbId, docId, target, timeout = 40000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const r = await api('GET', `/kb/${kbId}/documents/${docId}`, null, token)
    if (r.status === 200 && (r.body.data.status === target || r.body.data.process_status === target)) {
      return r.body.data
    }
    await new Promise((resolve) => setTimeout(resolve, 400))
  }
  throw new Error(`文档 ${docId} 未在 ${timeout}ms 内达到 ${target}`)
}

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await context.newPage()
attachErrors(page, 'desktop')
const token = await adminToken()

// 准备：创建知识库 + viewer 用户
const kbResp = await api('POST', '/kb', {
  name: `E2E解析_${stamp}`, description: 'Phase 2 文档解析', domain_code: 'general',
}, token)
const kbId = kbResp.body.data.id
createdKbs.push(kbId)

const viewerName = `parse_viewer_${stamp}`
const vuser = await api('POST', '/users', {
  username: viewerName, password: 'Test@1234', role_codes: ['member'], full_name: '解析查看者',
}, token)
createdUsers.push(vuser.body.data.id)
await api('POST', `/kb/${kbId}/invitations`, { username: viewerName, role: 'viewer' }, token)
const vlogin = await api('POST', '/auth/login', { username: viewerName, password: 'Test@1234' })
const viewerToken = vlogin.body.data.access_token
await api('POST', `/kb/invitations/${(await api('GET', '/kb/invitations/mine', null, viewerToken)).body.data.find((i) => i.kb_id === kbId).token}/accept`, null, viewerToken)

// ---------- L3M18-01 上传 → 完成 → Markdown 预览 ----------
await scenario('L3M18-01', 'M18', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', SAMPLE)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  await page.waitForTimeout(1200)
  if (!(await page.getByText('文档已上传').first().isVisible().catch(() => false))) {
    throw new Error('上传未提示成功')
  }
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  if (!doc) throw new Error('文档未出现在列表')
  await api('POST', `/kb/${kbId}/documents/${doc.id}/start`, null, token)
  await waitDocStatus(token, kbId, doc.id, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  if (!(await page.getByText('已完成').first().isVisible().catch(() => false))) {
    throw new Error('列表未显示已完成状态')
  }
  await page.screenshot({ path: `${OUT}parsing_phase2_documents.png` })
  await page.locator(`[data-testid="preview-${doc.id}"]`).click()
  await page.waitForTimeout(800)
  const pre = page.locator('pre')
  if (!(await pre.isVisible().catch(() => false))) throw new Error('Markdown 预览未打开')
  const text = await pre.innerText()
  if (!text.includes('<!-- page: 1 -->')) throw new Error('预览缺少分页标记')
  if (!text.includes('优质 GH4169')) throw new Error('预览缺少正文内容')
  await page.screenshot({ path: `${OUT}parsing_phase2_markdown_preview.png` })
  await page.getByRole('button', { name: '关闭' }).click()
})

// ---------- L3M18-02 重新解析 ----------
await scenario('L3M18-02', 'M18', async () => {
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename.includes('LSAM-JD01-0016'))
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator(`[data-testid="reparse-${doc.id}"]`).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('重新解析已启动').first().isVisible().catch(() => false))) {
    throw new Error('重新解析未提示成功')
  }
  await waitDocStatus(token, kbId, doc.id, 'completed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (!(await page.getByText('已完成').first().isVisible().catch(() => false))) {
    throw new Error('重解析后未恢复已完成')
  }
  await page.screenshot({ path: `${OUT}parsing_phase2_reparse.png` })
})

// ---------- L3M18-03 损坏 PDF → 失败 ----------
await scenario('L3M18-03', 'M18', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('[data-testid="open-upload"]').click()
  await page.waitForTimeout(300)
  await page.setInputFiles('[data-testid="upload-input"]', BROKEN)
  await page.waitForTimeout(400)
  await page.locator('[data-testid="confirm-upload"]').click()
  await page.waitForTimeout(1200)
  await page.waitForTimeout(1200)
  const list = await api('GET', `/kb/${kbId}/documents?page=1&page_size=20`, null, token)
  const doc = list.body.data.items.find((d) => d.filename === 'phase2_broken.pdf')
  if (!doc) throw new Error('损坏文件未上传成功')
  await api('POST', `/kb/${kbId}/documents/${doc.id}/start`, null, token)
  await waitDocStatus(token, kbId, doc.id, 'failed')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  if (!(await page.getByText('失败').first().isVisible().catch(() => false))) {
    throw new Error('列表未显示失败状态')
  }
  await page.screenshot({ path: `${OUT}parsing_phase2_failed.png` })
})

// ---------- L3M18-04 viewer 权限 UI ----------
await scenario('L3M18-04', 'M18', async () => {
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const p2 = await ctx2.newPage()
  attachErrors(p2, 'viewer')
  await sessionLogin(p2, viewerName, 'Test@1234')
  await p2.goto(`${BASE}/kb/${kbId}/documents`, { waitUntil: 'networkidle' })
  await p2.waitForTimeout(900)
  if ((await p2.getByRole('button', { name: '上传 PDF' }).count()) !== 0) {
    throw new Error('viewer 不应看到上传按钮')
  }
  if ((await p2.locator('[data-testid^="reparse-"]').count()) !== 0) {
    throw new Error('viewer 不应看到重新解析按钮')
  }
  if (!(await p2.getByText('已完成').first().isVisible().catch(() => false))) {
    throw new Error('viewer 应看到文档列表')
  }
  await p2.screenshot({ path: `${OUT}parsing_phase2_viewer.png` })
  await ctx2.close()
})

// ---------- 清理 ----------
for (const kbId2 of createdKbs) {
  await api('DELETE', `/kb/${kbId2}`, null, token).catch(() => undefined)
}
for (const userId of createdUsers) {
  await api('DELETE', `/users/${userId}`, null, token).catch(() => undefined)
}

await browser.close()

const failed = results.filter((r) => r.status === 'FAIL')
const summary = {
  total: results.length,
  passed: results.length - failed.length,
  failed: failed.length,
  consoleErrors: errors,
  results,
}
writeFileSync(`${OUT}parsing_phase2_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`PHASE2_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
