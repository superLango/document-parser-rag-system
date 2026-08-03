<script setup lang="ts">
/**
 * 批量操作工具栏
 *
 * 在列表顶部展示已选数量与可执行的批量操作按钮。
 * 当 selectedCount > 0 时固定显示，提供清空选择入口。
 *
 * 用法：
 *   <BatchActionbar :selected-count="sel.selectedCount.value" @clear="sel.clear">
 *     <Button @click="onBatchDelete">批量删除</Button>
 *   </BatchActionbar>
 */
import { X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

defineProps<{
  selectedCount: number
  /** 是否在操作中（禁用按钮） */
  loading?: boolean
}>()

const emit = defineEmits<{
  clear: []
}>()
</script>

<template>
  <Transition
    enter-active-class="transition duration-200 ease-out"
    enter-from-class="opacity-0 -translate-y-2"
    enter-to-class="opacity-100 translate-y-0"
    leave-active-class="transition duration-150 ease-in"
    leave-from-class="opacity-100 translate-y-0"
    leave-to-class="opacity-0 -translate-y-2"
  >
    <div
      v-if="selectedCount > 0"
      class="mb-3 flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2.5 shadow-sm"
    >
      <span class="text-sm font-medium text-foreground">
        已选择 <span class="text-primary">{{ selectedCount }}</span> 项
      </span>
      <div class="flex flex-1 flex-wrap items-center gap-2">
        <slot />
      </div>
      <Button
        variant="ghost"
        size="sm"
        :disabled="loading"
        @click="emit('clear')"
      >
        <X class="size-4" :stroke-width="1.5" />
        清空
      </Button>
    </div>
  </Transition>
</template>
