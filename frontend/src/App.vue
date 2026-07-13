<script setup lang="ts">
// 应用根组件：仅承载路由出口与过渡动画
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
