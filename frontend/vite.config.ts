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
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
