<script setup lang="ts">
/**
 * 500 Server Error 页面（阶段 4 - 错误边界）。
 *
 * 当服务器返回内部错误时展示，提供返回首页的入口。
 */
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { ServerCrash } from 'lucide-vue-next'

const router = useRouter()
</script>

<template>
  <div class="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background p-6 text-center">
    <div class="flex size-16 items-center justify-center rounded-lg bg-danger/10 text-danger">
      <ServerCrash class="size-8" :stroke-width="1.25" />
    </div>
    <div class="space-y-2">
      <p class="font-mono text-5xl font-semibold tabular-nums text-foreground">500</p>
      <h2 class="text-xl font-medium text-foreground">服务器错误</h2>
      <p class="text-sm text-muted-foreground">服务器遇到内部错误，请稍后重试</p>
    </div>
    <Button @click="router.push('/')">返回首页</Button>
  </div>
</template>
