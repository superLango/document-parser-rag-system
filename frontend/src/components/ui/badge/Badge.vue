<script setup lang="ts">
import { computed } from 'vue'
import { badgeVariants, type BadgeVariants } from '.'
import { cn } from '@/lib/utils'
import type { ClassValue } from 'clsx'

const props = defineProps<{
  variant?: BadgeVariants['variant']
  size?: BadgeVariants['size']
  class?: ClassValue
}>()

const classes = computed(() => cn(badgeVariants({ variant: props.variant, size: props.size }), props.class))
</script>

<template>
  <span :class="classes">
    <slot />
  </span>
</template>
