<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { FileQuestion } from 'lucide-vue-next'

const router = useRouter()
</script>

<template>
  <div class="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background p-6 text-center">
    <div class="flex size-16 items-center justify-center rounded-lg bg-muted text-muted-foreground">
      <FileQuestion class="size-8" :stroke-width="1.25" />
    </div>
    <div class="space-y-2">
      <p class="font-mono text-5xl font-semibold tabular-nums text-foreground">404</p>
      <h2 class="text-xl font-medium text-foreground">页面未找到</h2>
      <p class="text-sm text-muted-foreground">请求的路径不存在或已被移除</p>
    </div>
    <Button @click="router.push('/')">返回首页</Button>
  </div>
</template>
