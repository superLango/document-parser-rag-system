<script setup lang="ts">
import { onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import AppSidebar from './AppSidebar.vue'
import AppTopBar from './AppTopBar.vue'
import CommandPalette from './CommandPalette.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

/**
 * 应用主布局壳
 *
 * 结构：
 *  ┌─────────────────────────────────────┐
 *  │ Sidebar │ TopBar                    │
 *  │         ├──────────────────────────┤
 *  │         │ Content (router-view)     │
 *  └─────────────────────────────────────┘
 *
 * 响应式：
 *  - lg 及以上：侧边栏常驻，可折叠（240px ↔ 56px）
 *  - lg 以下：侧边栏抽屉式，默认隐藏，点击按钮遮罩显示
 */

const route = useRoute()
const appStore = useAppStore()

// 响应式断点：lg (1024px) 以下视为移动端
const RESPONSIVE_BREAKPOINT = 1024
let lastWidth = 0

function handleResize() {
  const w = window.innerWidth
  // 从大屏切到小屏：自动收起
  if (lastWidth >= RESPONSIVE_BREAKPOINT && w < RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = true
    appStore.setMobileDrawer(false)
  }
  // 从小屏切到大屏：展开桌面侧边栏
  if (lastWidth > 0 && lastWidth < RESPONSIVE_BREAKPOINT && w >= RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = false
    appStore.setMobileDrawer(false)
  }
  lastWidth = w
}

onMounted(() => {
  lastWidth = window.innerWidth
  if (lastWidth < RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = true
  }
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})

// 路由切换时关闭移动抽屉
watch(
  () => route.path,
  () => {
    appStore.setMobileDrawer(false)
  },
)
</script>

<template>
  <div class="flex h-dvh w-full overflow-hidden bg-background text-foreground">
    <!-- 桌面侧边栏 -->
    <AppSidebar class="hidden lg:flex" />

    <!-- 移动端抽屉 -->
    <Teleport to="body">
      <template v-if="appStore.mobileDrawerOpen">
        <div
          class="fixed inset-0 z-[1199] bg-background/70 backdrop-blur-sm lg:hidden"
          @click="appStore.setMobileDrawer(false)"
        />
        <div class="fixed inset-y-0 left-0 z-[1200] lg:hidden">
          <AppSidebar :is-drawer="true" />
        </div>
      </template>
    </Teleport>

    <!-- 主区域 -->
    <div class="flex min-w-0 flex-1 flex-col">
      <AppTopBar />

      <main class="flex-1 overflow-y-auto">
        <div class="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <ErrorBoundary>
            <router-view v-slot="{ Component }">
              <transition name="fade-slide" mode="out-in">
                <component :is="Component" />
              </transition>
            </router-view>
          </ErrorBoundary>
        </div>
      </main>
    </div>

    <!-- 命令面板 -->
    <CommandPalette />
  </div>
</template>
