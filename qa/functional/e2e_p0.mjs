// L3 功能场景测试（Playwright E2E，P0 RBAC）
// 运行：cd qa/functional && node e2e_p0.mjs
import { chromium } from '/tmp/uitools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'

const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const results = []
const errors = []
const createdUsers = []
const createdRoles = []
const stamp = Date.now().toString(36)

async function api(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  return { status: resp.status, body: await resp.json() }
}

async function adminToken() {
  const r = await api('POST', '/auth/login', { username: 'admin', password: 'admin123' })
  return r.body.data.access_token
}

function attachErrors(page, label) {
  page.on('pageerror', (e) => errors.push(`[${label}] pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    // 负向用例（错误密码/限流）会刻意产生 401/429 资源加载日志，属预期
    if (/401|429/.test(m.text())) return
    errors.push(`[${label}] console: ${m.text()}`)
  })
}

async function uiLogin(page, username, password) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.fill('#username', username)
  await page.fill('#password', password)
  await page.click('button[type="submit"]')
  await page.waitForURL(`${BASE}/`, { timeout: 15000 })
  await page.waitForTimeout(800)
}

async function sessionLogin(page, username, password) {
  // 通过 API 登录并注入 localStorage，避免触发 5 次/分钟登录限流
  let r = await api('POST', '/auth/login', { username, password })
  for (let i = 0; r.status === 429 && i < 6; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3000))
    r = await api('POST', '/auth/login', { username, password })
  }
  if (r.status !== 200) throw new Error(`会话登录失败 ${r.status}: ${JSON.stringify(r.body)}`)
  const { access_token: access, refresh_token: refresh } = r.body.data
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(([a, rf]) => {
    localStorage.setItem('access_token', a)
    localStorage.setItem('refresh_token', rf || '')
  }, [access, refresh])
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

// ---------- M1 认证登录 ----------
await scenario('L3M1-01', 'M1', async () => {
  await uiLogin(page, 'admin', 'admin123')
  if (!(await page.getByText('欢迎回来，admin').first().isVisible().catch(() => false))) {
    throw new Error('登录后未进入工作台')
  }
})

await scenario('L3M1-02', 'M1', async () => {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.fill('#username', 'admin')
  await page.fill('#password', 'wrong-password')
  await page.click('button[type="submit"]')
  await page.waitForTimeout(600)
  if (!(await page.getByText('登录失败').first().isVisible().catch(() => false))) {
    throw new Error('错误密码未提示登录失败')
  }
})

await scenario('L3M1-03', 'M1', async () => {
  await uiLogin(page, 'admin', 'admin123')
  await page.locator('header button').first().click()
  await page.getByText('退出登录').click()
  await page.waitForURL('**/login', { timeout: 10000 })
})

// ---------- M5 工作台 ----------
await scenario('L3M5-01', 'M5', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}p0_dashboard.png` })
  for (const t of ['工作台', '用户总数', '今日操作', '近 7 天登录趋势']) {
    if (!(await page.getByText(t, { exact: false }).first().isVisible().catch(() => false))) {
      throw new Error(`工作台缺少内容：${t}`)
    }
  }
  const fit = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  if (fit) throw new Error('工作台存在横向溢出')
})

await scenario('L3M5-02', 'M5', async () => {
  const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true })
  const mpage = await mob.newPage()
  attachErrors(mpage, 'mobile')
  await sessionLogin(mpage, 'admin', 'admin123')
  await mpage.waitForTimeout(900)
  const fit = await mpage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  await mpage.screenshot({ path: `${OUT}p0_dashboard_mobile.png` })
  await mob.close()
  if (fit) throw new Error('移动端工作台存在横向溢出')
})

// ---------- M8 路由与菜单权限 ----------
await scenario('L3M8-01', 'M8', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  for (const t of ['用户管理', '角色管理', '审计日志']) {
    if (!(await page.getByRole('link', { name: t }).isVisible().catch(() => false))) {
      throw new Error(`管理员菜单缺少：${t}`)
    }
  }
})

await scenario('L3M8-02', 'M8', async () => {
  const uname = `member_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'], full_name: 'E2E成员',
  }, token)
  if (created.status !== 200) throw new Error(`创建成员失败 ${created.status}`)
  createdUsers.push(created.body.data.id)
  await sessionLogin(page, uname, 'Test@1234')
  for (const t of ['用户管理', '角色管理', '审计日志']) {
    const visible = await page.getByRole('link', { name: t }).isVisible().catch(() => false)
    if (visible) throw new Error(`成员不应看到菜单：${t}`)
  }
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  if (!(await page.getByText('403 · 权限不足').isVisible().catch(() => false))) {
    throw new Error('成员访问用户管理未跳转 403')
  }
  await page.screenshot({ path: `${OUT}p0_forbidden.png` })
})

// ---------- M4 用户管理 ----------
await scenario('L3M4-01', 'M4', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.getByText('新建用户').click()
  await page.waitForTimeout(300)
  const uname = `ui_user_${stamp}`
  await page.fill('#u-username', uname)
  await page.fill('#u-password', 'Test@1234')
  await page.fill('#u-full-name', 'UI用户')
  const memberBox = page.locator('label', { hasText: '普通成员' }).locator('input')
  await memberBox.check()
  await page.getByRole('button', { name: '创建用户' }).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('用户已创建').first().isVisible().catch(() => false))) {
    throw new Error('新建用户未提示成功')
  }
  if (!(await page.getByText(uname).first().isVisible().catch(() => false))) {
    throw new Error('新建用户未出现在列表')
  }
  await page.screenshot({ path: `${OUT}p0_users.png` })
})

await scenario('L3M4-02', 'M4', async () => {
  const uname = `edit_user_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'], full_name: '待编辑',
  }, token)
  createdUsers.push(created.body.data.id)
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: uname })
  await row.getByTitle('编辑').click()
  await page.waitForTimeout(300)
  await page.fill('#u-full-name', '已编辑用户')
  await page.getByRole('button', { name: '保存' }).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('用户已更新').first().isVisible().catch(() => false))) {
    throw new Error('编辑用户未提示成功')
  }
})

await scenario('L3M4-03', 'M4', async () => {
  const uname = `toggle_user_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: uname })
  await row.getByTitle('禁用').click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('已禁用该用户').first().isVisible().catch(() => false))) {
    throw new Error('禁用用户未提示成功')
  }
  const loginFail = await api('POST', '/auth/login', { username: uname, password: 'Test@1234' })
  if (loginFail.status !== 401) throw new Error('禁用后仍可登录')
  await row.getByTitle('启用').click()
  await page.waitForTimeout(700)
})

await scenario('L3M4-04', 'M4', async () => {
  const uname = `reset_user_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: uname })
  await row.getByTitle('重置密码').click()
  await page.waitForTimeout(300)
  await page.fill('#reset_password', 'NewPass@5678')
  await page.getByRole('button', { name: '确认重置' }).click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('密码已重置').first().isVisible().catch(() => false))) {
    throw new Error('重置密码未提示成功')
  }
  const ok = await api('POST', '/auth/login', { username: uname, password: 'NewPass@5678' })
  if (ok.status !== 200) throw new Error('重置后的新密码无法登录')
})

await scenario('L3M4-05', 'M4', async () => {
  const uname = `del_user_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: uname })
  await row.getByTitle('删除').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('用户已删除').first().isVisible().catch(() => false))) {
    throw new Error('删除用户未提示成功')
  }
})

// ---------- M3 角色管理 ----------
await scenario('L3M3-01', 'M3', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/admin/roles`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  for (const t of ['超级管理员', '管理员', '普通成员', '待审批']) {
    if (!(await page.getByText(t, { exact: false }).first().isVisible().catch(() => false))) {
      throw new Error(`角色列表缺少：${t}`)
    }
  }
  await page.screenshot({ path: `${OUT}p0_roles.png` })
})

await scenario('L3M3-02', 'M3', async () => {
  const code = `ui_role_${stamp}`
  await page.getByText('新建角色').click()
  await page.waitForTimeout(300)
  await page.fill('#r-code', code)
  await page.fill('#r-name', 'UI自定义角色')
  await page.getByRole('button', { name: '创建角色' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('角色已创建').first().isVisible().catch(() => false))) {
    throw new Error('新建角色未提示成功')
  }
  if (!(await page.getByText(code).first().isVisible().catch(() => false))) {
    throw new Error('新建角色未出现在列表')
  }
  const list = await api('GET', '/roles', null, token)
  const role = list.body.data.find((r) => r.code === code)
  if (!role) throw new Error('API 中未找到新角色')
  createdRoles.push(role.id)
})

await scenario('L3M3-03', 'M3', async () => {
  const list = await api('GET', '/roles', null, token)
  const role = list.body.data.find((r) => r.code === `ui_role_${stamp}`)
  if (!role) throw new Error('角色不存在')
  await page.goto(`${BASE}/admin/roles`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: role.code })
  await row.getByTitle('权限矩阵').click()
  await page.waitForTimeout(300)
  const userView = page.locator('label', { hasText: '查看用户' }).locator('input')
  const auditView = page.locator('label', { hasText: '查看审计' }).locator('input')
  await userView.check()
  await auditView.check()
  await page.getByRole('button', { name: '保存矩阵' }).click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('权限矩阵已保存').first().isVisible().catch(() => false))) {
    throw new Error('权限矩阵保存未提示成功')
  }
  await page.screenshot({ path: `${OUT}p0_roles_matrix.png` })
  const detail = await api('GET', `/roles/${role.id}`, null, token)
  const perms = detail.body.data.permissions
  if (!perms.includes('user.view') || !perms.includes('audit.view')) {
    throw new Error(`矩阵未生效：${JSON.stringify(perms)}`)
  }
})

await scenario('L3M3-04', 'M3', async () => {
  const list = await api('GET', '/roles', null, token)
  const role = list.body.data.find((r) => r.code === `ui_role_${stamp}`)
  if (!role) throw new Error('待删除角色不存在')
  await page.goto(`${BASE}/admin/roles`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const row = page.locator('tr', { hasText: role.code })
  await row.getByTitle('删除').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForTimeout(700)
  if (!(await page.getByText('角色已删除').first().isVisible().catch(() => false))) {
    throw new Error('删除角色未提示成功')
  }
})

// ---------- M7 个人中心 ----------
await scenario('L3M7-01', 'M7', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  if (!(await page.getByText('超级管理员').first().isVisible().catch(() => false))) {
    throw new Error('个人中心未展示角色徽章')
  }
  for (const t of ['账号状态', '最近登录', '注册时间', '密码安全']) {
    if (!(await page.getByText(t, { exact: false }).first().isVisible().catch(() => false))) {
      throw new Error(`个人中心缺少区块：${t}`)
    }
  }
  await page.screenshot({ path: `${OUT}p0_profile.png` })
})

await scenario('L3M7-02', 'M7', async () => {
  const uname = `profile_user_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  await sessionLogin(page, uname, 'Test@1234')
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.fill('#full_name', '<script>alert(1)</script>')
  await page.fill('#avatar', 'https://example.com/avatar.png')
  await page.getByRole('button', { name: '保存资料' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('资料已更新').first().isVisible().catch(() => false))) {
    throw new Error('资料更新未提示成功')
  }
  const text = await page.locator('body').innerText()
  if (!text.includes('<script>alert(1)</script>')) {
    throw new Error('XSS 内容未按文本展示')
  }
  if (errors.some((e) => e.includes('pageerror'))) {
    throw new Error('XSS 内容触发了页面错误')
  }
})

await scenario('L3M7-03', 'M7', async () => {
  const uname = `pwd_user_${stamp}`
  const created = await api('POST', '/users', {
    username: uname, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  await sessionLogin(page, uname, 'Test@1234')
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.fill('#old_password', 'Test@1234')
  await page.fill('#new_password', 'NewPass@5678')
  await page.fill('#confirm', 'NewPass@5678')
  await page.getByRole('button', { name: '修改密码' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('密码修改成功').first().isVisible().catch(() => false))) {
    throw new Error('修改密码未提示成功')
  }
  const old = await api('POST', '/auth/login', { username: uname, password: 'Test@1234' })
  const fresh = await api('POST', '/auth/login', { username: uname, password: 'NewPass@5678' })
  if (old.status !== 401 || fresh.status !== 200) {
    throw new Error('修改密码后登录校验失败')
  }
})

// ---------- M6 审计日志 ----------
await scenario('L3M6-01', 'M6', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/admin/audit-logs`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  if (!(await page.getByText('审计日志').first().isVisible().catch(() => false))) {
    throw new Error('审计日志页未渲染')
  }
  const rows = await page.locator('tbody tr').count()
  if (rows === 0) throw new Error('审计日志无数据行')
  await page.screenshot({ path: `${OUT}p0_audit.png` })
})

// ---------- 清理 ----------
for (const roleId of createdRoles) {
  await api('DELETE', `/roles/${roleId}`, null, token).catch(() => undefined)
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
writeFileSync(`${OUT}p0_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
