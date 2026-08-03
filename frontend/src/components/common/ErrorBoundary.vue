<script setup lang="ts">
/**
 * 错误边界组件（阶段 4 - 错误边界）。
 *
 * 通过 ``onErrorCaptured`` 捕获子组件树抛出的运行时错误，展示友好的错误提示，
 * 阻止错误向上传播导致整页白屏。
 *
 * 用法：
 *   <ErrorBoundary>
 *     <router-view />
 *   </ErrorBoundary>
 *
 * 注意：``onErrorCaptured`` 仅捕获组件渲染、生命周期、事件处理器中的同步错误，
 * 不捕获异步回调（Promise rejection）与事件冒泡。异步错误请用 ``useErrorHandler``。
 */
import { ref, onErrorCaptured } from 'vue'
import { Button } from '@/components/ui/button'
import { AlertTriangle, RefreshCw } from 'lucide-vue-next'

const error = ref<Error | null>(null)
// 用于强制重新渲染 slot 内容的 key
const renderKey = ref(0)

onErrorCaptured((err) => {
  error.value = err instanceof Error ? err : new Error(String(err))
  // eslint-disable-next-line no-console
  console.error('[ErrorBoundary] 组件渲染出错', err)
  // 阻止错误向上传播
  return false
})

function retry() {
  error.value = null
  // 通过递增 key 强制 slot 重新挂载，避免整页 reload 丢失状态
  renderKey.value++
}
</script>

<template>
  <div
    v-if="error"
    class="flex min-h-[320px] flex-col items-center justify-center gap-4 p-6 text-center"
  >
    <div class="flex size-12 items-center justify-center rounded-lg bg-danger/10 text-danger">
      <AlertTriangle class="size-6" :stroke-width="1.5" />
    </div>
    <div class="space-y-1">
      <h3 class="text-base font-medium text-foreground">组件渲染出错</h3>
      <p class="max-w-md text-sm text-muted-foreground">{{ error.message }}</p>
    </div>
    <Button size="sm" @click="retry">
      <RefreshCw class="size-3.5" :stroke-width="1.5" />
      重试
    </Button>
  </div>
  <slot v-else :key="renderKey" />
</template>
