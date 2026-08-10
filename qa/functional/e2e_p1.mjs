// L3 功能场景测试（Playwright E2E，P1 知识库 ACL / 邀请 / 待审批）
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
  if (r.status !== 200) throw new Error(`admin login failed ${r.status}`)
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

// ---------- M10 知识库列表与创建 ----------
await scenario('L3M10-01', 'M10', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.getByText('新建知识库').click()
  await page.waitForTimeout(300)
  await page.fill('#kb-name', `E2E知识库_${stamp}`)
  await page.fill('#kb-desc', 'P1 功能验证')
  await page.getByRole('button', { name: '创建知识库' }).click()
  await page.waitForTimeout(900)
  if (!(await page.getByText('知识库已创建').first().isVisible().catch(() => false))) {
    throw new Error('创建知识库未提示成功')
  }
  if (!(await page.getByText(`E2E知识库_${stamp}`).first().isVisible().catch(() => false))) {
    throw new Error('知识库未出现在列表')
  }
  await page.screenshot({ path: `${OUT}p1_kb_list.png` })
  const list = await api('GET', '/kb?keyword=' + encodeURIComponent(`E2E知识库_${stamp}`), null, token)
  createdKbs.push(list.body.data.items[0].id)
})

// ---------- M10 成员管理 + M11 邀请接受 ----------
await scenario('L3M10-02', 'M10', async () => {
  const invitee = `kb_invitee_${stamp}`
  const created = await api('POST', '/users', {
    username: invitee, password: 'Test@1234', role_codes: ['member'], full_name: '邀请对象',
  }, token)
  createdUsers.push(created.body.data.id)

  await page.goto(`${BASE}/kb`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const card = page.locator('main .rounded-xl', { hasText: `E2E知识库_${stamp}` }).first()
  await card.getByRole('button', { name: '成员' }).click()
  await page.waitForURL('**/kb/*/members', { timeout: 10000 })
  await page.waitForTimeout(600)
  const combobox = page.getByPlaceholder('搜索系统现有用户')
  await combobox.click()
  await combobox.fill(invitee)
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: new RegExp(invitee) }).first().click()
  await page.getByRole('button', { name: '添加成员' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('邀请已发送').first().isVisible().catch(() => false))) {
    throw new Error('邀请发送未提示成功')
  }
  await page.screenshot({ path: `${OUT}p1_kb_members.png` })

  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const p2 = await ctx2.newPage()
  attachErrors(p2, 'invitee')
  await sessionLogin(p2, invitee, 'Test@1234')
  await p2.goto(`${BASE}/kb/invitations`, { waitUntil: 'networkidle' })
  await p2.waitForTimeout(800)
  if (!(await p2.getByText(`E2E知识库_${stamp}`).first().isVisible().catch(() => false))) {
    throw new Error('邀请页未显示知识库邀请')
  }
  await p2.screenshot({ path: `${OUT}p1_invitations.png` })
  await p2.getByRole('button', { name: '接受邀请' }).click()
  await p2.waitForTimeout(900)
  if (!(await p2.getByText('已加入知识库').first().isVisible().catch(() => false))) {
    throw new Error('接受邀请未提示成功')
  }
  const mine = await api('GET', '/kb/invitations/mine', null, token)
  // 邀请人 token 查询自己邀请，接受者已接受后该列表应为空
  const detail = await api('GET', `/kb/${createdKbs[0]}`, null, token)
  if (detail.body.data.member_count < 2) {
    throw new Error(`成员数未增加：${detail.body.data.member_count}`)
  }
  await ctx2.close()
})

// ---------- M10 新建时初始成员管理 ----------
await scenario('L3M10-04', 'M10', async () => {
  const invitee = `kb_seed_member_${stamp}`
  const created = await api('POST', '/users', {
    username: invitee, password: 'Test@1234', role_codes: ['member'], full_name: '初始成员',
  }, token)
  createdUsers.push(created.body.data.id)

  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.getByText('新建知识库').click()
  await page.waitForTimeout(300)
  await page.fill('#kb-name', `E2E初始成员库_${stamp}`)
  await page.fill('#kb-desc', '创建时邀请成员')
  const memberInput = page.getByPlaceholder('输入用户名搜索成员')
  await memberInput.click()
  await memberInput.fill(invitee)
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: new RegExp(invitee) }).first().click()
  await page.locator('select').first().selectOption('admin')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.waitForTimeout(300)
  if (!(await page.getByText(`@${invitee}`).first().isVisible().catch(() => false))) {
    throw new Error('初始成员未加入待邀请列表')
  }
  await page.getByRole('button', { name: '创建知识库' }).click()
  await page.waitForTimeout(1000)
  if (!(await page.getByText('已向 1 位成员发送邀请').first().isVisible().catch(() => false))) {
    throw new Error('创建时邀请未提示成功')
  }
  await page.screenshot({ path: `${OUT}p1_kb_cards.png` })
  const list = await api('GET', '/kb?keyword=' + encodeURIComponent(`E2E初始成员库_${stamp}`), null, token)
  createdKbs.push(list.body.data.items[0].id)

  // 接收方在我的邀请中可见
  const ctx3 = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const p3 = await ctx3.newPage()
  attachErrors(p3, 'seed-invitee')
  await sessionLogin(p3, invitee, 'Test@1234')
  await p3.goto(`${BASE}/kb/invitations`, { waitUntil: 'networkidle' })
  await p3.waitForTimeout(800)
  if (!(await p3.getByText(`E2E初始成员库_${stamp}`).first().isVisible().catch(() => false))) {
    throw new Error('初始成员邀请未出现在我的邀请')
  }
  await ctx3.close()
})

// ---------- M10 KB 详情：概览 / 成员权限管理 / 外部联动 ----------
const detailKbId = () => createdKbs[createdKbs.length - 1]

await scenario('L3M10-06', 'M10', async () => {
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/kb`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  await page.getByText(`E2E初始成员库_${stamp}`).click()
  await page.waitForURL(`**/kb/${detailKbId()}`, { timeout: 10000 })
  await page.waitForTimeout(800)
  for (const t of ['知识库概览', '活跃成员', '文档解析', '知识图谱', '知识问答', '知识库成员']) {
    if (!(await page.getByText(t, { exact: false }).first().isVisible().catch(() => false))) {
      throw new Error(`KB 概览缺少：${t}`)
    }
  }
  await page.screenshot({ path: `${OUT}p1_kb_overview.png` })
})

await scenario('L3M10-07', 'M10', async () => {
  await page.goto(`${BASE}/kb/${detailKbId()}/members`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  if (!(await page.getByText(`@kb_seed_member_${stamp}`).first().isVisible().catch(() => false))) {
    throw new Error('成员页未显示初始成员')
  }
  if (!(await page.getByText('待接受').first().isVisible().catch(() => false))) {
    throw new Error('成员页未显示待接受状态')
  }
  const invitee = `kb_seed_member_${stamp}`
  const login = await api('POST', '/auth/login', { username: invitee, password: 'Test@1234' })
  const itoken = login.body.data.access_token
  const mine = await api('GET', '/kb/invitations/mine', null, itoken)
  const inv = mine.body.data.find((i) => i.kb_id === detailKbId())
  if (!inv) throw new Error('初始成员邀请不存在')
  await api('POST', `/kb/invitations/${inv.token}/accept`, null, itoken)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (!(await page.getByText('已加入').first().isVisible().catch(() => false))) {
    throw new Error('接受后成员页未显示已加入')
  }
  const memberRow = page.locator('div.px-4', { hasText: `@${invitee}` }).last()
  await memberRow.locator('select').selectOption('editor')
  await page.waitForTimeout(700)
  if (!(await page.getByText('角色已更新').first().isVisible().catch(() => false))) {
    throw new Error('角色调整未提示成功')
  }
})

await scenario('L3M10-08', 'M10', async () => {
  await page.goto(`${BASE}/kb/${detailKbId()}/resources`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const toggle = page.locator('input[type="checkbox"]')
  if (!(await toggle.isVisible().catch(() => false))) throw new Error('外部联动开关不可见')
  if (!(await toggle.isChecked())) {
    await page.locator('label').filter({ hasText: '启用外部访问' }).click()
    await page.waitForTimeout(700)
  }
  if (!(await page.getByText('已开启').first().isVisible().catch(() => false))) {
    throw new Error('外部联动开启状态未展示')
  }
  await page.getByRole('button', { name: '重新生成' }).click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '确认重新生成' }).click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('新令牌已生成').first().isVisible().catch(() => false))) {
    throw new Error('重新生成后未展示完整令牌')
  }
  await page.screenshot({ path: `${OUT}p1_kb_external.png` })
  await page.getByRole('button', { name: '我知道了' }).click()
})

// ---------- M10 成员可见性隔离 ----------
await scenario('L3M10-03', 'M10', async () => {
  const outsider = `kb_outsider_${stamp}`
  const created = await api('POST', '/users', {
    username: outsider, password: 'Test@1234', role_codes: ['member'],
  }, token)
  createdUsers.push(created.body.data.id)
  await sessionLogin(page, outsider, 'Test@1234')
  await page.goto(`${BASE}/kb`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  if (await page.getByText(`E2E知识库_${stamp}`).first().isVisible().catch(() => false)) {
    throw new Error('非成员看到了他人知识库')
  }
})

// ---------- M11/M12 待审批与审批 ----------
await scenario('L3M12-01', 'M12', async () => {
  const pendingUser = `pending_${stamp}`
  const created = await api('POST', '/users', {
    username: pendingUser, password: 'Test@1234', role_codes: ['pending'], full_name: '待审批用户',
  }, token)
  createdUsers.push(created.body.data.id)
  await sessionLogin(page, pendingUser, 'Test@1234')
  await page.waitForTimeout(1000)
  if (!(await page.getByText('账号待审批').first().isVisible().catch(() => false))) {
    throw new Error('pending 用户未进入待审批页')
  }
  if (await page.getByRole('link', { name: '工作台' }).isVisible().catch(() => false)) {
    throw new Error('pending 用户不应看到工作台菜单')
  }
  await page.screenshot({ path: `${OUT}p1_pending.png` })

  // 管理员审批
  await sessionLogin(page, 'admin', 'admin123')
  await page.goto(`${BASE}/admin/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const row = page.locator('tr', { hasText: pendingUser })
  await row.getByTitle('审批通过').click()
  await page.waitForTimeout(800)
  if (!(await page.getByText('用户已审批通过').first().isVisible().catch(() => false))) {
    throw new Error('审批未提示成功')
  }

  // 审批后 pending 用户可访问工作台
  await sessionLogin(page, pendingUser, 'Test@1234')
  await page.waitForTimeout(1000)
  if (!(await page.getByText('欢迎回来').first().isVisible().catch(() => false))) {
    throw new Error('审批后 pending 用户未进入工作台')
  }
})

// ---------- 清理 ----------
for (const kbId of createdKbs) {
  await api('DELETE', `/kb/${kbId}`, null, token).catch(() => undefined)
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
writeFileSync(`${OUT}p1_e2e_results.json`, JSON.stringify(summary, null, 2))
console.log(`P1_E2E_DONE total=${summary.total} passed=${summary.passed} failed=${summary.failed}`)
if (errors.length) console.log('CONSOLE_ERRORS:', JSON.stringify(errors))
if (failed.length) process.exitCode = 1
