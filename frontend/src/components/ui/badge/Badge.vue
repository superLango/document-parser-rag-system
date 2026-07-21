<script setup lang="ts">
import { computed } from 'vue'
import { badgeVariants, type BadgeVariants } from '.'
import { cn } from '@/lib/utils'

const props = defineProps<{
  variant?: BadgeVariants['variant']
  class?: string
}>()

const classes = computed(() => cn(badgeVariants({ variant: props.variant }), props.class))
</script>

<template>
  <span :class="classes">
    <slot />
  </span>
</template>
