// L3 功能场景测试（Playwright E2E，M34-G：全局配置页）
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
  const kb = (await api('POST', '/kb', { name: `S10Global_${stamp}`, domain_code: 'general' }, token)).body.data

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction-config`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)

  // 1. 默认进入全局配置页签
  results.push({ id: 'G-01', name: '默认进入全局配置页签', pass: (await page.textContent('body')).includes('检索召回与上下文') && (await page.textContent('body')).includes('LLM 抽取参数') && (await page.textContent('body')).includes('脚本工具 kb_tool') })

  // 2. 三大区块与默认值
  const topK = await page.inputValue('[data-testid="global-retrieval-top-k"]')
  const timeout = await page.inputValue('[data-testid="global-script-timeout"]')
  results.push({ id: 'G-02', name: '默认值回显（top_k=10 / script_timeout=10）', pass: topK === '10' && timeout === '10' })

  // 3. LLM 区块展开与引擎切换
  await page.locator('button:has-text("LLM 抽取参数")').first().click()
  await page.waitForTimeout(300)
  await page.selectOption('[data-testid="global-llm-engine"]', 'LangExtract')
  await page.waitForTimeout(300)
  results.push({ id: 'G-03', name: 'LLM 区块展开与引擎切换', pass: (await page.textContent('body')).includes('引擎专属参数（LangExtract）') })

  // 4. 编辑并保存
  await page.fill('[data-testid="global-retrieval-top-k"]', '25')
  await page.fill('[data-testid="global-script-timeout"]', '20')
  await page.click('[data-testid="btn-save-global"]')
  await page.waitForFunction(() => document.body.innerText.includes('全局配置已保存'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'G-04', name: '编辑并保存全局配置', pass: (await page.textContent('body')).includes('全局配置已保存') })

  // 5. 重载持久化
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const topK2 = await page.inputValue('[data-testid="global-retrieval-top-k"]')
  const timeout2 = await page.inputValue('[data-testid="global-script-timeout"]')
  results.push({ id: 'G-05', name: '重载后配置持久化', pass: topK2 === '25' && timeout2 === '20' })

  // 6. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'G-06', name: '移动端全局配置可用', pass: (await page.textContent('body')).includes('检索召回与上下文') && (await page.textContent('body')).includes('保存全局配置') })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-G 抽取配置全局配置页 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_GLOBAL_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
