<script setup lang="ts">
import type { Component } from 'vue'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'success' | 'warning' | 'destructive' | 'outline'
    title: string
    description?: string
    icon?: Component
    class?: string
  }>(),
  {
    variant: 'default',
  },
)

const variantClass = {
  default: 'border-l-primary bg-primary/5',
  success: 'border-l-success bg-success/5',
  warning: 'border-l-warning bg-warning/5',
  destructive: 'border-l-destructive bg-destructive/5',
  outline: 'border-l-border bg-muted/30',
}
</script>

<template>
  <div
    :class="
      cn(
        'flex items-start gap-3 rounded-md border border-border border-l-4 p-4',
        variantClass[props.variant],
        props.class,
      )
    "
    role="alert"
  >
    <component
      v-if="props.icon"
      :is="props.icon"
      class="mt-0.5 size-5 shrink-0 text-foreground"
      :stroke-width="1.5"
    />
    <div class="flex-1 space-y-1">
      <p class="text-sm font-medium leading-snug text-foreground">{{ props.title }}</p>
      <p v-if="props.description" class="text-xs leading-relaxed text-muted-foreground">
        {{ props.description }}
      </p>
      <slot />
    </div>
  </div>
</template>
