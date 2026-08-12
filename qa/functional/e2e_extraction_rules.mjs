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

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction-config?tab=rules`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)

  // 1. 规则页签空态
  results.push({ id: 'S5-01', name: '规则页签与空态', pass: (await page.textContent('body')).includes('暂无规则组') && await page.locator('[data-testid="btn-new-rule-group"]').count() === 1 })

  // 2. 新建规则组
  await page.click('[data-testid="btn-new-rule-group"]')
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="rule-template-select"]', tpl.id)
  await page.click('[data-testid="btn-rule-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('2 类别'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-02', name: '新建规则组（绑定 Schema 模板）', pass: (await page.textContent('body')).includes('规则模板') && (await page.textContent('body')).includes('2 类别') })

  // 3. 规则组详情类别
  await page.locator('[role="button"]', { hasText: '规则模板' }).first().click()
  await page.waitForTimeout(800)
  results.push({ id: 'S5-03', name: '规则组详情显示绑定模板类别', pass: (await page.textContent('body')).includes('类别一') && (await page.textContent('body')).includes('类别二') })

  // 4. 类别一添加规则项
  await page.click(`[data-testid="btn-edit-rules-${cat1.id}"]`)
  await page.waitForTimeout(300)
  await page.fill('[data-testid="rule-script-0"]', 'clean_records')
  await page.fill('[data-testid="rule-params-0"]', '{"drop_empty": true}')
  await page.click('[data-testid="btn-rule-items-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('clean_records'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-04', name: '类别一规则项保存', pass: (await page.textContent('body')).includes('clean_records') })

  // 5. 类别二添加规则项
  await page.click(`[data-testid="btn-edit-rules-${cat2.id}"]`)
  await page.waitForTimeout(300)
  await page.fill('[data-testid="rule-script-0"]', 'validate_records')
  await page.click('[data-testid="btn-rule-items-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('validate_records'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S5-05', name: '类别二规则项保存', pass: (await page.textContent('body')).includes('validate_records') })

  // 6. 删除规则组
  const groups = (await (await fetch(`${API}/kb/${kb.id}/extraction-config/rule-groups`, { headers: h })).json()).data.items
  await page.click(`[data-testid="btn-del-rule-group-${groups[0].id}"]`)
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
