<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg'
    class?: string
  }>(),
  { size: 'md' },
)

const sizeClass = {
  sm: 'size-3.5',
  md: 'size-4',
  lg: 'size-5',
}
</script>

<template>
  <Loader2
    :class="cn('animate-spin text-muted-foreground', sizeClass[props.size], props.class)"
    :stroke-width="1.5"
  />
</template>
