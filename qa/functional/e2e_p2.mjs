// L3 功能场景测试（Playwright E2E，P2 工作空间/群组/API Key/导出）
import { chromium } from '/tmp/uitools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'

const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const results = []
const errors = []
const createdUsers = []
const createdKbs = []
const createdKeys = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
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

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await context.newPage()
attachErrors(page, 'desktop')
const token = await adminToken()

// ---------- M13 工作空间 ----------
await scenario('L3M13-01', 'M13', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/workspaces`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.getByText('新建工作空间').click()
  await page.waitForTimeout(300)
  await page.fill('#ws-name', `E2E工作空间_${stamp}`)
  await page.fill('#ws-code', `e2e_ws_${stamp}`)
  await page.getByRole('button', { name: '创建工作空间' }).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('工作空间已创建').first().isVisible().catch(() => false))) {
    throw new Error('创建工作空间未提示成功')
  }
  if (!(await page.getByText(`E2E工作空间_${stamp}`).first().isVisible().catch(() => false))) {
    throw new Error('工作空间未出现在列表')
  }
  await page.screenshot({ path: `${OUT}p2_workspaces.png` })
})

await scenario('L3M13-02', 'M13', async () => {
  const member = `ws_member_${stamp}`
  const created = await api('POST', '/users', {
    username: member, password: 'Test@1234', role_codes: ['member'], full_name: '工作空间成员',
  }, token)
  createdUsers.push(created.body.data.id)
  await page.goto(`${BASE}/workspaces`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: `E2E工作空间_${stamp}` })
  await row.getByTitle('成员').click()
  await page.waitForTimeout(500)
  await page.fill('#ws-invite', member)
  await page.getByRole('button', { name: '添加成员' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('成员已添加').first().isVisible().catch(() => false))) {
    throw new Error('添加工作空间成员未提示成功')
  }
  await page.screenshot({ path: `${OUT}p2_workspace_members.png` })
  await page.getByRole('button', { name: '关闭' }).click()
})

// ---------- M14 群组并集授权 ----------
await scenario('L3M14-01', 'M14', async () => {
  const grpMember = `grp_member_${stamp}`
  const created = await api('POST', '/users', {
    username: grpMember, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  const kb = await api('POST', '/kb', {
    name: `E2E授权库_${stamp}`, domain_code: 'general',
  }, token)
  createdKbs.push(kb.body.data.id)

  await page.goto(`${BASE}/workspaces`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: `E2E工作空间_${stamp}` })
  await row.getByTitle('群组').click()
  await page.waitForTimeout(500)
  await page.fill('#grp-name', 'E2E研发组')
  await page.fill('#grp-code', `e2e_grp_${stamp}`)
  await page.getByRole('button', { name: '创建群组' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('群组已创建').first().isVisible().catch(() => false))) {
    throw new Error('创建群组未提示成功')
  }
  await page.screenshot({ path: `${OUT}p2_groups.png` })

  // 群组成员（限定在群组对话框内，避免命中工作台行的“成员”图标按钮）
  const grpDialog = page.getByRole('dialog').filter({ hasText: '群组管理' })
  await grpDialog.getByRole('button', { name: '成员' }).click()
  await page.waitForTimeout(400)
  await page.getByPlaceholder('输入用户名').fill(grpMember)
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('群组成员已添加').first().isVisible().catch(() => false))) {
    throw new Error('添加群组成员未提示成功')
  }
  await page
    .getByRole('dialog')
    .filter({ hasText: '群组成员' })
    .getByRole('button', { name: '关闭' })
    .click()
  await page.waitForTimeout(300)

  // 知识库授权
  await grpDialog.getByRole('button', { name: '知识库授权' }).click()
  await page.waitForTimeout(600)
  await page.locator('select').first().selectOption({ label: `E2E授权库_${stamp}` })
  await page.locator('select').nth(1).selectOption('editor')
  await page.getByRole('button', { name: '授权', exact: true }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('群组授权已更新').first().isVisible().catch(() => false))) {
    throw new Error('群组授权未提示成功')
  }
  await page.screenshot({ path: `${OUT}p2_kb_grant.png` })
  await page
    .getByRole('dialog')
    .filter({ hasText: '知识库授权：' })
    .getByRole('button', { name: '关闭' })
    .click()

  // 并集生效：成员经群组可见该知识库且 my_role=editor
  const login = await api('POST', '/auth/login', { username: grpMember, password: 'Test@1234' })
  const gtoken = login.body.data.access_token
  const listed = await api('GET', `/kb?keyword=${encodeURIComponent(`E2E授权库_${stamp}`)}`, null, gtoken)
  const item = listed.body.data.items.find((i) => i.name === `E2E授权库_${stamp}`)
  if (!item || item.my_role !== 'editor') {
    throw new Error(`并集授权未生效：${JSON.stringify(item)}`)
  }
})

// ---------- M15 API 密钥 ----------
await scenario('L3M15-01', 'M15', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/api-keys`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.getByText('新建密钥').click()
  await page.waitForTimeout(300)
  await page.fill('#key-name', `E2E密钥_${stamp}`)
  await page.fill('#key-scopes', 'user.view')
  await page.getByRole('button', { name: '创建密钥' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('此密钥不会再次展示').first().isVisible().catch(() => false))) {
    throw new Error('创建密钥未展示一次性密钥')
  }
  const secretText = await page.locator('.font-mono').last().innerText()
  if (!secretText.startsWith('hd_')) throw new Error('密钥格式不正确')
  await page.screenshot({ path: `${OUT}p2_api_keys.png` })
  await page.getByRole('button', { name: '我已保存' }).click()
  await page.waitForTimeout(500)
  const list = await api('GET', '/api-keys', null, token)
  const createdKey = list.body.data.find((k) => k.name === `E2E密钥_${stamp}`)
  if (!createdKey) throw new Error('列表未显示新密钥')
  createdKeys.push(createdKey.id)
  await page.getByRole('button', { name: '撤销' }).first().click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('API Key 已撤销').first().isVisible().catch(() => false))) {
    throw new Error('撤销密钥未提示成功')
  }
})

// ---------- M16 审计导出 ----------
await scenario('L3M16-01', 'M16', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/admin/audit-logs`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const downloadPromise = page.waitForEvent('download', { timeout: 15000 })
  await page.getByRole('button', { name: '导出 CSV' }).click()
  const download = await downloadPromise
  const filename = download.suggestedFilename()
  if (!filename.endsWith('.csv')) throw new Error(`导出文件名异常：${filename}`)
  await download.saveAs(`${OUT}p2_audit_export.csv`)
  const fs = await import('node:fs')
  const content = fs.readFileSync(`${OUT}p2_audit_export.csv`, 'utf-8')
  if (!content.includes('created_at') || !content.includes('action')) {
    throw new Error('导出的 CSV 缺少表头')
  }
})

// ---------- 清理 ----------
for (const keyId of createdKeys) {
  await api('DELETE', `/api-keys/${keyId}`, null, token).catch(() => undefined)
}
for (const kbId of createdKbs) {
  await api('DELETE', `/kb/${kbId}`, null, token).catch(() => undefined)
}
for (const userId of createdUsers) {
  await api('DELETE', `/users/${userId}`, null, token).catch(() => undefined)
}
const wsList = await api('GET', `/workspaces?keyword=${encodeURIComponent(`E2E工作空间_${stamp}`)}`, null, token)
for (const ws of wsList.body?.data?.items ?? []) {
  await api('DELETE', `/workspaces/${ws.id}`, null, token).catch(() => undefined)
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
writeFileSync(`${OUT}p2_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`P2_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
