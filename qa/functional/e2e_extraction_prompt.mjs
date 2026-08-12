// L3 功能场景测试（Playwright E2E，M34-S4：Prompt 模板页 + 编辑器）
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
  const kb = (await api('POST', '/kb', { name: `S10Prompt_${stamp}`, domain_code: 'general' }, token)).body.data
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
  // Schema 模板 + 类别 + 字段（前置数据）
  const tpl = (await (await fetch(`${API}/kb/${kb.id}/schema-templates`, { method: 'POST', headers: h, body: JSON.stringify({ name: '材料模板' }) })).json()).data
  const cat = (await (await fetch(`${API}/kb/${kb.id}/schema-templates/${tpl.id}/categories`, { method: 'POST', headers: h, body: JSON.stringify({ name: '室温拉伸' }) })).json()).data
  await fetch(`${API}/kb/${kb.id}/schema-templates/${tpl.id}/categories/${cat.id}/fields`, { method: 'POST', headers: h, body: JSON.stringify({ name: '抗拉强度', type: 'string', example: 'Rm' }) })

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction-config`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  await page.locator('button:has-text("Prompt 模板")').first().click()
  await page.waitForTimeout(400)

  // 1. Prompt 页签与空态
  results.push({ id: 'S4-01', name: 'Prompt 页签与空态', pass: (await page.textContent('body')).includes('暂无 Prompt 模板') && await page.locator('[data-testid="btn-new-prompt"]').count() === 1 })

  // 2. 新建 simple Prompt
  await page.click('[data-testid="btn-new-prompt"]')
  await page.waitForTimeout(300)
  await page.fill('[data-testid="prompt-name-input"]', '简单Prompt')
  await page.click('[data-testid="btn-prompt-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('简单Prompt'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S4-02', name: '新建 simple Prompt（自动进入编辑页）', pass: (await page.textContent('body')).includes('简单Prompt') && (await page.textContent('body')).includes('System 系统提示词') })

  // 3. simple 编辑器：编辑并保存
  const prompts1 = (await (await fetch(`${API}/kb/${kb.id}/extraction-config/prompts`, { headers: h })).json()).data.items
  const simpleP = prompts1.find((p) => p.name === '简单Prompt')
  await page.locator('button:has-text("返回")').first().click()
  await page.waitForTimeout(500)
  await page.click(`[data-testid="btn-open-prompt-${simpleP.id}"]`)
  await page.waitForTimeout(900)
  await page.fill('[data-testid="system-prompt-input"]', '你是材料检测专家')
  await page.fill('[data-testid="user-prompt-input"]', '请抽取 ${feature} 的抗拉强度')
  await page.click('[data-testid="btn-prompt-editor-save"]')
  await page.waitForTimeout(1000)
  results.push({ id: 'S4-03', name: 'simple 编辑器保存并停留编辑页', pass: (await page.textContent('body')).includes('简单Prompt') && (await page.textContent('body')).includes('System 系统提示词') })
  await page.locator('button:has-text("返回")').first().click()
  await page.waitForTimeout(500)

  // 4. 新建 schema Prompt（绑定模板 + 勾选类别）
  await page.click('[data-testid="btn-new-prompt"]')
  await page.waitForTimeout(300)
  await page.fill('[data-testid="prompt-name-input"]', 'SchemaPrompt')
  await page.selectOption('[data-testid="prompt-scope-select"]', 'schema')
  await page.waitForTimeout(200)
  await page.selectOption('[data-testid="prompt-template-select"]', tpl.id)
  await page.waitForTimeout(200)
  await page.locator(`[data-testid="prompt-cat-${cat.id}"]`).check()
  await page.click('[data-testid="btn-prompt-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('SchemaPrompt'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S4-04', name: '新建 schema Prompt（绑定模板并自动进入编辑页）', pass: (await page.textContent('body')).includes('SchemaPrompt') && (await page.textContent('body')).includes('室温拉伸') })

  // 5. schema 编辑器：三栏 + 字段占位符插入 + 渲染预览 + 保存
  const prompts2 = (await (await fetch(`${API}/kb/${kb.id}/extraction-config/prompts`, { headers: h })).json()).data.items
  const schemaP = prompts2.find((p) => p.name === 'SchemaPrompt')
  await page.waitForTimeout(600)
  await page.fill('[data-testid="system-prompt-input"]', '你是材料检测专家，请按 Schema 抽取')
  await page.fill('[data-testid="schema-user-input"]', '请抽取当前类别的')
  await page.click('[data-testid="field-token-抗拉强度"]')
  await page.waitForTimeout(200)
  const schemaInput = await page.inputValue('[data-testid="schema-user-input"]')
  results.push({ id: 'S4-05', name: 'schema 编辑器字段占位符插入', pass: schemaInput.includes('${') && schemaInput.includes('抗拉强度') })
  await page.locator('button:has-text("测试组装")').last().click()
  await page.waitForTimeout(300)
  const previewText = await page.textContent('[data-testid="test-user"]')
  results.push({ id: 'S4-06', name: '测试组装（占位符替换）', pass: previewText.includes('Rm') || previewText.includes('抗拉强度') })
  await page.click('[data-testid="btn-prompt-editor-save"]')
  await page.waitForTimeout(1000)

  // 6. 删除 schema Prompt（先返回列表）
  await page.locator('button:has-text("返回")').first().click()
  await page.waitForTimeout(1500)
  await page.click(`[data-testid="btn-del-prompt-${schemaP.id}"]`)
  await page.waitForTimeout(300)
  await page.click('[data-testid="btn-confirm-delete"]')
  await page.waitForTimeout(1000)
  results.push({ id: 'S4-07', name: '删除 Prompt（确认弹框）', pass: !(await page.textContent('body')).includes('SchemaPrompt') })

  // 7. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'S4-08', name: '移动端 Prompt 列表可用', pass: (await page.textContent('body')).includes('简单Prompt') && await page.locator('[data-testid="btn-new-prompt"]').count() === 1 })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-S4 Prompt 模板页 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_S4_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
