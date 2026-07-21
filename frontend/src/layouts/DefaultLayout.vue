<script setup lang="ts">
/**
 * 默认布局壳
 *
 * 实际工作委托给 AppShell，保留此文件是为了与路由配置兼容
 * （router/index.ts 中 DefaultLayout 仍是主布局组件）
 */
import AppShell from './AppShell.vue'
</script>

<template>
  <AppShell />
</template>
