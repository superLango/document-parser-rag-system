<script setup lang="ts">
import { Separator } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    orientation?: 'horizontal' | 'vertical'
    decorative?: boolean
    class?: string
  }>(),
  {
    orientation: 'horizontal',
    decorative: true,
  },
)
</script>

<template>
  <Separator
    :orientation="props.orientation"
    :decorative="props.decorative"
    :class="
      cn(
        'shrink-0 bg-border',
        props.orientation === 'vertical' ? 'w-px h-full' : 'h-px w-full',
        props.class,
      )
    "
  />
</template>
