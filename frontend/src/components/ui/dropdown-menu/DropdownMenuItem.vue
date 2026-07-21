<script setup lang="ts">
import { DropdownMenuItem, type DropdownMenuItemProps } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<
  DropdownMenuItemProps & {
    variant?: 'default' | 'destructive'
    class?: string
  }
>()
</script>

<template>
  <DropdownMenuItem
    v-bind="props"
    :class="
      cn(
        'relative flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors',
        'focus:bg-muted focus:text-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        props.variant === 'destructive' && 'text-destructive focus:bg-destructive/10 focus:text-destructive',
        props.class,
      )
    "
  >
    <slot />
  </DropdownMenuItem>
</template>
