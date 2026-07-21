<script setup lang="ts">
import { onMounted } from 'vue'
import { TooltipProvider } from 'reka-ui'
import { useAuthStore } from '@/stores/auth'
import { Toaster } from '@/components/ui/toast'

// 应用根组件：承载路由出口与过渡动画，并在挂载时恢复会话
const auth = useAuthStore()

onMounted(() => {
  // 页面刷新后：token 存在但 user 为 null 时，恢复用户信息
  if (auth.isAuthenticated && !auth.user) {
    auth.fetchUser()
  }
})
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <router-view v-slot="{ Component }">
      <transition name="fade-slide" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>

    <!-- 全局 Toast 容器 -->
    <Toaster />
  </TooltipProvider>
</template>
