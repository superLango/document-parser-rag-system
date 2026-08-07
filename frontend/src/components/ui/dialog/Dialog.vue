<script setup lang="ts">
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from 'reka-ui'
import { X } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    open?: boolean
    defaultOpen?: boolean
    title?: string
    description?: string
    closable?: boolean
    glass?: boolean
    class?: string
    contentClass?: string
  }>(),
  {
    closable: true,
    glass: true,
  },
)

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()
</script>

<template>
  <DialogRoot
    :open="props.open"
    :default-open="props.defaultOpen"
    @update:open="emit('update:open', $event)"
  >
    <DialogTrigger v-if="$slots.trigger" as-child>
      <slot name="trigger" />
    </DialogTrigger>
    <DialogPortal>
      <DialogOverlay
        class="fixed inset-0 z-[1299] bg-foreground/20 backdrop-blur-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 duration-300"
      />
      <DialogContent
        :class="
          cn(
            'fixed left-1/2 top-1/2 z-[1300] w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4',
            'rounded-xl border p-6 shadow-2xl',
            props.glass
              ? 'bg-glass backdrop-blur-2xl saturate-150 border-glass-border shadow-lg shadow-black/10 dark:shadow-black/30'
              : 'bg-card border-border',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]',
            'duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]',
            props.contentClass,
          )
        "
      >
        <div v-if="title || description" class="space-y-2">
          <DialogTitle v-if="title" class="text-xl font-semibold leading-none tracking-tight">
            {{ title }}
          </DialogTitle>
          <DialogDescription v-if="description" class="text-sm text-muted-foreground leading-relaxed">
            {{ description }}
          </DialogDescription>
        </div>
        <slot />
        <DialogClose
          v-if="closable"
          class="absolute right-4 top-4 rounded-lg p-1.5 text-muted-foreground/70 transition-all duration-200 hover:bg-muted/80 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 hover:scale-105 active:scale-95"
        >
          <X class="size-4" :stroke-width="1.75" />
          <span class="sr-only">关闭</span>
        </DialogClose>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
[data-state='open'] {
  animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1);
}
[data-state='closed'] {
  animation-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
}
</style>
