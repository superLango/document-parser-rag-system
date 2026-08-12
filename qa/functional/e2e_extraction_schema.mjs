// L3 功能场景测试（Playwright E2E，M34-S3：抽取配置 Schema 模板页）
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
  const kb = (await api('POST', '/kb', { name: `S10Schema_${stamp}`, domain_code: 'general' }, token)).body.data
  await api('POST', `/kb/${kb.id}/term-bases`, { name: '材料库', source_type: 'manual' }, token)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)

  // 入口闭环：KB 内部菜单 → 抽取配置
  await page.locator('a[href*="/extraction-config"]').last().click()
  await page.waitForTimeout(900)

  // 1. 页面标题与页签
  const h1 = await page.locator('h1', { hasText: '抽取配置' }).count()
  const tabs = await page.locator('button:has-text("Schema 模板")').count()
  results.push({ id: 'S3-01', name: '页面标题与四个页签', pass: h1 >= 1 && tabs >= 1 && await page.locator('button:has-text("Prompt 模板")').count() >= 1 && await page.locator('button:has-text("后处理与校验规则")').count() >= 1 && await page.locator('button:has-text("脚本管理")').count() >= 1 })

  // 2. 其他页签占位
  await page.locator('button:has-text("Prompt 模板")').first().click()
  await page.waitForTimeout(300)
  results.push({ id: 'S3-02', name: '未开放页签占位提示', pass: (await page.textContent('body')).includes('该模块在后续阶段开放') })
  await page.locator('button:has-text("Schema 模板")').first().click()
  await page.waitForTimeout(300)

  // 3. 新建模板
  await page.click('[data-testid="btn-new-template"]')
  await page.waitForTimeout(300)
  await page.fill('[data-testid="tpl-name-input"]', '材料检测模板')
  await page.click('[data-testid="btn-tpl-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('材料检测模板'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S3-03', name: '新建 Schema 模板', pass: await page.locator('button:has-text("材料检测模板")').count() >= 1 })

  // 4. 新建类别（手动）
  await page.locator('button:has-text("材料检测模板")').first().click()
  await page.waitForTimeout(500)
  await page.click('[data-testid="btn-new-category"]')
  await page.waitForTimeout(300)
  await page.fill('[data-testid="cat-name-input"]', '室温拉伸')
  await page.click('[data-testid="btn-cat-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('室温拉伸'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S3-04', name: '新建类别（手动）', pass: (await page.textContent('body')).includes('室温拉伸') })

  // 5. 新建字段
  await page.locator('button:has-text("室温拉伸")').first().click()
  await page.waitForTimeout(300)
  await page.locator('button:has-text("添加字段")').first().click()
  await page.waitForTimeout(300)
  await page.fill('[data-testid="field-name-input"]', '抗拉强度')
  await page.click('[data-testid="btn-field-save"]')
  await page.waitForFunction(() => document.body.innerText.includes('抗拉强度'), null, { timeout: 10000 }).catch(() => {})
  results.push({ id: 'S3-05', name: '新建字段', pass: (await page.textContent('body')).includes('抗拉强度') })

  // 6. 术语集名称来源类别
  await page.click('[data-testid="btn-new-category"]')
  await page.waitForTimeout(300)
  await page.locator('div[role="dialog"] select').first().selectOption('term_base')
  await page.waitForTimeout(200)
  await page.selectOption('[data-testid="cat-term-base-select"]', { label: '材料库' })
  await page.click('[data-testid="btn-cat-save"]')
  await page.waitForTimeout(900)
  results.push({ id: 'S3-06', name: '术语集名称来源类别（使用术语库徽标）', pass: (await page.textContent('body')).includes('使用术语库') })

  // 7. Query 术语集
  await page.click('[data-testid="btn-new-category"]')
  await page.waitForTimeout(300)
  await page.locator('button:has-text("添加术语集")').first().click()
  await page.waitForTimeout(300)
  await page.fill('[data-testid="qs-label-0"]', '材料Query')
  await page.selectOption('[data-testid="qs-term-0"]', { label: '材料库' })
  await page.locator('[data-testid="qs-in-query-0"]').click()
  await page.click('[data-testid="btn-cat-save"]')
  await page.waitForTimeout(900)
  await page.locator('button:has-text("未命名类别")').last().click()
  await page.waitForTimeout(300)
  results.push({ id: 'S3-07', name: 'Query 术语集配置', pass: (await page.textContent('body')).includes('材料Query') })

  // 8. 删除模板（确认弹框）
  const bodyBefore = await page.textContent('body')
  await page.locator('button:has-text("材料检测模板")').first().click()
  await page.waitForTimeout(400)
  await page.locator('button:has-text("删除")').last().click()
  await page.waitForTimeout(300)
  const delDialog = await page.locator('text=删除模板').count()
  await page.click('[data-testid="btn-confirm-delete"]')
  await page.waitForTimeout(1000)
  const bodyAfter = await page.textContent('body')
  results.push({ id: 'S3-08', name: '删除模板（确认弹框+级联）', pass: delDialog >= 1 && !bodyAfter.includes('材料检测模板') && bodyAfter.includes('暂无模板') })

  // 9. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'S3-09', name: '移动端可用', pass: (await page.textContent('body')).includes('Schema 模板') && await page.locator('[data-testid="btn-new-template"]').count() === 1 })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-S3 抽取配置 Schema 模板页 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_S3_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
