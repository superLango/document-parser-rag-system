<script setup lang="ts">
import { CheckboxRoot, CheckboxIndicator, type CheckboxRootProps } from 'reka-ui'
import { Check, Minus } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<CheckboxRootProps & { class?: string; indeterminate?: boolean }>(),
  {},
)

const emit = defineEmits<{
  'update:checked': [value: boolean | 'indeterminate']
}>()
</script>

<template>
  <CheckboxRoot
    v-bind="props"
    @update:checked="emit('update:checked', $event)"
    :class="
      cn(
        'peer size-4 shrink-0 rounded-[4px] border border-primary shadow-sm',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
        'data-[state=indeterminate]:bg-primary data-[state=indeterminate]:text-primary-foreground',
        props.class,
      )
    "
  >
    <CheckboxIndicator class="flex items-center justify-center text-current">
      <Minus v-if="props.indeterminate" class="size-3.5" :stroke-width="3" />
      <Check v-else class="size-3.5" :stroke-width="3" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>
