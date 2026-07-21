/**
 * 全局 Toast 状态管理
 *
 * 设计参考：sonner 风格 + shadcn-vue 接口约定
 * 实现方式：基于 Vue reactive() 单例，跨组件共享状态
 *
 * 使用方式：
 *   import { toast } from '@/components/ui/toast'
 *   toast.success('保存成功')
 *   toast.error('请求失败')
 */
import { reactive, readonly } from 'vue'
import type { App } from 'vue'

// ---------- 类型 ----------
export type ToastVariant = 'default' | 'success' | 'error' | 'warning' | 'info' | 'loading'

export interface ToastOptions {
  id?: string
  title?: string
  description?: string
  variant?: ToastVariant
  duration?: number // 0 表示不自动关闭
  dismissible?: boolean
}

export interface ToastRecord extends Required<Omit<ToastOptions, 'id' | 'title' | 'description'>> {
  id: string
  title?: string
  description?: string
  createdAt: number
}

interface ToastState {
  toasts: ToastRecord[]
}

// ---------- 状态 ----------
const state = reactive<ToastState>({ toasts: [] })

let counter = 0
function genId(): string {
  counter += 1
  return `toast-${Date.now()}-${counter}`
}

function dismiss(id: string): void {
  const idx = state.toasts.findIndex((t) => t.id === id)
  if (idx > -1) state.toasts.splice(idx, 1)
}

function push(opts: ToastOptions): string {
  const id = opts.id ?? genId()
  const record: ToastRecord = {
    id,
    title: opts.title,
    description: opts.description,
    variant: opts.variant ?? 'default',
    duration: opts.duration ?? 4000,
    dismissible: opts.dismissible ?? true,
    createdAt: Date.now(),
  }
  // 同 id 替换
  const idx = state.toasts.findIndex((t) => t.id === id)
  if (idx > -1) state.toasts.splice(idx, 1, record)
  else state.toasts.push(record)

  // 自动关闭（loading 默认不自动关闭）
  if (record.duration > 0 && record.variant !== 'loading') {
    setTimeout(() => dismiss(id), record.duration)
  }

  return id
}

// ---------- 公开 API ----------
export const toast = {
  /** 显示一条自定义 toast */
  show(opts: ToastOptions): string {
    return push(opts)
  },
  /** 默认样式 toast */
  message(title: string, description?: string): string {
    return push({ title, description, variant: 'default' })
  },
  success(title: string, description?: string): string {
    return push({ title, description, variant: 'success' })
  },
  error(title: string, description?: string): string {
    return push({ title, description, variant: 'error', duration: 6000 })
  },
  warning(title: string, description?: string): string {
    return push({ title, description, variant: 'warning' })
  },
  info(title: string, description?: string): string {
    return push({ title, description, variant: 'info' })
  },
  /** loading toast，返回 id 供后续 dismiss 或 update */
  loading(title: string, description?: string): string {
    return push({ title, description, variant: 'loading', duration: 0 })
  },
  /** 通过 id 关闭指定 toast */
  dismiss,
  /** 关闭所有 */
  dismissAll(): void {
    state.toasts.splice(0, state.toasts.length)
  },
}

// ---------- 组合式 API ----------
/**
 * 用于 Toaster 组件读取状态
 */
export function useToastState() {
  return readonly(state)
}

// 兼容 Vue 2 风格的全局注入（可选）
export const ToastPlugin = {
  install(app: App) {
    app.config.globalProperties.$toast = toast
  },
}

export default toast
