// L3 功能场景测试（Playwright E2E，S8-S5：术语管理页 · 完全复刻版）
import { chromium } from '/tmp/e2e_tools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
const HELP_IMG = join(__dirname, '../../frontend/public/help/glossary-editor.png')
mkdirSync(OUT, { recursive: true })

const results = []
const errors = []
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
    const loc = m.location()
    if (/400|Bad Request/.test(m.text()) && loc && /term-bases\/test-api/.test(loc.url)) return
    errors.push(`[${label}] console: ${m.text()}`)
  })
}

async function sessionLogin(page, token) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate((t) => {
    localStorage.setItem('access_token', t)
    localStorage.setItem('refresh_token', '')
  }, token)
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
}

async function run() {
  const token = await adminToken()

  const kbResp = await api('POST', '/kb', { name: `S8术语管理_${stamp}`, domain_code: 'general' }, token)
  if (kbResp.status !== 200) throw new Error('创建 KB 失败')
  const kbId = kbResp.body.data.id
  const baseResp = await api('POST', `/kb/${kbId}/term-bases`, { name: '标准术语', description: 'E2E 术语集', source_type: 'manual' }, token)
  if (baseResp.status !== 200) throw new Error('创建术语集失败')
  const baseId = baseResp.body.data.id

  const viewerName = `s5viewer_${stamp}`
  await api('POST', '/users', { username: viewerName, password: 'Viewer123!', full_name: 'E2E查看者' }, token)
  const inv = await api('POST', `/kb/${kbId}/invitations`, { username: viewerName, role: 'viewer' }, token)
  if (inv.status !== 200) throw new Error('邀请 viewer 失败')
  const invToken = inv.body.data.token
  const vlogin = await api('POST', '/auth/login', { username: viewerName, password: 'Viewer123!' })
  const viewerToken = vlogin.body.data.access_token
  await api('POST', `/kb/invitations/${invToken}/accept`, null, viewerToken)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'admin')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kbId}/glossary`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('h3:has-text("标准术语")').click()
  await page.waitForTimeout(900)

  // 1. 页面标题/返回/空态/操作按钮
  const h1 = await page.locator('h1', { hasText: '标准术语' }).first().textContent()
  results.push({ id: 'S5-01', name: '页面标题与返回链接', pass: Boolean(h1) && (await page.textContent('body')).includes('返回列表') })
  const body0 = await page.textContent('body')
  results.push({ id: 'S5-02', name: '空态与操作按钮（添加行/保存全部）', pass: body0.includes('暂无数据') && await page.locator('[data-testid="btn-add-row"]').count() === 1 && await page.locator('[data-testid="btn-save-all"]').count() === 1 })

  // 2. 添加一行 + 保存全部
  await page.click('[data-testid="btn-add-row"]')
  await page.waitForTimeout(300)
  const newRow = page.locator('tr', { has: page.locator('[data-testid^="edit-term-new-"]') }).first()
  await newRow.locator('input').nth(0).fill('抗拉强度')
  await newRow.locator('input').nth(3).fill('力学性能')
  await page.click('[data-testid="btn-save-all"]')
  await page.waitForFunction(() => Boolean(document.querySelector('input[value="抗拉强度"]')), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-03', name: '添加一行并保存（行出现）', pass: await page.locator('input[value="抗拉强度"]').count() >= 1 })

  // 3. 行内编辑（改分类）
  const list1 = await api('GET', `/kb/${kbId}/terms?term_base_id=${baseId}&page_size=100`, null, token)
  const termStrength = list1.body.data.items.find((t) => t.term_name === '抗拉强度')
  if (!termStrength) throw new Error('抗拉强度未创建成功')
  const strengthRow = page.locator('tr', { has: page.locator(`[data-testid="edit-term-${termStrength.id}"]`) }).first()
  await strengthRow.locator('input').nth(3).fill('高温性能')
  await page.click('[data-testid="btn-save-all"]')
  await page.waitForFunction(() => Boolean(document.querySelector('input[value="高温性能"]')), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-04', name: '行内编辑术语更新分类', pass: await page.locator('input[value="高温性能"]').count() >= 1 })

  // 4. 字段级搜索（manual：search_field=category）
  await page.selectOption('[data-testid="search-field-select"]', 'category')
  await page.fill('[data-testid="term-search"]', '高温性能')
  await page.click('button:has-text("搜索")')
  await page.waitForFunction(() => Boolean(document.querySelector('input[value="抗拉强度"]')), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-05', name: '字段级搜索命中', pass: await page.locator('input[value="抗拉强度"]').count() >= 1 })
  await page.fill('[data-testid="term-search"]', '不存在的术语XYZ')
  await page.click('button:has-text("搜索")')
  await page.waitForTimeout(900)
  const bodyNoHit = await page.textContent('body')
  results.push({ id: 'S5-06', name: '字段级搜索无命中空态', pass: bodyNoHit.includes('暂无数据') })
  await page.selectOption('[data-testid="search-field-select"]', '')
  await page.fill('[data-testid="term-search"]', '')
  await page.click('button:has-text("搜索")')
  await page.waitForTimeout(900)

  // 5. 术语集信息内联编辑（描述随保存全部提交）
  await page.fill('[data-testid="info-desc-input"]', 'E2E更新描述')
  await page.click('[data-testid="btn-save-all"]')
  await page.waitForTimeout(1000)
  await page.locator('button:has-text("返回列表")').first().click()
  await page.waitForTimeout(800)
  const listBody = await page.textContent('body')
  results.push({ id: 'S5-07', name: '术语集信息内联编辑（描述保存并在列表可见）', pass: listBody.includes('E2E更新描述') })
  await page.locator('h3:has-text("标准术语")').click()
  await page.waitForTimeout(900)

  // 6. 帮助截图（编辑器页）
  await page.screenshot({ path: HELP_IMG, fullPage: true })
  results.push({ id: 'S5-08', name: '帮助截图生成（glossary-editor.png）', pass: true })

  // 7. viewer 权限
  const vpage = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(vpage, 'viewer')
  await sessionLogin(vpage, viewerToken)
  await vpage.goto(`${BASE}/kb/${kbId}/glossary`, { waitUntil: 'networkidle' })
  await vpage.waitForTimeout(800)
  await vpage.locator('h3:has-text("标准术语")').click()
  await vpage.waitForTimeout(900)
  const vBody = await vpage.textContent('body')
  results.push({
    id: 'S5-09', name: '查看者只读（无写操作按钮）',
    pass: vBody.includes('标准术语') && await vpage.locator('[data-testid="btn-add-row"]').count() === 0 && await vpage.locator('[data-testid="btn-save-all"]').count() === 0,
  })
  await vpage.close()

  // 8. 行内删除标记 + 保存全部
  const termDel = await api('POST', `/kb/${kbId}/terms`, { term: `待删除_${stamp}`, term_base_id: baseId }, token)
  const termDelId = termDel.body.data.id
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.click(`[data-testid="btn-toggle-delete-${termDelId}"]`)
  await page.waitForTimeout(300)
  await page.click('[data-testid="btn-save-all"]')
  await page.waitForTimeout(1000)
  const bodyAfterDel = await page.textContent('body')
  results.push({ id: 'S5-10', name: '行内删除标记并保存（行消失）', pass: !bodyAfterDel.includes(`待删除_${stamp}`) })

  // 9. 移动端：表格横向滚动可用
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForFunction(() => Boolean(document.querySelector('input[value="抗拉强度"]')), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-11', name: '移动端表格可用', pass: await page.locator('input[value="抗拉强度"]').count() >= 1 && await page.locator('[data-testid="btn-add-row"]').count() === 1 })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M33-S5 术语管理页 E2E 报告（完全复刻版）',
    '',
    `- 日期：${new Date().toISOString().slice(0, 10)}`,
    `- 通过：${passed}/${results.length}`,
    '',
    '| 场景 | 结果 |',
    '|------|------|',
    ...results.map((r) => `| ${r.id} ${r.name} | ${r.pass ? '✅' : '❌'} |`),
    '',
    errors.length ? `## 控制台错误\n\n${errors.join('\n')}\n` : '## 控制台错误\n\n无\n',
  ].join('\n')
  writeFileSync(join(OUT, 'INDEX_S8_GLOSSARY_S5_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
