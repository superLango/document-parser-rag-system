<script setup lang="ts">
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: string
}>()
</script>

<template>
  <div
    :class="cn('skeleton-pulse rounded-md bg-muted', props.class)"
    aria-hidden="true"
  />
</template>
