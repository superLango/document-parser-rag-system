/**
 * HansonDOC RAG Service Worker（P3-11 PWA 基础）。
 *
 * 实现基础的离线缓存策略：
 * - 静态资源（JS/CSS/字体）：缓存优先（Cache First）
 * - API 请求：网络优先（Network First），失败回退缓存
 * - 导航请求：网络优先，失败回退离线页面
 *
 * 版本管理：通过 CACHE_VERSION 控制缓存更新，激活时清理旧版本。
 */

const CACHE_VERSION = 'v1'
const STATIC_CACHE = `hansondoc-static-${CACHE_VERSION}`
const API_CACHE = `hansondoc-api-${CACHE_VERSION}`

// 预缓存的静态资源
const PRECACHE_URLS = ['/', '/index.html']

// 不缓存的路径（SSE、实时流不可缓存）
const NO_CACHE_PATTERNS = [
  '/notifications/subscribe',
  '/qa/stream',
  '/extraction/stream',
  '/metrics',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== API_CACHE)
          .map((key) => caches.delete(key)),
      ),
    ).then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // 跳过非 GET 请求
  if (request.method !== 'GET') return

  // 跳过 SSE / 流式端点（不可缓存）
  if (NO_CACHE_PATTERNS.some((p) => url.pathname.includes(p))) return

  // 跨域请求直接放行
  if (url.origin !== self.location.origin) return

  // API 请求：网络优先
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, API_CACHE))
    return
  }

  // 静态资源：缓存优先
  event.respondWith(cacheFirst(request, STATIC_CACHE))
})

/**
 * 缓存优先策略：先查缓存，未命中再请求网络。
 */
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request)
  if (cached) return cached
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(cacheName)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    // 离线且无缓存：返回基础离线响应
    return new Response('离线模式', { status: 503, statusText: 'Offline' })
  }
}

/**
 * 网络优先策略：先请求网络，失败回退缓存。
 */
async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(cacheName)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    const cached = await caches.match(request)
    if (cached) return cached
    return new Response(JSON.stringify({ code: -1, message: '网络不可用' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
