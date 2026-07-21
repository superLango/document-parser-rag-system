<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, AlertCircle, AlertTriangle, Info, Loader2, X } from 'lucide-vue-next'
import type { ToastRecord, ToastVariant } from './useToast'
import { cn } from '@/lib/utils'

const props = defineProps<{
  toast: ToastRecord
}>()

const emit = defineEmits<{
  dismiss: [id: string]
}>()

// 变体 → 图标映射
const iconFor = computed(() => {
  const map: Record<ToastVariant, typeof CheckCircle2> = {
    success: CheckCircle2,
    error: AlertCircle,
    warning: AlertTriangle,
    info: Info,
    loading: Loader2,
    default: Info,
  }
  return map[props.toast.variant]
})

// 变体 → 颜色类（左侧图标 + 标题色）
const variantClass = computed(() => {
  const map: Record<ToastVariant, string> = {
    success: 'text-success',
    error: 'text-destructive',
    warning: 'text-warning',
    info: 'text-info',
    loading: 'text-primary animate-spin',
    default: 'text-foreground',
  }
  return map[props.toast.variant]
})
</script>

<template>
  <div
    role="alert"
    :class="
      cn(
        'pointer-events-auto relative flex w-full items-start gap-3 overflow-hidden rounded-lg border border-border bg-popover p-4 shadow-lg',
        'transition-all duration-300 ease-out',
      )
    "
  >
    <!-- 图标 -->
    <component
      :is="iconFor"
      :class="cn('mt-0.5 size-5 shrink-0', variantClass)"
      :stroke-width="1.5"
    />

    <!-- 内容 -->
    <div class="flex-1 space-y-1">
      <p v-if="toast.title" class="text-sm font-medium leading-snug text-foreground">
        {{ toast.title }}
      </p>
      <p v-if="toast.description" class="text-xs leading-relaxed text-muted-foreground">
        {{ toast.description }}
      </p    >
    </div>

    <!-- 关闭按钮 -->
    <button
      v-if="toast.dismissible"
      type="button"
      class="shrink-0 rounded-md p-1 text-muted-foreground/70 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label="关闭通知"
      @click="emit('dismiss', toast.id)"
    >
      <X class="size-3.5" :stroke-width="1.5" />
    </button>
  </div>
</template>
