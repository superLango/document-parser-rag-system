<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '@/stores/app'
import { PanelLeft, Menu, Search } from 'lucide-vue-next'
import { Tooltip } from '@/components/ui/tooltip'
import AppBreadcrumb from './AppBreadcrumb.vue'
import ThemeToggle from './ThemeToggle.vue'
import UserMenu from './UserMenu.vue'
import NotificationBell from '@/components/notification/NotificationBell.vue'

const appStore = useAppStore()

// 跟踪当前是否为桌面布局（lg+）
const isDesktop = ref(true)

function updateBreakpoint() {
  isDesktop.value = window.matchMedia('(min-width: 1024px)').matches
}

onMounted(() => {
  updateBreakpoint()
  window.addEventListener('resize', updateBreakpoint)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateBreakpoint)
})

function handleSidebarToggle() {
  if (isDesktop.value) {
    appStore.toggleSidebar()
  } else {
    appStore.setMobileDrawer(true)
  }
}
</script>

<template>
  <header
    class="sticky top-0 z-[1100] flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80 sm:px-6"
  >
    <!-- 左：折叠 + 面包屑 -->
    <div class="flex min-w-0 items-center gap-3">
      <Tooltip :side="'bottom'" :delay-ms="200">
        <template #trigger>
          <button
            type="button"
            class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :aria-label="isDesktop ? (appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏') : '打开菜单'"
            @click="handleSidebarToggle"
          >
            <PanelLeft v-if="isDesktop" class="size-4" :stroke-width="1.5" />
            <Menu v-else class="size-4" :stroke-width="1.5" />
          </button>
        </template>
        <span>{{ isDesktop ? (appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏') : '打开菜单' }}</span>
      </Tooltip>

      <AppBreadcrumb />
    </div>

    <!-- 右：命令入口 + 主题 + 用户 -->
    <div class="flex items-center gap-1">
      <!-- Command Palette 触发按钮（桌面） -->
      <Tooltip :side="'bottom'" :delay-ms="200">
        <template #trigger>
          <button
            type="button"
            class="hidden items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:flex"
            aria-label="命令面板"
            @click="appStore.openCommandPalette()"
          >
            <Search class="size-3.5" :stroke-width="1.5" />
            <span>搜索</span>
            <kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">
              ⌘K
            </kbd>
          </button>
        </template>
        <span>命令面板 (⌘K)</span>
      </Tooltip>

      <!-- Command Palette 触发按钮（移动端简化） -->
      <Tooltip :side="'bottom'" :delay-ms="200">
        <template #trigger>
          <button
            type="button"
            class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:hidden"
            aria-label="命令面板"
            @click="appStore.openCommandPalette()"
          >
            <Search class="size-4" :stroke-width="1.5" />
          </button>
        </template>
        <span>命令面板</span>
      </Tooltip>

      <ThemeToggle />

      <NotificationBell />

      <div class="mx-1 h-5 w-px bg-border" />

      <UserMenu />
    </div>
  </header>
</template>
