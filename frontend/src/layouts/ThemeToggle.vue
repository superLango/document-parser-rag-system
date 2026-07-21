<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { Sun, Moon, Monitor } from 'lucide-vue-next'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const appStore = useAppStore()

const modes = [
  { key: 'light' as const, icon: Sun, label: '浅色' },
  { key: 'system' as const, icon: Monitor, label: '跟随系统' },
  { key: 'dark' as const, icon: Moon, label: '深色' },
]

const currentIndex = computed(() =>
  modes.findIndex((m) => m.key === appStore.themeMode),
)

function cycle() {
  const next = (currentIndex.value + 1) % modes.length
  appStore.setThemeMode(modes[next].key)
}
</script>

<template>
  <Tooltip :side="'bottom'" :delay-ms="200">
    <template #trigger>
      <button
        type="button"
        class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-label="`切换主题（当前：${modes[currentIndex].label}）`"
        @click="cycle"
      >
        <component
          :is="modes[currentIndex].icon"
          class="size-4"
          :stroke-width="1.5"
        />
      </button>
    </template>
    <span>主题：{{ modes[currentIndex].label }}</span>
  </Tooltip>
</template>
