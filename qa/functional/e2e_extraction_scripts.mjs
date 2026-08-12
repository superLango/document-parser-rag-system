// L3 功能场景测试（Playwright E2E，M34-S6：脚本管理页）
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
  const kb = (await api('POST', '/kb', { name: `S10Scripts_${stamp}`, domain_code: 'general' }, token)).body.data
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
  await fetch(`${API}/kb/${kb.id}/term-bases`, { method: 'POST', headers: h, body: JSON.stringify({ name: '材料库', source_type: 'manual', auto_import: true, import_data: [{ term: '抗拉强度', standard_name: '拉伸强度' }] }) })

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction-config?tab=scripts`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)

  // 1. 脚本页签与目录
  results.push({ id: 'S6-01', name: '脚本页签与目录/新建入口', pass: (await page.textContent('body')).includes('抽取后处理') && (await page.textContent('body')).includes('校验') && await page.locator('[data-testid="btn-new-script"]').count() === 1 })

  // 2. 新建 post 脚本并保存
  await page.click('[data-testid="btn-new-script"]')
  await page.waitForTimeout(200)
  await page.fill('[data-testid="script-name-input"]', 'clean_records')
  await page.click('[data-testid="btn-save-script"]')
  await page.waitForFunction(() => document.body.innerText.includes('clean_records'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S6-02', name: '新建并保存 post 脚本', pass: (await page.textContent('body')).includes('clean_records') })

  // 3. 校验目录新建脚本
  await page.click('[data-testid="script-folder-validation"]')
  await page.waitForTimeout(300)
  await page.click('[data-testid="btn-new-script"]')
  await page.waitForTimeout(200)
  await page.fill('[data-testid="script-name-input"]', 'validate_records')
  await page.click('[data-testid="btn-save-script"]')
  await page.waitForFunction(() => document.body.innerText.includes('validate_records'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S6-03', name: '校验目录新建脚本', pass: (await page.textContent('body')).includes('validate_records') })

  // 4. 回到 post 运行调试（文件夹点击为折叠/展开切换）
  await page.click('[data-testid="script-folder-post"]')
  await page.waitForTimeout(200)
  await page.click('[data-testid="script-folder-post"]')
  await page.waitForTimeout(300)
  await page.locator('[data-testid="script-item-clean_records"]').click()
  await page.waitForTimeout(300)
  await page.fill('[data-testid="debug-args-input"]', '{"records":[{"a":1}],"category":"力学性能"}')
  await page.click('[data-testid="btn-run-script"]')
  await page.waitForFunction(() => document.body.innerText.includes('records'), null, { timeout: 20000 }).catch(() => {})
  const debugText = await page.textContent('[data-testid="debug-result"]')
  results.push({ id: 'S6-04', name: '调试运行成功（结构化回显 records）', pass: debugText.includes('records') && debugText.includes('a') })

  // 5. 术语集工具读取
  await page.fill('[data-testid="script-code-input"]', 'async def run(args):\n    rows = await kb_tools.get_term_records("材料库", "term_name")\n    return {"rows": rows}\n')
  await page.click('[data-testid="btn-save-script"]')
  await page.waitForTimeout(800)
  await page.click('[data-testid="btn-run-script"]')
  await page.waitForFunction(() => document.body.innerText.includes('抗拉强度'), null, { timeout: 20000 }).catch(() => {})
  const termText = await page.textContent('[data-testid="debug-result"]')
  results.push({ id: 'S6-05', name: '脚本读取术语集（get_term_records）', pass: termText.includes('抗拉强度') })

  // 6. 超时失败
  await page.fill('[data-testid="script-code-input"]', 'import time\ndef run(args):\n    time.sleep(11)\n    return {}\n')
  await page.click('[data-testid="btn-save-script"]')
  await page.waitForTimeout(600)
  await page.click('[data-testid="btn-run-script"]')
  await page.waitForFunction(() => document.body.innerText.includes('超时'), null, { timeout: 20000 }).catch(() => {})
  results.push({ id: 'S6-06', name: '脚本超时返回错误（非 500）', pass: (await page.textContent('body')).includes('超时') })

  // 7. 删除脚本（确认）
  await page.fill('[data-testid="script-code-input"]', 'def run(args): return args')
  await page.click('[data-testid="btn-save-script"]')
  await page.waitForTimeout(600)
  await page.click('[data-testid="btn-delete-script"]')
  await page.waitForTimeout(300)
  const delDialog = await page.locator('text=删除脚本').count()
  await page.click('[data-testid="btn-script-delete-confirm"]')
  await page.waitForTimeout(800)
  results.push({ id: 'S6-07', name: '删除脚本（确认弹框）', pass: delDialog >= 1 && !(await page.textContent('body')).includes('clean_records') })

  // 8. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'S6-08', name: '移动端脚本页可用', pass: (await page.textContent('body')).includes('抽取后处理') && await page.locator('[data-testid="btn-new-script"]').count() === 1 })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-S6 脚本管理页 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_S6_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
