<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

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
  <router-view v-slot="{ Component }">
    <transition name="fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
</template>

<style lang="scss">
@use './styles/transitions.scss';
</style>
