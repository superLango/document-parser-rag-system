// L3 功能场景测试（Playwright E2E，M34-S7：四项联动整体验收）
import { chromium } from '/tmp/e2e_tools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
const HELP_IMG = join(__dirname, '../../frontend/public/help/extraction-config.png')
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
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
  const kb = (await api('POST', '/kb', { name: `S10Flow_${stamp}`, domain_code: 'general' }, token)).body.data
  // 前置：术语集（含词条）
  const tb = (await api('POST', `/kb/${kb.id}/term-bases`, { name: '材料库', source_type: 'manual', auto_import: true, import_data: [{ term: '抗拉强度', standard_name: '拉伸强度' }] }, token)).body.data
  // 前置：Schema 模板 + 术语集名称来源类别 + 字段
  const tpl = (await api('POST', `/kb/${kb.id}/schema-templates`, { name: '材料检测模板' }, token)).body.data
  const cat = (await api('POST', `/kb/${kb.id}/schema-templates/${tpl.id}/categories`, {
    name: '', name_source: 'term_base', name_term_base_id: tb.id, name_term_field: 'term_name',
    query_sources: [{ label: '材料Query', term_base_id: tb.id, value_field: 'standard_name', in_query: true }],
  }, token)).body.data
  await api('POST', `/kb/${kb.id}/schema-templates/${tpl.id}/categories/${cat.id}/fields`, { name: '抗拉强度', type: 'string', example: 'Rm' }, token)
  // 前置：已启用脚本（规则绑定 + 脚本调试共用）
  await api('POST', `/kb/${kb.id}/extraction-config/scripts`, {
    folder: 'post', name: 'clean_records', enabled: true,
    code: 'async def run(args):\n    rows = await kb_tools.get_term_records("材料库", "standard_name")\n    return {"rows": rows}\n',
  }, token)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction-config`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)

  // 1. Schema：模板/术语库类别/字段/Query 联动可见
  await page.locator('[data-testid^="tpl-item-"]').first().click()
  await page.waitForTimeout(600)
  await page.locator('[data-testid^="schema-cat-"]', { hasText: '使用术语库' }).first().locator('button').first().click()
  await page.waitForTimeout(300)
  const schemaBody = await page.textContent('body')
  results.push({
    id: 'S7-01', name: 'Schema 联动（模板/术语库类别/Query 徽标）',
    pass: schemaBody.includes('材料检测模板') && schemaBody.includes('使用术语库') && schemaBody.includes('材料Query'),
  })

  // 2. Prompt：绑定 Schema 新建 → 自动进入编辑器 → 占位符 → 保存 → 返回
  await page.locator('button:has-text("Prompt 模板")').first().click()
  await page.waitForTimeout(400)
  await page.click('[data-testid="btn-new-prompt"]')
  await page.waitForTimeout(300)
  await page.fill('[data-testid="prompt-name-input"]', '联动Prompt')
  await page.selectOption('[data-testid="prompt-scope-select"]', 'schema')
  await page.waitForTimeout(200)
  await page.selectOption('[data-testid="prompt-template-select"]', tpl.id)
  await page.waitForTimeout(200)
  await page.click('[data-testid="btn-prompt-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('联动Prompt'), null, { timeout: 10000 }).catch(() => {})
  await page.waitForTimeout(600)
  await page.fill('[data-testid="system-prompt-input"]', '你是材料检测专家')
  await page.fill('[data-testid="schema-user-input"]', '请抽取类别')
  await page.click('[data-testid="field-token-抗拉强度"]')
  await page.waitForTimeout(200)
  await page.locator('button:has-text("测试组装")').last().click()
  await page.waitForTimeout(400)
  const preview = await page.textContent('[data-testid="test-user"]')
  await page.click('[data-testid="btn-prompt-editor-save"]')
  await page.waitForTimeout(800)
  await page.locator('button:has-text("返回")').first().click()
  await page.waitForTimeout(500)
  results.push({ id: 'S7-02', name: 'Prompt 绑定与占位符/测试组装', pass: preview.includes('Rm') || preview.includes('抗拉强度') })

  // 3. 规则组：绑定同一模板 + 弹窗添加脚本规则项
  await page.locator('button:has-text("后处理与校验规则")').first().click()
  await page.waitForTimeout(400)
  await page.click('[data-testid="btn-new-rule-group"]')
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="rule-template-select"]', tpl.id)
  await page.click('[data-testid="btn-rule-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('1 类别'), null, { timeout: 10000 }).catch(() => {})
  const groups = (await (await fetch(`${API}/kb/${kb.id}/extraction-config/rule-groups`, { headers: h })).json()).data.items
  await page.locator(`[data-testid="rule-group-${groups[0].id}"]`).click()
  await page.waitForTimeout(800)
  await page.locator('button[title="添加规则"]').first().click()
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="add-rule-stage"]', 'post')
  await page.selectOption('[data-testid="add-rule-script"]', { label: 'clean_records' })
  await page.click('[data-testid="btn-add-rule"]')
  await page.waitForTimeout(900)
  await page.locator(`[data-testid="rule-cat-${cat.id}"]`).click()
  await page.waitForTimeout(300)
  results.push({ id: 'S7-03', name: '规则组绑定模板并添加脚本规则项', pass: (await page.textContent('body')).includes('clean_records') })

  // 4. 脚本：调试读取术语集（与规则项同名脚本联动闭环）
  await page.locator('button:has-text("脚本管理")').first().click()
  await page.waitForTimeout(400)
  await page.locator('[data-testid="script-item-clean_records"]').click()
  await page.waitForTimeout(300)
  await page.fill('[data-testid="debug-args-input"]', '{}')
  await page.click('[data-testid="btn-run-script"]')
  await page.waitForFunction(() => document.body.innerText.includes('拉伸强度'), null, { timeout: 20000 }).catch(() => {})
  results.push({ id: 'S7-04', name: '脚本调试读取术语集（联动闭环）', pass: (await page.textContent('[data-testid="debug-result"]')).includes('拉伸强度') })

  // 5. 帮助截图
  await page.screenshot({ path: HELP_IMG, fullPage: true })
  results.push({ id: 'S7-05', name: '帮助截图生成（extraction-config.png）', pass: true })

  // 6. 移动端四项入口可用
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'S7-06', name: '移动端抽取配置入口可用', pass: (await page.textContent('body')).includes('脚本管理') && (await page.textContent('body')).includes('Schema 模板') })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-S7 四项联动整体验收 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_S7_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
