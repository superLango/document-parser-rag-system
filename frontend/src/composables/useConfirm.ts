/**
 * 全局确认对话框
 *
 * 设计参考：toast composable 的 reactive 单例模式
 *
 * 使用方式：
 *   import { confirm } from '@/composables/useConfirm'
 *   if (!await confirm({ title: '确定删除？', description: '此操作不可恢复' })) return
 *   // 或简写
 *   if (!await confirm('确定删除？')) return
 */
import { reactive } from 'vue'

export interface ConfirmOptions {
  title?: string
  description?: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger'
}

interface ConfirmState {
  open: boolean
  title: string
  description: string
  confirmText: string
  cancelText: string
  variant: 'default' | 'danger'
  resolver: ((value: boolean) => void) | null
}

const state = reactive<ConfirmState>({
  open: false,
  title: '确认操作',
  description: '',
  confirmText: '确认',
  cancelText: '取消',
  variant: 'default',
  resolver: null,
})

function resolve(value: boolean) {
  if (state.resolver) {
    state.resolver(value)
    state.resolver = null
  }
  state.open = false
}

/**
 * 弹出确认对话框，返回 Promise<boolean>
 * - true: 用户点击确认
 * - false: 用户点击取消 / 关闭 / 按 ESC
 */
export function confirm(message: string): Promise<boolean>
export function confirm(options: ConfirmOptions): Promise<boolean>
export function confirm(messageOrOptions: string | ConfirmOptions): Promise<boolean> {
  const opts: ConfirmOptions =
    typeof messageOrOptions === 'string'
      ? { title: messageOrOptions }
      : messageOrOptions

  // 如果已有对话框打开，先关闭上一个（返回 false）
  if (state.open) resolve(false)

  return new Promise<boolean>((resolver) => {
    state.title = opts.title ?? '确认操作'
    state.description = opts.description ?? ''
    state.confirmText = opts.confirmText ?? '确认'
    state.cancelText = opts.cancelText ?? '取消'
    state.variant = opts.variant ?? 'default'
    state.resolver = resolver
    state.open = true
  })
}

/** 供 ConfirmDialog 组件使用 */
export function useConfirmState() {
  return state
}

/** 供 ConfirmDialog 组件调用 —— 用户点击确认 */
export function handleConfirm() {
  resolve(true)
}

/** 供 ConfirmDialog 组件调用 —— 用户点击取消 / 关闭 */
export function handleCancel() {
  resolve(false)
}
