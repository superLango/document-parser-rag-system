import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'path'

// Vite 配置：Vue 3 + Tailwind v4 + 端口 5174 + API 代理到 :8000
// 注意：pdfjs-dist 通过 public/pdfjs/build/ 目录以 UMD 形式加载，绕过 Vite 预构建
// （ESM 版本的私有字段与 Vue 响应式代理不兼容）
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE / 流式响应配置：关闭 buffering 以支持实时推送
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            // 订阅类端点: 禁用 Nginx/Vite 层缓冲
            if (req.url && req.url.includes('/subscribe')) {
              proxyReq.setHeader('X-Accel-Buffering', 'no')
              proxyReq.setHeader('Cache-Control', 'no-cache')
            }
          })
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const ct = proxyRes.headers['content-type'] || ''
            if (ct.includes('text/event-stream')) {
              // SSE 响应头确保 Vite 不对其做缓存/聚合
              proxyRes.headers['x-accel-buffering'] = 'no'
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['content-encoding'] = 'identity'
              // 流式写入，强制 flush 每个 chunk
              const originalWrite = res.write.bind(res)
              ;(res as any).write = (chunk: any, encoding?: any, cb?: any) => {
                const ret = originalWrite(chunk, encoding, cb)
                try {
                  ;(res as any).flush?.()
                } catch {
                  /* ignore */
                }
                return ret
              }
            }
          })
        },
      },
    },
  },
})
