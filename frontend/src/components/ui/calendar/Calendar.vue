<script setup lang="ts">
/**
 * Calendar 组件（实用简化版）。
 *
 * 基于原生 input[type=date] 封装，样式对齐 shadcn-vue Input。
 * 项目内日期筛选场景（审计日志、任务时间过滤）统一使用此组件，
 * 避免 reka-ui Calendar 完整日历的复杂 DOM 结构。
 *
 * 如需完整日历选择器，可后续引入 reka-ui CalendarRoot 重新封装。
 */
import { computed } from 'vue'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    class?: string
    placeholder?: string
    disabled?: boolean
  }>(),
  { placeholder: '选择日期' },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const inner = computed({
  get: () => props.modelValue ?? '',
  set: (v: string) => emit('update:modelValue', v),
})
</script>

<template>
  <input
    v-model="inner"
    type="date"
    :disabled="disabled"
    :placeholder="placeholder"
    :class="
      cn(
        'h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground shadow-sm transition-colors',
        'hover:border-primary/50 focus:outline-none focus:ring-1 focus:ring-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        props.class,
      )
    "
  />
</template>
