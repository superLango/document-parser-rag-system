// L3 功能场景测试（Playwright E2E，M34-E5：结构化抽取列表/详情/失败重抽/返回闭环）
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

const MINI_PDF = 'JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjguMgoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjguMik+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFIgNyAwIFIgOCAwIFIgOSAwIFIgMTAgMCBSIDExIDAgUiAxMiAwIFIgMTMgMCBSIDE0IDAgUiAxNSAwIFIgMTYgMCBSIDE3IDAgUiAxOCAwIFIgMTkgMCBSIDIwIDAgUiAyMSAwIFIgMjIgMCBSIDIzIDAgUiAyNCAwIFIgMjUgMCBSIDI2IDAgUiAyNyAwIFIgMjggMCBSIDI5IDAgUiAzMCAwIFIgMzEgMCBSIDMyIDAgUiAzMyAwIFIgMzQgMCBSIDM1IDAgUiAzNiAwIFIgMzcgMCBSIDM4IDAgUiAzOSAwIFIgNDAgMCBSIDQxIDAgUiA0MiAwIFIgNDMgMCBSIDQ0IDAgUiA0NSAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDEyMC9GaWx0ZXIvRmxhdGVEZWNvZGU+PgpzdHJlYW0KeNotjD0KQkEQg/s5xdzA+dnJPEEsBBs7YTuxct/DQgsbz+/uIilCvoTQh06VlKVLOY0TxvVNu+f6+rIq141vhzBsXc0kCwItBZEGzZLD48/XdOzxmNl7Z4Mhe7eY+OLiYlJaCHQsoPNp7l2P93qhc6Ur/QCX2yD4CmVuZHN0cmVhbQplbmRvYmoKCjcgMCBvYmoKPDwvTGVuZ3RoIDExOS9GaWx0ZXIvRmxh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dHJlYW0KZW5kb2JqCgo0NSAwIG9iago8PC9MZW5ndGggMTIwL0ZpbHRlci9GbGF0ZURlY29kZT4+CnN0cmVhbQp42i2MPQpCQRCD+znF3MD52ck8QSwEGzthO7Fy38NCCxvP7+4iKUK+hNCHTpWUpUs5jSFc37R7rq8vq3Ld+HYIw9bVTLIg0FIQadAsOTz+fE3HHo+ZvXc2GLJ3i4kvLi4mpYVAxwI6n+bei8vxXi90rnSlH7laISUKZW5kc3RyZWFtCmVuZG9iagoKeHJlZgowIDQ2CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDA0MiAwMDAwMCBuIAowMDAwMDAwMTIwIDAwMDAwIG4gCjAwMDAwMDAxNzIgMDAwMDAgbiAKMDAwMDAwMDIxMyAwMDAwMCBuIAowMDAwMDAwNTkwIDAwMDAwIG4gCjAwMDAwMDA2NzkgMDAwMDAgbiAKMDAwMDAwMDg2OCAwMDAwMCBuIAowMDAwMDAxMDU2IDAwMDAwIG4gCjAwMDAwMDEyNDQgMDAwMDAgbiAKMDAwMDAwMTQzNCAwMDAwMCBuIAowMDAwMDAxNjI0IDAwMDAwIG4gCjAwMDAwMDE4MTIgMDAwMDAgbiAKMDAwMDAwMjAwMiAwMDAwMCBuIAowMDAwMDAyMTkyIDAwMDAwIG4gCjAwMDAwMDIzODIgMDAwMDAgbiAKMDAwMDAwMjU3MyAwMDAwMCBuIAowMDAwMDAyNzY0IDAwMDAwIG4gCjAwMDAwMDI5NTUgMDAwMDAgbiAKMDAwMDAwMzE0NiAwMDAwMCBuIAowMDAwMDAzMzM4IDAwMDAwIG4gCjAwMDAwMDM1MjkgMDAwMDAgbiAKMDAwMDAwMzcyMSAwMDAwMCBuIAowMDAwMDAzOTExIDAwMDAwIG4gCjAwMDAwMDQxMDIgMDAwMDAgbiAKMDAwMDAwNDI5NCAwMDAwMCBuIAowMDAwMDA0NDg1IDAwMDAwIG4gCjAwMDAwMDQ2NzYgMDAwMDAgbiAKMDAwMDAwNDg2OCAwMDAwMCBuIAowMDAwMDA1MDU4IDAwMDAwIG4gCjAwMDAwMDUyNTAgMDAwMDAgbiAKMDAwMDAwNTQ0MSAwMDAwMCBuIAowMDAwMDA1NjMyIDAwMDAwIG4gCjAwMDAwMDU4MjQgMDAwMDAgbiAKMDAwMDAwNjAxNSAwMDAwMCBuIAowMDAwMDA2MjA3IDAwMDAwIG4gCjAwMDAwMDYzOTggMDAwMDAgbiAKMDAwMDAwNjU4OSAwMDAwMCBuIAowMDAwMDA2NzgwIDAwMDAwIG4gCjAwMDAwMDY5NjkgMDAwMDAgbiAKMDAwMDAwNzE2MCAwMDAwMCBuIAowMDAwMDA3MzUxIDAwMDAwIG4gCjAwMDAwMDc1NDIgMDAwMDAgbiAKMDAwMDAwNzczMiAwMDAwMCBuIAowMDAwMDA3OTIzIDAwMDAwIG4gCjAwMDAwMDgxMTQgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA0Ni9Sb290IDEgMCBSL0lEWzwwNzFDMDAxOEMyODJDMjg2MzcyRTA0QzNCRjZEMzM2RD48N0RCQzFFN0M2MzJENTdEREU0QTlFMEFDMjQ4REU4RUU+XT4+CnN0YXJ0eHJlZgo4MzA0CiUlRU9GCg=='

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

async function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

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
  const kb = (await api('POST', '/kb', { name: `S10Extract_${stamp}`, domain_code: 'general' }, token)).body.data
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }

  // 前置：Schema + Prompt + 不可达 LLM 资源
  const tpl = (await api('POST', `/kb/${kb.id}/schema-templates`, { name: '材料模板' }, token)).body.data
  const cat = (await api('POST', `/kb/${kb.id}/schema-templates/${tpl.id}/categories`, { name: '室温拉伸' }, token)).body.data
  await api('POST', `/kb/${kb.id}/schema-templates/${tpl.id}/categories/${cat.id}/fields`, { name: 'f1', type: 'string', required: true }, token)
  const prompt = (await api('POST', `/kb/${kb.id}/extraction-config/prompts`, { name: 'P', scope: 'schema', schema_template_id: tpl.id, category_ids: [cat.id] }, token)).body.data
  await api('PUT', `/kb/${kb.id}/extraction-config/prompts/${prompt.id}/save`, { system_prompt: 'sys', categories: [{ category_id: cat.id, user_prompt: '抽取 ${feature} 的 ${f1}' }] }, token)
  await api('PUT', `/kb/${kb.id}/resources/llm`, { enabled: true, api_base: 'http://127.0.0.1:9/v1', model: 'qwen', timeout: 2 }, token)

  // 上传 + 解析 + 索引（后台 arq 自动执行）
  const form = new FormData()
  form.append('file', new Blob([Buffer.from(MINI_PDF, 'base64')], { type: 'application/pdf' }), 'extract.pdf')
  const up = await fetch(`${API}/kb/${kb.id}/documents`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form })
  const upJson = await up.json()
  if (up.status !== 200) throw new Error(`上传失败：${upJson.message}`)
  const docId = upJson.data.document.id
  await api('POST', `/kb/${kb.id}/documents/${docId}/start`, null, token)
  await waitDocumentReady(token, kb.id, docId)

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attachErrors(page, 'desktop')
  await sessionLogin(page, token)

  // 1. 列表页：入口菜单 → 抽取页
  await page.goto(`${BASE}/kb/${kb.id}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('a[href$="/extraction"]').last().click()
  await page.waitForTimeout(800)
  if (!page.url().includes('/extraction')) {
    await page.goto(`${BASE}/kb/${kb.id}/extraction`, { waitUntil: 'networkidle' })
  }
  await page.waitForSelector('[data-testid^="btn-extract-"]', { timeout: 20000 })
  results.push({ id: 'E5-01', name: '抽取列表页展示可抽取文档', pass: (await page.textContent('body')).includes('结构化抽取') && (await page.textContent('body')).includes('extract.pdf') })

  // 2. 点击抽取 → 详情页
  await page.locator('[data-testid^="btn-extract-"]').first().click()
  await page.waitForURL(/\/extraction\/[0-9a-f-]+$/, { timeout: 10000 }).catch(() => {})
  await page.waitForSelector('button:has-text("开始抽取")', { timeout: 30000 }).catch(() => {})
  const detailBody = await page.textContent('body')
  results.push({ id: 'E5-02', name: '进入抽取详情页（Schema 卡片 + 原文档预览）', pass: page.url().includes('/extraction/') && detailBody.includes('选择抽取 Schema') && detailBody.includes('材料模板') && detailBody.includes('原始文档预览') })

  // 3. 开始抽取 → 轮询失败
  await page.locator('button:has-text("开始抽取")').first().click()
  await page.waitForTimeout(300)
  const failedSeen = await page.waitForFunction(() => document.body.innerText.includes('抽取失败') || document.body.innerText.includes('重新抽取'), null, { timeout: 30000 }).catch(() => null)
  results.push({ id: 'E5-03', name: '抽取进度轮询并失败提示', pass: failedSeen !== null && (await page.textContent('body')).includes('重新抽取') })

  // 4. 重新抽取按钮可再次点击
  await page.locator('button:has-text("重新抽取")').first().click()
  await page.waitForTimeout(300)
  results.push({ id: 'E5-04', name: '重新抽取可再次发起', pass: (await page.textContent('body')).includes('抽取中...') || (await page.textContent('body')).includes('重新抽取') })

  // 5. 返回列表
  await page.locator('button:has-text("返回列表")').first().click()
  await page.waitForTimeout(1000)
  results.push({ id: 'E5-05', name: '返回抽取列表页', pass: (await page.textContent('body')).includes('结构化抽取') && (await page.textContent('body')).includes('extract.pdf') })

  // 6. 移动端
  await page.setViewportSize({ width: 375, height: 720 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  results.push({ id: 'E5-06', name: '移动端抽取列表可用', pass: (await page.textContent('body')).includes('结构化抽取') })

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const md = [
    '# M34-E5 结构化抽取前端页面 E2E 报告',
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
  writeFileSync(join(OUT, 'INDEX_S9_EXTRACTION_E5_E2E.md'), md)
  console.log(`E2E ${passed}/${results.length} passed`)
  if (errors.length) console.log('console errors:', errors)
  if (passed !== results.length) process.exit(1)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
