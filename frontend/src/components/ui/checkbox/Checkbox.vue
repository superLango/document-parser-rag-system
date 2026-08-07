<script setup lang="ts">
import { CheckboxRoot, CheckboxIndicator, type CheckboxRootProps } from 'reka-ui'
import { Check, Minus } from 'lucide-vue-next'
import { computed } from 'vue'
import { cn } from '@/lib/utils'

interface CheckboxProps extends Omit<CheckboxRootProps, 'checked'> {
  class?: string
  indeterminate?: boolean
  modelValue?: boolean | 'indeterminate'
}

const props = withDefaults(defineProps<CheckboxProps>(), {
  modelValue: false,
  indeterminate: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:checked': [value: boolean | 'indeterminate']
}>()

const checked = computed({
  get: () => props.indeterminate ? 'indeterminate' as const : props.modelValue,
  set: (val: boolean | 'indeterminate') => {
    emit('update:modelValue', val === true)
    emit('update:checked', val)
  },
})
</script>

<template>
  <CheckboxRoot
    v-model:checked="checked"
    :class="
      cn(
        'peer size-4 shrink-0 rounded-[4px] border border-primary shadow-sm cursor-pointer',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
        'data-[state=indeterminate]:bg-primary data-[state=indeterminate]:text-primary-foreground',
        props.class,
      )
    "
  >
    <CheckboxIndicator class="flex items-center justify-center text-current">
      <Minus v-if="indeterminate" class="size-3.5" :stroke-width="3" />
      <Check v-else class="size-3.5" :stroke-width="3" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>
