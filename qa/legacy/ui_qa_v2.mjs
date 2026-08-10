import { chromium } from 'playwright'

const browser = await chromium.launch()
const errors = []

// ===== 桌面端（1600x900） =====
const context = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.5 })
const page = await context.newPage()
page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`console: ${msg.text()}`) })

// 登录页
await page.goto('http://127.0.0.1:5174/login', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
await page.screenshot({ path: '/tmp/ui_login_v2.png' })

// 登录进入工作台
await page.fill('#username', 'admin')
await page.fill('#password', 'admin123')
await page.click('button[type="submit"]')
await page.waitForURL('http://127.0.0.1:5174/', { timeout: 15000 })
await page.waitForTimeout(2800)
await page.screenshot({ path: '/tmp/ui_dashboard_v2.png' })

// 工作台视口适配检查
const fit = await page.evaluate(() => ({
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  clientWidth: document.documentElement.clientWidth,
  scrollWidth: document.documentElement.scrollWidth,
  canScrollX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
}))
console.log('VIEWPORT_FIT', JSON.stringify(fit))

// 用户管理 + 打开新建弹窗
await page.goto('http://127.0.0.1:5174/admin/users', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
await page.screenshot({ path: '/tmp/ui_users_v2.png' })
await page.click('text=新建用户')
await page.waitForTimeout(600)
await page.screenshot({ path: '/tmp/ui_users_dialog_v2.png' })
await page.click('button[aria-label="关闭"]')
await page.waitForTimeout(300)

// 审计日志
await page.goto('http://127.0.0.1:5174/admin/audit-logs', { waitUntil: 'networkidle' })
await page.waitForTimeout(1400)
await page.screenshot({ path: '/tmp/ui_audit_v2.png' })

// 个人中心
await page.goto('http://127.0.0.1:5174/profile', { waitUntil: 'networkidle' })
await page.waitForTimeout(1000)
await page.screenshot({ path: '/tmp/ui_profile_v2.png' })

// ===== 移动端（390x844） =====
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
const mpage = await mobile.newPage()
mpage.on('pageerror', (err) => errors.push(`mobile pageerror: ${err.message}`))
await mpage.goto('http://127.0.0.1:5174/login', { waitUntil: 'networkidle' })
await mpage.waitForTimeout(900)
await mpage.screenshot({ path: '/tmp/ui_login_mobile_v2.png' })
await mpage.fill('#username', 'admin')
await mpage.fill('#password', 'admin123')
await mpage.click('button[type="submit"]')
await mpage.waitForURL('http://127.0.0.1:5174/', { timeout: 15000 })
await mpage.waitForTimeout(2400)
const mfit = await mpage.evaluate(() => ({
  innerWidth: window.innerWidth,
  scrollWidth: document.documentElement.scrollWidth,
  canScrollX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
}))
console.log('MOBILE_FIT', JSON.stringify(mfit))
await mpage.screenshot({ path: '/tmp/ui_dashboard_mobile_v2.png' })

await browser.close()
console.log('ERRORS', errors.length ? JSON.stringify(errors) : 'none')
console.log('QA_DONE')
