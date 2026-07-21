<script setup lang="ts">
import { TabsRoot, TabsList, TabsTrigger, TabsContent, type TabsRootProps } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<TabsRootProps & { class?: string }>(),
  {
    orientation: 'horizontal',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <TabsRoot
    v-bind="props"
    @update:model-value="emit('update:modelValue', $event)"
    :class="cn('flex flex-col gap-3', props.class)"
  >
    <slot />
  </TabsRoot>
</template>
