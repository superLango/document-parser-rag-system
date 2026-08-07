<script setup lang="ts">
import { onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import AppSidebar from './AppSidebar.vue'
import AppTopBar from './AppTopBar.vue'
import CommandPalette from './CommandPalette.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

const route = useRoute()
const appStore = useAppStore()

const RESPONSIVE_BREAKPOINT = 1024
let lastWidth = 0

function handleResize() {
  const w = window.innerWidth
  if (lastWidth >= RESPONSIVE_BREAKPOINT && w < RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = true
    appStore.setMobileDrawer(false)
  }
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
          class="fixed inset-0 z-[1199] bg-background/60 backdrop-blur-sm lg:hidden transition-opacity duration-200"
          @click="appStore.setMobileDrawer(false)"
        />
        <div
          class="fixed inset-y-0 left-0 z-[1200] lg:hidden transition-transform duration-300 ease-[var(--ease-spring)]"
        >
          <AppSidebar :is-drawer="true" />
        </div>
      </template>
    </Teleport>

    <!-- 主区域 -->
    <div class="flex min-w-0 flex-1 flex-col">
      <AppTopBar />

      <main class="flex-1 overflow-y-auto bg-subtle-gradient">
        <div class="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <ErrorBoundary>
            <router-view v-slot="{ Component, route: viewRoute }">
              <transition name="fade-slide" mode="out-in">
                <component :is="Component" :key="viewRoute.fullPath" />
              </transition>
            </router-view>
          </ErrorBoundary>
        </div>
      </main>
    </div>

    <CommandPalette />
  </div>
</template>
