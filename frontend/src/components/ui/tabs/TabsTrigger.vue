<script setup lang="ts">
import { TabsTrigger } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{
  value: string
  class?: string
  disabled?: boolean
}>()
</script>

<template>
  <TabsTrigger
    :value="props.value"
    :disabled="props.disabled"
    :class="
      cn(
        'relative z-10 inline-flex items-center justify-center gap-1.5 whitespace-nowrap px-4 py-2 text-sm font-medium transition-all duration-200 rounded-lg',
        'text-muted-foreground hover:text-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
        'disabled:pointer-events-none disabled:opacity-50',
        'data-[state=active]:text-foreground',
        props.class,
      )
    "
  >
    <slot />
  </TabsTrigger>
</template>
