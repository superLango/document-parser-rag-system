<script setup lang="ts">
import { PopoverPortal, PopoverContent, type PopoverContentProps } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    align?: PopoverContentProps['align']
    side?: PopoverContentProps['side']
    sideOffset?: number
    class?: string
  }>(),
  {
    align: 'center',
    side: 'bottom',
    sideOffset: 4,
    class: '',
  },
)
</script>

<template>
  <PopoverPortal>
    <PopoverContent
      :align="props.align"
      :side="props.side"
      :side-offset="props.sideOffset"
      :class="
        cn(
          'z-[1400] w-72 rounded-md border border-border bg-popover p-4 text-popover-foreground shadow-md outline-none',
          'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 duration-150',
          props.class,
        )
      "
    >
      <slot />
    </PopoverContent>
  </PopoverPortal>
</template>
