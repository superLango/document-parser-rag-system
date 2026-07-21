<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from 'reka-ui'
import { Search, CornerDownLeft } from 'lucide-vue-next'
import { navItems, type NavItem } from './navigation'
import { useAppStore } from '@/stores/app'
import { cn } from '@/lib/utils'

/**
 * Command Palette
 * 触发：Cmd/Ctrl + K
 * 功能：搜索导航项并快速跳转
 */

const router = useRouter()
const appStore = useAppStore()

// 通过 store 双向绑定，让 TopBar 按钮也能控制开关
const open = computed({
  get: () => appStore.commandPaletteOpen,
  set: (v: boolean) => appStore.setCommandPalette(v),
})
const query = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
const activeIndex = ref(0)

// 全局快捷键 Cmd/Ctrl + K
function onKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    open.value = !open.value
  }
  // ESC 关闭
  if (e.key === 'Escape' && open.value) {
    open.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

// 打开时自动聚焦输入框
watch(open, (v) => {
  if (v) {
    query.value = ''
    activeIndex.value = 0
    nextTick(() => inputEl.value?.focus())
  }
})

// 搜索结果：按 title / keywords / description 过滤
const results = computed<NavItem[]>(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return navItems
  return navItems.filter((item) => {
    const haystack = [
      item.title,
      item.description ?? '',
      ...(item.keywords ?? []),
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(q)
  })
})

// 键盘上下选择
function onInputKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, results.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = results.value[activeIndex.value]
    if (item) navigate(item)
  }
}

function navigate(item: NavItem) {
  appStore.setCommandPalette(false)
  router.push(item.path)
}

// 重置激活索引
watch(query, () => {
  activeIndex.value = 0
})
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay
        class="fixed inset-0 z-[1299] bg-background/70 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
      />
      <DialogContent
        class="fixed left-1/2 top-[15%] z-[1300] flex -translate-x-1/2 flex-col gap-0 overflow-hidden rounded-lg border border-border bg-popover p-0 shadow-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 duration-200 w-[calc(100%-2rem)] max-w-xl"
      >
        <DialogTitle class="sr-only">命令面板</DialogTitle>
        <DialogDescription class="sr-only">
          输入页面名称或关键字快速跳转
        </DialogDescription>

        <!-- 搜索输入框 -->
        <div class="flex items-center gap-3 border-b border-border px-4">
          <Search class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
          <input
            ref="inputEl"
            v-model="query"
            type="text"
            placeholder="搜索页面或功能..."
            class="h-12 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            @keydown="onInputKeydown"
          />
          <kbd class="hidden shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground sm:inline">
            ESC
          </kbd>
        </div>

        <!-- 结果列表 -->
        <div class="max-h-80 overflow-y-auto p-2">
          <div v-if="results.length === 0" class="px-3 py-8 text-center text-sm text-muted-foreground">
            未找到匹配项
          </div>
          <ul v-else class="flex flex-col gap-0.5">
            <li v-for="(item, idx) in results" :key="item.path">
              <button
                type="button"
                :class="
                  cn(
                    'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors',
                    idx === activeIndex
                      ? 'bg-primary/10 text-primary'
                      : 'text-foreground hover:bg-muted',
                  )
                "
                @mouseenter="activeIndex = idx"
                @click="navigate(item)"
              >
                <component :is="item.icon" class="size-4 shrink-0" :stroke-width="1.5" />
                <div class="flex-1 min-w-0">
                  <div class="truncate font-medium">{{ item.title }}</div>
                  <div v-if="item.description" class="truncate text-xs text-muted-foreground">
                    {{ item.description }}
                  </div>
                </div>
                <CornerDownLeft
                  v-if="idx === activeIndex"
                  class="size-3.5 shrink-0 text-muted-foreground"
                  :stroke-width="1.5"
                />
              </button>
            </li>
          </ul>
        </div>

        <!-- 底部提示 -->
        <div class="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted-foreground">
          <div class="flex items-center gap-3">
            <span class="flex items-center gap-1">
              <kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono">↑</kbd>
              <kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono">↓</kbd>
              <span>选择</span>
            </span>
            <span class="flex items-center gap-1">
              <kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono">↵</kbd>
              <span>跳转</span>
            </span>
          </div>
          <span>Hansight Command</span>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
