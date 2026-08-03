/**
 * 前端错误监控服务（P2-8）。
 *
 * 提供统一的错误上报接口，支持可选 Sentry 集成：
 * - 若通过 CDN 引入了 Sentry（window.Sentry 存在），则上报到 Sentry
 * - 否则降级为 console.error + localStorage 错误日志缓冲
 *
 * 不强制依赖 @sentry/vue，用户可按需通过 CDN 引入：
 *   <script src="https://browser.sentry-cdn.com/8.x/bundle.min.js"></script>
 *   <script>Sentry.init({ dsn: 'YOUR_DSN', integrations: [...] })</script>
 *
 * 用法：
 *   import { captureException, initErrorTracking } from '@/lib/errorTracking'
 *   initErrorTracking()  // 在 main.ts 调用
 *   captureException(new Error('xxx'))
 */

const ERROR_BUFFER_KEY = 'hansondoc_error_buffer'
const MAX_BUFFER_SIZE = 50

interface ErrorRecord {
  timestamp: string
  message: string
  stack?: string
  url: string
  userAgent: string
}

/**
 * 初始化全局错误监控。
 *
 * 注册 window.onerror 与 unhandledrejection 监听，捕获未处理的同步错误
 * 与 Promise rejection。应在 main.ts 中调用一次。
 */
export function initErrorTracking(): void {
  // 同步错误
  window.addEventListener('error', (event) => {
    captureException(event.error || event.message, {
      type: 'global_error',
      filename: event.filename,
      lineno: event.lineno,
    })
  })

  // 未处理的 Promise rejection
  window.addEventListener('unhandledrejection', (event) => {
    captureException(event.reason instanceof Error ? event.reason : new Error(String(event.reason)), {
      type: 'unhandled_rejection',
    })
  })
}

/**
 * 上报异常到错误监控服务。
 *
 * 优先使用 Sentry（如已通过 CDN 初始化），否则降级为 console.error +
 * localStorage 缓冲（供后续批量上报或调试查看）。
 *
 * @param err 错误对象或消息字符串。
 * @param context 额外上下文信息。
 */
export function captureException(
  err: Error | string,
  context?: Record<string, unknown>,
): void {
  const error = err instanceof Error ? err : new Error(String(err))
  const record: ErrorRecord = {
    timestamp: new Date().toISOString(),
    message: error.message,
    stack: error.stack,
    url: window.location.href,
    userAgent: navigator.userAgent,
  }

  // 优先 Sentry（CDN 引入）
  const sentry = (window as unknown as { Sentry?: { captureException: (e: unknown) => void } }).Sentry
  if (sentry?.captureException) {
    try {
      sentry.captureException(error)
    } catch {
      // Sentry 上报失败，降级
    }
  }

  // 降级：console + localStorage 缓冲
  // eslint-disable-next-line no-console
  console.error('[ErrorTracking]', error, context || '')
  bufferError(record)
}

/**
 * 上报消息（非异常级别的信息）。
 */
export function captureMessage(message: string, level: 'info' | 'warning' | 'error' = 'info'): void {
  const sentry = (window as unknown as { Sentry?: { captureMessage: (m: string, l?: string) => void } }).Sentry
  if (sentry?.captureMessage) {
    try {
      sentry.captureMessage(message, level)
    } catch {
      // 降级
    }
  }
  // eslint-disable-next-line no-console
  console[level === 'error' ? 'error' : level === 'warning' ? 'warn' : 'log'](
    `[ErrorTracking:${level}]`,
    message,
  )
}

/**
 * 将错误写入 localStorage 缓冲（供调试查看，避免无限增长）。
 */
function bufferError(record: ErrorRecord): void {
  try {
    const raw = localStorage.getItem(ERROR_BUFFER_KEY)
    const buffer: ErrorRecord[] = raw ? JSON.parse(raw) : []
    buffer.unshift(record)
    if (buffer.length > MAX_BUFFER_SIZE) {
      buffer.length = MAX_BUFFER_SIZE
    }
    localStorage.setItem(ERROR_BUFFER_KEY, JSON.stringify(buffer))
  } catch {
    // localStorage 不可用时静默
  }
}

/**
 * 获取错误缓冲（供调试面板查看）。
 */
export function getErrorBuffer(): ErrorRecord[] {
  try {
    const raw = localStorage.getItem(ERROR_BUFFER_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

/**
 * 清空错误缓冲。
 */
export function clearErrorBuffer(): void {
  try {
    localStorage.removeItem(ERROR_BUFFER_KEY)
  } catch {
    // 静默
  }
}
