<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { TabsList } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: string; variant?: 'default' | 'underline' }>()

const containerRef = ref<HTMLDivElement | null>(null)
const activeIndicator = ref({ left: 0, width: 0, opacity: 0 })

const updateIndicator = () => {
  if (!containerRef.value) return
  const activeTrigger = containerRef.value.querySelector('[data-state="active"]') as HTMLElement | null
  const tabsListEl = containerRef.value.querySelector('[role="tablist"]') as HTMLElement | null
  if (activeTrigger && tabsListEl) {
    const listRect = tabsListEl.getBoundingClientRect()
    const triggerRect = activeTrigger.getBoundingClientRect()
    activeIndicator.value = {
      left: triggerRect.left - listRect.left,
      width: triggerRect.width,
      opacity: 1,
    }
  } else {
    activeIndicator.value.opacity = 0
  }
}

let observer: MutationObserver | null = null

onMounted(async () => {
  await nextTick()
  updateIndicator()
  if (containerRef.value) {
    observer = new MutationObserver(() => {
      requestAnimationFrame(updateIndicator)
    })
    observer.observe(containerRef.value, {
      attributes: true,
      subtree: true,
      attributeFilter: ['data-state'],
    })
  }
  window.addEventListener('resize', updateIndicator)
})

onUnmounted(() => {
  observer?.disconnect()
  window.removeEventListener('resize', updateIndicator)
})
</script>

<template>
  <div ref="containerRef" class="relative">
    <TabsList
      :class="
        cn(
          'relative inline-flex items-center justify-center gap-1',
          props.variant === 'underline'
            ? 'h-10 w-full border-b border-border bg-transparent p-0 gap-0'
            : 'h-10 rounded-xl bg-muted/60 p-1 text-muted-foreground',
          props.class,
        )
      "
    >
      <span
        v-if="props.variant === 'underline'"
        class="absolute bottom-0 h-0.5 bg-primary rounded-full shadow-sm shadow-primary/40 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] pointer-events-none z-10"
        :style="{
          left: `${activeIndicator.left}px`,
          width: `${activeIndicator.width}px`,
          opacity: activeIndicator.opacity,
        }"
      />
      <span
        v-else
        class="absolute h-8 rounded-lg bg-background shadow-sm transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] pointer-events-none"
        :style="{
          left: `${activeIndicator.left}px`,
          width: `${activeIndicator.width}px`,
          opacity: activeIndicator.opacity,
          top: '4px',
        }"
      />
      <slot />
    </TabsList>
  </div>
</template>
