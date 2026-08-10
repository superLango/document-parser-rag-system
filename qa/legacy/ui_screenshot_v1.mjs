import { chromium } from 'playwright'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 })

// 1. 登录页
await page.goto('http://localhost:5174/login', { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
await page.screenshot({ path: '/tmp/hansondoc_login.png' })

// 2. 登录进入工作台
await page.fill('#username', 'admin')
await page.fill('#password', 'admin123')
await page.click('button[type="submit"]')
await page.waitForURL('http://localhost:5174/', { timeout: 15000 })
await page.waitForTimeout(2500)
await page.screenshot({ path: '/tmp/hansondoc_dashboard.png' })

// 3. 用户管理
await page.goto('http://localhost:5174/admin/users', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
await page.screenshot({ path: '/tmp/hansondoc_users.png' })

// 4. 审计日志
await page.goto('http://localhost:5174/admin/audit-logs', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
await page.screenshot({ path: '/tmp/hansondoc_audit.png' })

await browser.close()
console.log('SCREENSHOTS_DONE')
