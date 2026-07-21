<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { findNavItem } from './navigation'
import { ChevronRight } from 'lucide-vue-next'

const route = useRoute()

// 面包屑项：首页 / 当前页面
const items = computed(() => {
  const current = findNavItem(route.path)
  const title = (route.meta.title as string) || current?.title || ''
  return [{ label: '首页', path: '/' }, { label: title, path: route.path }]
})
</script>

<template>
  <nav aria-label="面包屑" class="flex items-center gap-1 text-sm">
    <template v-for="(item, idx) in items" :key="item.path">
      <router-link
        v-if="idx < items.length - 1"
        :to="item.path"
        class="text-muted-foreground transition-colors hover:text-foreground"
      >
        {{ item.label }}
      </router-link>
      <span v-else class="font-medium text-foreground">{{ item.label }}</span>
      <ChevronRight
        v-if="idx < items.length - 1"
        class="size-3.5 text-muted-foreground/50"
        :stroke-width="1.5"
      />
    </template>
  </nav>
</template>
