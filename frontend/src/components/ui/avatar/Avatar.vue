<script setup lang="ts">
import { AvatarRoot } from 'reka-ui'
import { avatarVariant, type AvatarVariants } from '.'
import { cn } from '@/lib/utils'

const props = defineProps<{
  size?: AvatarVariants['size']
  shape?: AvatarVariants['shape']
  class?: string
}>()
</script>

<template>
  <AvatarRoot :class="cn(avatarVariant({ size, shape }), props.class)">
    <slot />
  </AvatarRoot>
</template>
