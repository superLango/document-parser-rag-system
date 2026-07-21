<script setup lang="ts">
import type { Component } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  icon?: Component
  title?: string
  description?: string
  class?: string
}>()
</script>

<template>
  <div
    :class="
      cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-12 text-center',
        props.class,
      )
    "
  >
    <div v-if="props.icon" class="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
      <component :is="props.icon" class="size-6" :stroke-width="1.25" />
    </div>
    <div class="space-y-1">
      <p v-if="props.title" class="text-sm font-medium text-foreground">{{ props.title }}</p>
      <p v-if="props.description" class="max-w-sm text-xs text-muted-foreground">
        {{ props.description }}
      </p>
    </div>
    <slot />
  </div>
</template>
