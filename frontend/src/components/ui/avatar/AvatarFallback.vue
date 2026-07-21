<script setup lang="ts">
import { AvatarFallback } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: string
  delayMs?: number
}>()
</script>

<template>
  <AvatarFallback
    :delay-ms="props.delayMs ?? 0"
    :class="cn('flex size-full items-center justify-center text-muted-foreground', props.class)"
  >
    <slot />
  </AvatarFallback>
</template>
