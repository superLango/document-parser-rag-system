<script setup lang="ts">
/**
 * 403 Forbidden 页面（阶段 4 - 错误边界）。
 *
 * 当用户访问无权限的资源或路由时展示。
 */
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { ShieldX } from 'lucide-vue-next'

const router = useRouter()
</script>

<template>
  <div class="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background p-6 text-center">
    <div class="flex size-16 items-center justify-center rounded-lg bg-danger/10 text-danger">
      <ShieldX class="size-8" :stroke-width="1.25" />
    </div>
    <div class="space-y-2">
      <p class="font-mono text-5xl font-semibold tabular-nums text-foreground">403</p>
      <h2 class="text-xl font-medium text-foreground">权限不足</h2>
      <p class="text-sm text-muted-foreground">您没有访问此页面的权限</p>
    </div>
    <Button @click="router.push('/')">返回首页</Button>
  </div>
</template>
