// L3 功能场景测试（Playwright E2E，M34-S5：后处理与校验规则页）
import { chromium } from '/tmp/e2e_tools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const results = []
const errors = []
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
  const kb = (await api('POST', '/kb', { name: `S10Rules_${stamp}`, domain_code: 'general' }, token)).body.data
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
  const tpl = (await (await fetch(`${API}/kb/${kb.id}/schema-templates`, { method: 'POST', headers: h, body: JSON.stringify({ name: '规则模板' }) })).json()).data
  const cat1 = (await (await fetch(`${API}/kb/${kb.id}/schema-templates/${tpl.id}/categories`, { method: 'POST', headers: h, body: JSON.stringify({ name: '类别一' }) })).json()).data
  const cat2 = (await (await fetch(`${API}/kb/${kb.id}/schema-templates/${tpl.id}/categories`, { method: 'POST', headers: h, body: JSON.stringify({ name: '类别二' }) })).json()).data
  // 前置：已启用脚本（添加规则弹窗只列出启用脚本）
  await api('POST', `/kb/${kb.id}/extraction-config/scripts`, { folder: 'post', name: 'clean_records', enabled: true, code: 'def run(args): return args' }, token)
  await api('POST', `/kb/${kb.id}/extraction-config/scripts`, { folder: 'validation', name: 'validate_records', enabled: true, code: 'def run(args): return args' }, token)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction-config?tab=rules`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)

  // 1. 规则页签空态
  results.push({ id: 'S5-01', name: '规则页签与空态', pass: (await page.textContent('body')).includes('暂无规则组') && await page.locator('[data-testid="btn-new-rule-group"]').count() === 1 })

  // 2. 新建规则组（默认选中第一个模板）
  await page.click('[data-testid="btn-new-rule-group"]')
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="rule-template-select"]', tpl.id)
  await page.click('[data-testid="btn-rule-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('2 类别'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-02', name: '新建规则组（绑定 Schema 模板）', pass: (await page.textContent('body')).includes('规则模板') && (await page.textContent('body')).includes('2 类别') })

  // 3. 展开规则组（懒加载类别详情）
  const groups = (await (await fetch(`${API}/kb/${kb.id}/extraction-config/rule-groups`, { headers: h })).json()).data.items
  const gid = groups[0].id
  await page.locator(`[data-testid="rule-group-${gid}"]`).click()
  await page.waitForTimeout(800)
  results.push({ id: 'S5-03', name: '规则组展开显示绑定模板类别', pass: (await page.textContent('body')).includes('类别一') && (await page.textContent('body')).includes('类别二') })

  // 4. 类别一添加后处理规则（弹窗：阶段 + 脚本）
  await page.locator('button[title="添加规则"]').first().click()
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="add-rule-stage"]', 'post')
  await page.selectOption('[data-testid="add-rule-script"]', { label: 'clean_records' })
  await page.click('[data-testid="btn-add-rule"]')
  await page.waitForTimeout(900)
  await page.locator(`[data-testid="rule-cat-${cat1.id}"]`).click()
  await page.waitForTimeout(300)
  results.push({ id: 'S5-04', name: '类别一添加后处理规则（自动持久化）', pass: (await page.textContent('body')).includes('clean_records') && (await page.textContent('body')).includes('后处理') })

  // 5. 类别二添加校验规则
  await page.locator('button[title="添加规则"]').last().click()
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="add-rule-stage"]', 'validation')
  await page.selectOption('[data-testid="add-rule-script"]', { label: 'validate_records' })
  await page.click('[data-testid="btn-add-rule"]')
  await page.waitForTimeout(900)
  await page.locator(`[data-testid="rule-cat-${cat2.id}"]`).click()
  await page.waitForTimeout(300)
  results.push({ id: 'S5-05', name: '类别二添加校验规则（阶段徽章）', pass: (await page.textContent('body')).includes('validate_records') && (await page.textContent('body')).includes('校验') })

  // 6. 删除规则组
  await page.locator(`[data-testid="btn-del-rule-group-${gid}"]`).click()
  await page.waitForTimeout(300)
  const delDialog = await page.locator('text=删除规则组').count()
  await page.click('[data-testid="btn-confirm-delete"]')
  await page.waitForTimeout(1000)
  results.push({ id: 'S5-06', name: '删除规则组（确认弹框+级联）', pass: delDialog >= 1 && (await page.textContent('body')).includes('暂无规则组') })

  // 7. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'S5-07', name: '移动端规则页可用', pass: (await page.textContent('body')).includes('规则组') && await page.locator('[data-testid="btn-new-rule-group"]').count() === 1 })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-S5 后处理与校验规则页 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_S5_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
