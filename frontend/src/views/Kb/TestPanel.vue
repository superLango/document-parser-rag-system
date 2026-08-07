<script setup lang="ts">
/**
 * 组装测试面板：预览 system / user 提示词占位符组装后的效果。
 */
import { Braces } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'

interface TestResult {
  system: string
  user: string
}

defineProps<{
  result: TestResult | null
  catName?: string
}>()
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border p-2">
    <p class="flex items-center gap-1 px-1 pb-1 text-xs font-medium text-muted-foreground">
      <Braces class="size-3.5" :stroke-width="1.5" />
      测试效果
    </p>
    <div v-if="!result" class="flex flex-1 items-center justify-center px-1 py-6 text-center text-xs text-muted-foreground">
      点击"测试组装"按钮预览占位符组装后的效果
    </div>
    <div v-else class="flex-1 space-y-3 overflow-auto">
      <div v-if="catName" class="flex items-center gap-2">
        <span class="text-xs font-medium">当前类别</span>
        <Badge variant="outline">{{ catName }}</Badge>
      </div>
      <div class="space-y-1">
        <p class="text-xs font-medium text-muted-foreground">System 提示词</p>
        <pre class="whitespace-pre-wrap rounded-md border bg-muted/40 p-2 font-mono text-xs">{{ result.system || '（空）' }}</pre>
      </div>
      <div class="space-y-1">
        <p class="text-xs font-medium text-muted-foreground">User 提示词（组装后）</p>
        <pre class="whitespace-pre-wrap rounded-md border bg-muted/40 p-2 font-mono text-xs">{{ result.user || '（空）' }}</pre>
      </div>
    </div>
  </div>
</template>