<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '@/stores/app'
import { PanelLeft, Menu, Search, Command } from 'lucide-vue-next'
import { Tooltip } from '@/components/ui/tooltip'
import AppBreadcrumb from './AppBreadcrumb.vue'
import ThemeToggle from './ThemeToggle.vue'
import UserMenu from './UserMenu.vue'
import NotificationBell from '@/components/notification/NotificationBell.vue'

const appStore = useAppStore()

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

const isMac = ref(false)
onMounted(() => {
  isMac.value = navigator.platform.toUpperCase().indexOf('MAC') >= 0
})
</script>

<template>
  <header
    class="sticky top-0 z-[1100] flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border/50 glass px-4 sm:px-6"
  >
    <!-- 左：折叠 + 面包屑 -->
    <div class="flex min-w-0 items-center gap-2">
      <Tooltip :side="'bottom'" :delay-ms="200">
        <template #trigger>
          <button
            type="button"
            class="group inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-all duration-200 hover:bg-muted/80 hover:text-foreground active:scale-95"
            :aria-label="isDesktop ? (appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏') : '打开菜单'"
            @click="handleSidebarToggle"
          >
            <PanelLeft
              v-if="isDesktop"
              class="size-4 transition-transform duration-200 group-hover:scale-110"
              :stroke-width="1.5"
              :class="{ 'rotate-180': appStore.sidebarCollapsed }"
            />
            <Menu v-else class="size-4 transition-transform duration-200 group-hover:scale-110" :stroke-width="1.5" />
          </button>
        </template>
        <span>{{ isDesktop ? (appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏') : '打开菜单' }}</span>
      </Tooltip>

      <AppBreadcrumb />
    </div>

    <!-- 右：命令入口 + 主题 + 通知 + 用户 -->
    <div class="flex items-center gap-1">
      <!-- Command Palette 触发按钮（桌面） -->
      <Tooltip :side="'bottom'" :delay-ms="200">
        <template #trigger>
          <button
            type="button"
            class="group hidden items-center gap-2.5 rounded-lg border border-border/60 bg-background/60 px-3 py-1.5 text-xs text-muted-foreground transition-all duration-200 hover:border-border hover:bg-muted/60 hover:text-foreground active:scale-[0.98] sm:flex"
            aria-label="命令面板"
            @click="appStore.openCommandPalette()"
          >
            <Search class="size-3.5 transition-transform duration-200 group-hover:scale-110" :stroke-width="1.5" />
            <span>搜索或跳转...</span>
            <kbd class="ml-auto flex items-center gap-0.5 rounded border border-border/60 bg-muted/80 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              <Command v-if="isMac" class="size-2.5" :stroke-width="2" />
              <span v-if="!isMac">Ctrl</span>
              <span>K</span>
            </kbd>
          </button>
        </template>
        <span>命令面板 ({{ isMac ? '⌘' : 'Ctrl' }}K)</span>
      </Tooltip>

      <!-- Command Palette 触发按钮（移动端） -->
      <Tooltip :side="'bottom'" :delay-ms="200">
        <template #trigger>
          <button
            type="button"
            class="group inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-all duration-200 hover:bg-muted/80 hover:text-foreground active:scale-95 sm:hidden"
            aria-label="命令面板"
            @click="appStore.openCommandPalette()"
          >
            <Search class="size-4 transition-transform duration-200 group-hover:scale-110" :stroke-width="1.5" />
          </button>
        </template>
        <span>命令面板</span>
      </Tooltip>

      <ThemeToggle />

      <NotificationBell />

      <div class="mx-1 h-5 w-px bg-border/50" />

      <UserMenu />
    </div>
  </header>
</template>
