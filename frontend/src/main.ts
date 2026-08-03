import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

// Tailwind v4 + 主题样式（必须在 main 入口加载，确保 Tailwind utility 先就绪）
import './styles/globals.css'

// 自托管字体（避免 Google Fonts CDN）
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/noto-sans-sc/500.css'
import '@fontsource/noto-sans-sc/600.css'

// 前端错误监控（P2-8）：可选 Sentry CDN 集成，降级 console + localStorage
import { initErrorTracking, captureException } from '@/lib/errorTracking'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// 全局 Vue 错误处理器（P2-8）：捕获组件渲染/生命周期错误并上报
app.config.errorHandler = (err, _instance, info) => {
  captureException(err instanceof Error ? err : new Error(String(err)), { info })
}

// 初始化全局错误监控（window.onerror + unhandledrejection）
initErrorTracking()

// 在挂载前预先应用主题，避免首次渲染时的主题闪烁（FOUC）
// 通过内联脚本在 <head> 中提前应用主题是更佳方案；此处作为运行时兜底
import('./stores/app').then(({ useAppStore }) => {
  useAppStore() // 触发 watch + applyTheme
  app.mount('#app')
})
