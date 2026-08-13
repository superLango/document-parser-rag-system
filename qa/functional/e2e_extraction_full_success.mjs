// L3 功能场景测试（Playwright E2E，M34-E6：真实 LLM 抽取全成功链路）
import { chromium } from '/tmp/e2e_tools/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = 'http://127.0.0.1:5174'
const API = 'http://127.0.0.1:8000/api/v1'
const OUT = new URL('../results/', import.meta.url).pathname
const HELP_IMG = join(__dirname, '../../frontend/public/help/structured-extraction.png')
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

async function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

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

const RICH_PDF = 'JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjguMgoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjguMik+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFIgNyAwIFIgOCAwIFIgOSAwIFIgMTAgMCBSIDExIDAgUiAxMiAwIFIgMTMgMCBSIDE0IDAgUiAxNSAwIFIgMTYgMCBSIDE3IDAgUiAxOCAwIFIgMTkgMCBSIDIwIDAgUiAyMSAwIFIgMjIgMCBSIDIzIDAgUiAyNCAwIFIgMjUgMCBSIDI2IDAgUiAyNyAwIFIgMjggMCBSIDI5IDAgUiAzMCAwIFIgMzEgMCBSIDMyIDAgUiAzMyAwIFIgMzQgMCBSIDM1IDAgUiAzNiAwIFIgMzcgMCBSIDM4IDAgUiAzOSAwIFIgNDAgMCBSIDQxIDAgUiA0MiAwIFIgNDMgMCBSIDQ0IDAgUiA0NSAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDEyMC9GaWx0ZXIvRmxhdGVEZWNvZGU+PgpzdHJlYW0KeNotjD0KQkEQg/s5xdzA+dnJPEEsBBs7YTuxct/DQgsbz+/uIilCvoTQh06VlKVLOY0TxvVNu+f6+rIq141vhzBsXc0kCwItBZEGzZLD48/XdOzxmNl7Z4Mhe7eY+OLiYlJaCHQsoPNp7l2P93qhc6Ur/QCX2yD4CmVuZHN0cmVhbQplbmRvYmoKCjcgMCBvYmoKPDwvTGVuZ3RoIDExOS9GaWx0ZXIvRmxh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agoKNDUgMCBvYmoKPDwvTGVuZ3RoIDEyMC9GaWx0ZXIvRmxhdGVEY29kZT4+CnN0cmVhbQp42i2MPQpCQRCD+znF3MD52ck8QSwEGzthO7Fy38NCCxvP7+4iKUK+hNCHTpWUpUs5jSFc37R7rq8vq3Ld+HYIw9bVTLIg0FIQadAsOTz+fE3HHo+ZvXc2GLJ3i4kvLi4mpYVAxwI6n+bei8vxXi90rnSlH7laISUKZW5kc3RyZWFtCmVuZG9iagoKeHJlZgowIDQ2CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDA0MiAwMDAwMCBuIAowMDAwMDAwMTIwIDAwMDAwIG4gCjAwMDAwMDAxNzIgMDAwMDAgbiAKMDAwMDAwMDIxMyAwMDAwMCBuIAowMDAwMDAwNTkwIDAwMDAwIG4gCjAwMDAwMDA2NzkgMDAwMDAgbiAKMDAwMDAwMDg2OCAwMDAwMCBuIAowMDAwMDAxMDU2IDAwMDAwIG4gCjAwMDAwMDEyNDQgMDAwMDAgbiAKMDAwMDAwMTQzNCAwMDAwMCBuIAowMDAwMDAxNjI0IDAwMDAwIG4gCjAwMDAwMDE4MTIgMDAwMDAgbiAKMDAwMDAwMjAwMiAwMDAwMCBuIAowMDAwMDAyMTkyIDAwMDAwIG4gCjAwMDAwMDIzODIgMDAwMDAgbiAKMDAwMDAwMjU3MyAwMDAwMCBuIAowMDAwMDAyNzY0IDAwMDAwIG4gCjAwMDAwMDI5NTUgMDAwMDAgbiAKMDAwMDAwMzE0NiAwMDAwMCBuIAowMDAwMDAzMzM4IDAwMDAwIG4gCjAwMDAwMDM1MjkgMDAwMDAgbiAKMDAwMDAwMzcyMSAwMDAwMCBuIAowMDAwMDAzOTExIDAwMDAwIG4gCjAwMDAwMDQxMDIgMDAwMDAgbiAKMDAwMDAwNDI5NCAwMDAwMCBuIAowMDAwMDA0NDg1IDAwMDAwIG4gCjAwMDAwMDQ2NzYgMDAwMDAgbiAKMDAwMDAwNDg2OCAwMDAwMCBuIAowMDAwMDA1MDU4IDAwMDAwIG4gCjAwMDAwMDUyNTAgMDAwMDAgbiAKMDAwMDAwNTQ0MSAwMDAwMCBuIAowMDAwMDA1NjMyIDAwMDAwIG4gCjAwMDAwMDU4MjQgMDAwMDAgbiAKMDAwMDAwNjAxNSAwMDAwMCBuIAowMDAwMDA2MjA3IDAwMDAwIG4gCjAwMDAwMDYzOTggMDAwMDAgbiAKMDAwMDAwNjU4OSAwMDAwMCBuIAowMDAwMDA2NzgwIDAwMDAwIG4gCjAwMDAwMDY5NjkgMDAwMDAgbiAKMDAwMDAwNzE2MCAwMDAwMCBuIAowMDAwMDA3MzUxIDAwMDAwIG4gCjAwMDAwMDc1NDIgMDAwMDAgbiAKMDAwMDAwNzczMiAwMDAwMCBuIAowMDAwMDA3OTIzIDAwMDAwIG4gCjAwMDAwMDgxMTQgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA0Ni9Sb290IDEgMCBSL0lEWzw0NTRCMzlDMjk0MTcyREMyODhDM0ExNzFDMjlGNTdDMj48MUFDQ0I3RDg1OUI0MDg3MEIxMjgyOUY3NEE4NDRBNzE+XT4+CnN0YXJ0eHJlZgo4MzA0CiUlRU9GCg=='

async function waitDocumentReady(token, kbId, docId, timeout = 180000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const r = await api('GET', `/kb/${kbId}/documents/${docId}`, null, token)
    const d = r.body.data
    if (d && d.process_status === 'completed' && d.index_status === 'indexed') return d
    await sleep(2000)
  }
  throw new Error('文档解析/索引超时')
}

async function run() {
  const token = await adminToken()
  const kb = (await api('POST', '/kb', { name: `S10E6_${stamp}`, domain_code: 'general' }, token)).body.data
  const h = { Authorization: `Bearer ${token}` }

  // 自建配置：术语集 + Schema（类别/字段）+ Prompt + 规则脚本 + LLM 资源
  const tb = (await api('POST', `/kb/${kb.id}/term-bases`, { name: '材料库', source_type: 'manual', auto_import: true, import_data: [{ term: '抗拉强度', standard_name: '拉伸强度' }] }, token)).body.data
  const tpl = (await api('POST', `/kb/${kb.id}/schema-templates`, { name: '材料检测模板' }, token)).body.data
  const cat = (await api('POST', `/kb/${kb.id}/schema-templates/${tpl.id}/categories`, {
    name: '室温拉伸', fixed_query: '室温拉伸 抗拉强度',
    query_sources: [{ label: '材料库', term_base_id: tb.id, value_field: 'standard_name', in_query: true }],
  }, token)).body.data
  await api('POST', `/kb/${kb.id}/schema-templates/${tpl.id}/categories/${cat.id}/fields`, { name: '抗拉强度', type: 'string', required: true, description: '室温拉伸抗拉强度值' }, token)
  const prompt = (await api('POST', `/kb/${kb.id}/extraction-config/prompts`, { name: '材料抽取', scope: 'schema', schema_template_id: tpl.id, category_ids: [cat.id] }, token)).body.data
  await api('PUT', `/kb/${kb.id}/extraction-config/prompts/${prompt.id}/save`, {
    system_prompt: '你是材料检测专家，只输出 JSON，不要输出解释。',
    categories: [{ category_id: cat.id, user_prompt: '从文档上下文中抽取「${feature}」的数据。字段：${抗拉强度}。术语参考：${材料库.standard_name}。只输出 JSON 数组：[{"抗拉强度": "值"}]。文档：\n${context}' }],
  }, token)
  const script = (await api('POST', `/kb/${kb.id}/extraction-config/scripts`, { folder: 'post', name: 'normalize', code: "def run(args):\n    return {'records': args['records']}" }, token)).body.data
  const gid = (await api('POST', `/kb/${kb.id}/extraction-config/rule-groups`, { schema_template_id: tpl.id }, token)).body.data.id
  await api('PUT', `/kb/${kb.id}/extraction-config/rule-groups/${gid}/items`, { category_id: cat.id, items: [{ script_id: script.id, stage: 'post' }] }, token)
  await api('PUT', `/kb/${kb.id}/resources/llm`, { enabled: true, api_base: 'http://127.0.0.1:9988/v1', model: 'Qwen3.6-35B-A3B-FP8', api_key: '', timeout: 180 }, token)

  // 上传 + 解析 + 索引
  const form = new FormData()
  form.append('file', new Blob([Buffer.from(RICH_PDF, 'base64')], { type: 'application/pdf' }), 'extract.pdf')
  const up = await fetch(`${API}/kb/${kb.id}/documents`, { method: 'POST', headers: h, body: form })
  const upJson = await up.json()
  if (up.status !== 200) throw new Error(`上传失败：${upJson.message}`)
  const docId = upJson.data.document.id
  await api('POST', `/kb/${kb.id}/documents/${docId}/start`, null, token)
  await waitDocumentReady(token, kb.id, docId)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)
  await page.goto(`${BASE}/kb/${kb.id}/extraction`, { waitUntil: 'networkidle' })
  await page.waitForSelector('[data-testid^="btn-extract-"]', { timeout: 20000 })

  // 1. 列表页
  results.push({ id: 'E6-01', name: '列表页展示可抽取文档', pass: (await page.textContent('body')).includes('extract.pdf') })

  // 2. 进入详情并开始抽取（真实 LLM）
  await page.locator('[data-testid^="btn-extract-"]').first().click()
  await page.waitForSelector('button:has-text("开始抽取")', { timeout: 20000 })
  await page.locator('button:has-text("开始抽取")').first().click()
  const completed = await page.waitForFunction(() => document.body.innerText.includes('表格视图'), null, { timeout: 240000 }).catch(() => null)
  results.push({ id: 'E6-02', name: '真实 LLM 抽取完成（表格视图出现）', pass: completed !== null })

  // 3. 表格结果包含记录
  await page.locator('button:has-text("室温拉伸")').first().click()
  await page.waitForTimeout(400)
  const tableBody = await page.textContent('body')
  results.push({ id: 'E6-03', name: '表格结果展示抽取记录', pass: tableBody.includes('抗拉强度') && tableBody.includes('条记录') })

  // 4. JSON 视图
  await page.locator('button:has-text("JSON 视图")').first().click()
  await page.waitForTimeout(500)
  const jsonText = await page.textContent('body')
  results.push({ id: 'E6-04', name: 'JSON 视图展示完整结果', pass: jsonText.includes('抗拉强度') && jsonText.includes('summary') })

  // 5. 历史记录
  await page.locator('button:has-text("历史记录")').first().click()
  await page.waitForTimeout(800)
  const histBody = await page.textContent('body')
  results.push({ id: 'E6-05', name: '历史记录包含本次版本', pass: histBody.includes('材料检测模板') || histBody.includes('1 个类别') || histBody.includes('点击查看此版本结果') })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // 6. 导出 CSV（API 校验）
  const csv = await fetch(`${API}/kb/${kb.id}/extraction/export?document_id=${docId}`, { headers: h })
  const csvText = await csv.text()
  results.push({ id: 'E6-06', name: '导出 CSV 包含记录', pass: csv.status === 200 && csvText.includes('抗拉强度') })

  // 7. 截图（帮助文档）
  await page.screenshot({ path: HELP_IMG, fullPage: true })
  results.push({ id: 'E6-07', name: '帮助截图生成（structured-extraction.png）', pass: true })

  // 8. 删除结果
  await page.locator('button:has-text("删除结果")').first().click()
  await page.waitForTimeout(300)
  await page.locator('button:has-text("删除")').last().click()
  await page.waitForTimeout(1000)
  const afterDel = await page.textContent('body')
  results.push({ id: 'E6-08', name: '删除结果与历史', pass: afterDel.includes('暂无抽取结果') })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-E6 真实 LLM 结构化抽取全成功链路 E2E 报告',
    '',
    `- 日期：${new Date().toISOString().slice(0, 10)}`,
    `- LLM：http://127.0.0.1:9988/v1 · Qwen3.6-35B-A3B-FP8`,
    `- 通过：${passed}/${results.length}`,
    '',
    '| 场景 | 结果 |',
    '|------|------|',
    ...results.map((r) => `| ${r.id} ${r.name} | ${r.pass ? '✅' : '❌'} |`),
    '',
    errors.length ? `## 控制台错误\n\n${errors.join('\n')}\n` : '## 控制台错误\n\n无\n',
  ].join('\n')
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_E6_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
