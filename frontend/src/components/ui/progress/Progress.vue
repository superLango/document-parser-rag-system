<script setup lang="ts">
import { ProgressIndicator, ProgressRoot } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    value?: number
    max?: number
    class?: string
    indicatorClass?: string
  }>(),
  {
    value: 0,
    max: 100,
  },
)

const percent = Math.min(100, Math.max(0, (props.value / props.max) * 100))
</script>

<template>
  <ProgressRoot
    :value="props.value"
    :max="props.max"
    :class="
      cn(
        'relative h-1.5 w-full overflow-hidden rounded-full bg-muted',
        props.class,
      )
    "
  >
    <ProgressIndicator
      :class="
        cn(
          'h-full w-full flex-1 bg-primary transition-all duration-300 ease-out',
          props.indicatorClass,
        )
      "
      :style="{ transform: `translateX(-${100 - percent}%)` }"
    />
  </ProgressRoot>
</template>
