<script setup lang="ts">
import { TooltipArrow, TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger, type TooltipContentProps } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    side?: TooltipContentProps['side']
    align?: TooltipContentProps['align']
    delayMs?: number
    showArrow?: boolean
    class?: string
  }>(),
  {
    side: 'top',
    align: 'center',
    delayMs: 300,
    showArrow: false,
  },
)
</script>

<template>
  <TooltipRoot :delay-duration="props.delayMs">
    <TooltipTrigger as-child>
      <slot name="trigger" />
    </TooltipTrigger>
    <TooltipPortal>
      <TooltipContent
        :side="props.side"
        :align="props.align"
        :side-offset="6"
        :class="
          cn(
            'z-[1600] overflow-hidden rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background shadow-md',
            'animate-in fade-in-0 zoom-in-95 duration-150',
            props.class,
          )
        "
      >
        <slot />
        <TooltipArrow v-if="showArrow" class="fill-foreground" :width="8" :height="4" />
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
