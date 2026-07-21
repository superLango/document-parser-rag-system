<script setup lang="ts">
import { computed } from 'vue'
import { FileText, ListChecks, Braces, BookOpen, CheckCircle2, Clock, AlertCircle, Loader2 } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

/**
 * 状态徽章
 * 用于文档与任务状态统一展示
 */

type StatusKind = 'document' | 'task'

const props = defineProps<{
  status: string
  kind?: StatusKind
  class?: string
}>()

// 状态配置：标签 + 颜色 + 图标
const statusConfig: Record<string, { label: string; variant: string; icon: typeof CheckCircle2 }> = {
  // 文档状态
  pending: { label: '待解析', variant: 'secondary', icon: Clock },
  parsing: { label: '解析中', variant: 'info', icon: Loader2 },
  completed: { label: '已完成', variant: 'success', icon: CheckCircle2 },
  failed: { label: '已失败', variant: 'danger', icon: AlertCircle },
  // 任务状态
  queued: { label: '排队中', variant: 'secondary', icon: Clock },
  running: { label: '运行中', variant: 'info', icon: Loader2 },
  success: { label: '已完成', variant: 'success', icon: CheckCircle2 },
}

const config = computed(() => statusConfig[props.status] ?? { label: props.status, variant: 'secondary', icon: Clock })

const variantClass = computed(() => {
  const map: Record<string, string> = {
    success: 'bg-success/15 text-success',
    danger: 'bg-danger/15 text-danger',
    info: 'bg-info/15 text-info',
    warning: 'bg-warning/15 text-warning',
    secondary: 'bg-muted text-muted-foreground',
  }
  return map[config.value.variant] || map.secondary
})

const isAnimated = computed(() => props.status === 'parsing' || props.status === 'running')
</script>

<template>
  <span
    :class="
      cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        variantClass,
        props.class,
      )
    "
  >
    <component
      :is="config.icon"
      class="size-3"
      :stroke-width="1.5"
      :class="isAnimated ? 'animate-spin' : ''"
    />
    <span>{{ config.label }}</span>
  </span>
</template>
