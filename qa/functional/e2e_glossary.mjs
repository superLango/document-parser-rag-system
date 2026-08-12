// L3 功能场景测试（Playwright E2E，S8-S4：术语集主页）
import { chromium } from '/tmp/e2e_tools/node_modules/playwright/index.mjs'
import { createServer } from 'node:http'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
const HELP_IMG = join(__dirname, '../../frontend/public/help/glossary.png')
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
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')

  const kbResp = await api('POST', '/kb', { name: `S8术语集_${stamp}`, domain_code: 'general' }, token)
  if (kbResp.status !== 200) throw new Error('创建 KB 失败')
  const kbId = kbResp.body.data.id

  // 本地 HTTP 术语源：验证“测试连接 → 创建 → 自动导入”真实链路（192.168.188.75 为内网地址，SSRF 放行）
  const termServer = createServer((req, res) => {
    if (req.url?.startsWith('/no-name')) {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify([
        { code: 'C1', spec: 'S1' },
        { code: 'C2', spec: 'S2' },
      ]))
      return
    }
    if (req.url?.startsWith('/terms')) {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify([
        { term_name: '接口术语A', standard_name: 'Interface A', english_term: 'Term A', category: '接口', spec: 'AA-100' },
        { term_name: '接口术语B', standard_name: 'Interface B', english_term: 'Term B', category: '接口', spec: 'BB-200' },
      ]))
      return
    }
    res.writeHead(404)
    res.end()
  })
  await new Promise((resolve) => termServer.listen(0, '0.0.0.0', resolve))
  const sourcePort = termServer.address().port
  const SOURCE_URL = `http://192.168.188.75:${sourcePort}/terms`

  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kbId}/glossary`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)

  // 1. 页面标题与空态
  const title = await page.locator('h1', { hasText: '专业术语集' }).first().textContent()
  results.push({ id: 'S4-01', name: '页面标题', pass: (title || '').includes('专业术语集') })
  const emptyText = await page.textContent('body')
  results.push({ id: 'S4-02', name: '空态展示', pass: emptyText.includes('暂无术语集') })

  // 2. 新建 manual 术语集
  await page.click('button:has-text("新建术语集")')
  await page.waitForTimeout(300)
  results.push({ id: 'S4-03', name: '向导数据源选择', pass: await page.locator('text=手动录入').count() >= 1 })
  await page.locator('button:has-text("手动录入")').first().click({ force: true })
  await page.waitForTimeout(300)
  const nameInput = page.locator('input[placeholder*="材料牌号库"]')
  await nameInput.fill('E2E材料术语')
  await page.locator('button:has-text("创建术语集")').first().click({ force: true })
  await page.waitForTimeout(900)
  const bodyAfter = await page.textContent('body')
  results.push({ id: 'S4-04', name: '手动创建后进入术语集编辑器', pass: await page.locator('h1', { hasText: 'E2E材料术语' }).count() >= 1 && bodyAfter.includes('添加一行') })
  results.push({ id: 'S4-05', name: '来源徽标显示', pass: bodyAfter.includes('手动录入') })
  await page.locator('button:has-text("返回列表")').first().click()
  await page.waitForTimeout(800)

  // 3. API 源向导表单与测试失败态（10.0.0.9 无服务）
  await page.click('button:has-text("新建术语集")')
  await page.waitForTimeout(300)
  await page.locator('button:has-text("接口拉取")').first().click({ force: true })
  await page.waitForTimeout(300)
  const urlInput = page.locator('input[placeholder*="https://"]')
  await urlInput.fill('http://169.254.169.254/terms')
  await page.locator('button:has-text("测试接口")').first().click({ force: true })
  await page.waitForTimeout(2500)
  const apiBody = await page.textContent('body')
  results.push({ id: 'S4-06', name: 'API 测试失败错误态', pass: apiBody.includes('连接失败') || apiBody.includes('失败') })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // 3.0 API 参数面板（对齐原项目：路径/Query/Header 参数动态增删）
  await page.click('button:has-text("新建术语集")')
  await page.waitForTimeout(300)
  await page.locator('button:has-text("接口拉取")').first().click({ force: true })
  await page.waitForTimeout(300)
  const hasParamBtns = await page.locator('button:has-text("+ 路径参数")').count() + await page.locator('button:has-text("+ Query 参数")').count() + await page.locator('button:has-text("+ 请求头")').count()
  await page.locator('button:has-text("+ Query 参数")').first().click({ force: true })
  await page.waitForTimeout(200)
  const paramInputs = await page.locator('div[role="dialog"] input[placeholder="参数名"]').count()
  results.push({ id: 'S4-17', name: 'API 参数面板（路径/Query/Header 参数）', pass: hasParamBtns === 3 && paramInputs === 1 })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // 3.1 API 源正向：真实本地源 → 测试成功 → 创建并自动导入词条
  await page.click('button:has-text("新建术语集")')
  await page.waitForTimeout(300)
  await page.locator('button:has-text("接口拉取")').first().click({ force: true })
  await page.waitForTimeout(300)
  await page.locator('input[placeholder*="https://"]').fill(SOURCE_URL)
  await page.locator('button:has-text("测试接口")').first().click({ force: true })
  await page.waitForTimeout(1500)
  const apiOkBody = await page.textContent('body')
  const apiOk = apiOkBody.includes('测试成功') && apiOkBody.includes('2 条数据')
  await page.locator('input[placeholder*="材料牌号库"]').fill('E2E接口术语')
  await page.locator('input[placeholder*="用途和内容范围"]').fill('E2E接口描述')
  await page.locator('button:has-text("创建并导入数据")').first().click({ force: true })
  await page.waitForTimeout(1500)
  const afterApiCreate = await page.textContent('body')
  results.push({
    id: 'S4-11', name: '接口源创建并自动全量同步（创建后进入编辑器）',
    pass: apiOk && await page.locator('h1', { hasText: 'E2E接口术语' }).count() >= 1 && afterApiCreate.includes('E2E接口描述') && afterApiCreate.includes('数据同步完成') && afterApiCreate.includes('2 条术语'),
  })

  // 3.2 返回列表 → 卡片点击进入术语管理页
  await page.locator('button:has-text("返回列表")').first().click()
  await page.waitForTimeout(800)
  await page.locator('h3:has-text("E2E接口术语")').click()
  await page.waitForTimeout(900)
  const editorBody = await page.textContent('body')
  const editorH1 = await page.locator('h1', { hasText: 'E2E接口术语' }).count()
  results.push({
    id: 'S4-12', name: '卡片点击进入术语管理页（词条与动态列可见）',
    pass: editorH1 >= 1 && editorBody.includes('接口术语A') && editorBody.includes('AA-100') && editorBody.includes('返回列表'),
  })

  // 3.3 字段配置：动态列显示名 spec → 规格
  await page.click('[data-testid="btn-field-config"]')
  await page.waitForTimeout(300)
  await page.fill('[data-testid="alias-input-spec"]', '规格')
  await page.click('[data-testid="btn-alias-save"]')
  await page.waitForTimeout(900)
  const afterAlias = await page.textContent('body')
  results.push({
    id: 'S4-13', name: '字段配置-动态列显示名更新',
    pass: afterAlias.includes('规格') && afterAlias.includes('AA-100'),
  })

  await page.locator('button:has-text("返回列表")').first().click()
  await page.waitForTimeout(800)

  // 3.4 无名称列源：创建后自动同步跳过并提示
  await page.click('button:has-text("新建术语集")')
  await page.waitForTimeout(300)
  await page.locator('button:has-text("接口拉取")').first().click({ force: true })
  await page.waitForTimeout(300)
  await page.locator('input[placeholder*="https://"]').fill(`${SOURCE_URL.replace('/terms', '/no-name')}`)
  await page.locator('button:has-text("测试接口")').first().click({ force: true })
  await page.waitForTimeout(1500)
  await page.locator('input[placeholder*="材料牌号库"]').fill('E2E无名称列')
  await page.locator('button:has-text("创建并导入数据")').first().click({ force: true })
  await page.waitForTimeout(1500)
  const afterNoNameCreate = await page.textContent('body')
  results.push({
    id: 'S4-14', name: '无名称列源创建-首列兜底自动导入',
    pass: await page.locator('h1', { hasText: 'E2E无名称列' }).count() >= 1 && afterNoNameCreate.includes('C1') && afterNoNameCreate.includes('C2') && afterNoNameCreate.includes('2 条术语'),
  })
  await page.locator('button:has-text("返回列表")').first().click()
  await page.waitForTimeout(800)

  // 4. 截图（帮助文档）
  await page.screenshot({ path: HELP_IMG, fullPage: true })
  results.push({ id: 'S4-07', name: '帮助截图生成', pass: true })

  // 5. 删除确认
  await page.locator('button:has-text("删除")').first().click()
  await page.waitForTimeout(300)
  results.push({ id: 'S4-08', name: '删除确认弹窗', pass: await page.locator('text=删除术语集').count() >= 1 })
  await page.locator('div[role="dialog"] button:has-text("删除")').click({ force: true })
  await page.waitForTimeout(800)
  const afterDelete = await page.textContent('body')
  results.push({
    id: 'S4-09', name: '删除后目标卡片消失（列表保留其他术语集）',
    pass: !afterDelete.includes('E2E无名称列') && afterDelete.includes('E2E接口术语') && afterDelete.includes('E2E材料术语'),
  })

  // 6. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.goto(`${BASE}/kb/${kbId}/glossary`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  results.push({ id: 'S4-10', name: '移动端可用', pass: await page.locator('button:has-text("新建术语集")').count() >= 1 })

  await browser.close()
  await new Promise((resolve) => termServer.close(resolve))

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M33-S4 术语集主页 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S8_GLOSSARY_S4_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
