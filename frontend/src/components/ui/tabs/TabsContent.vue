<script setup lang="ts">
import { TabsContent } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{ value: string; class?: string }>()
</script>

<template>
  <TabsContent
    :value="props.value"
    :class="
      cn(
        'mt-4 focus-visible:outline-none',
        'data-[state=inactive]:animate-out data-[state=active]:animate-in',
        'data-[state=inactive]:fade-out-0 data-[state=active]:fade-in-0',
        'data-[state=inactive]:slide-out-to-top-2 data-[state=active]:slide-in-from-top-2',
        'duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]',
        props.class,
      )
    "
  >
    <slot />
  </TabsContent>
</template>
