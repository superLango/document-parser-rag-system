<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    page: number
    pageSize: number
    total: number
    class?: string
  }>(),
  {},
)

const emit = defineEmits<{
  'update:page': [page: number]
  'change': [page: number, pageSize: number]
}>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const pageList = computed(() => {
  const total = totalPages.value
  const current = props.page
  const pages: (number | '...')[] = []
  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
    return pages
  }
  pages.push(1)
  if (current > 3) pages.push('...')
  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  for (let i = start; i <= end; i++) pages.push(i)
  if (current < total - 2) pages.push('...')
  pages.push(total)
  return pages
})

function go(page: number) {
  if (page < 1 || page > totalPages.value || page === props.page) return
  emit('update:page', page)
  emit('change', page, props.pageSize)
}
</script>

<template>
  <div :class="cn('flex items-center gap-1 text-sm', props.class)">
    <span class="mr-2 text-xs text-muted-foreground tabular-nums">
      共 <span class="font-medium text-foreground">{{ total }}</span> 条
    </span>

    <button
      type="button"
      :disabled="props.page === 1"
      class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      aria-label="首页"
      @click="go(1)"
    >
      <ChevronsLeft class="size-4" :stroke-width="1.5" />
    </button>
    <button
      type="button"
      :disabled="props.page === 1"
      class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      aria-label="上一页"
      @click="go(props.page - 1)"
    >
      <ChevronLeft class="size-4" :stroke-width="1.5" />
    </button>

    <template v-for="(p, i) in pageList" :key="`${p}-${i}`">
      <span v-if="p === '...'" class="inline-flex size-8 items-center justify-center text-xs text-muted-foreground">…</span>
      <button
        v-else
        type="button"
        :class="
          cn(
            'inline-flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-xs tabular-nums transition-colors',
            p === props.page
              ? 'bg-primary text-primary-foreground font-medium'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground',
          )
        "
        @click="go(p as number)"
      >
        {{ p }}
      </button>
    </template>

    <button
      type="button"
      :disabled="props.page >= totalPages"
      class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      aria-label="下一页"
      @click="go(props.page + 1)"
    >
      <ChevronRight class="size-4" :stroke-width="1.5" />
    </button>
    <button
      type="button"
      :disabled="props.page >= totalPages"
      class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      aria-label="末页"
      @click="go(totalPages)"
    >
      <ChevronsRight class="size-4" :stroke-width="1.5" />
    </button>
  </div>
</template>
