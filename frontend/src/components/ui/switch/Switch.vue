<script setup lang="ts">
import { SwitchRoot, SwitchThumb, type SwitchRootProps } from 'reka-ui'
import { cn } from '@/lib/utils'
import type { ClassValue } from 'clsx'

const props = withDefaults(
  defineProps<
    SwitchRootProps & {
      class?: ClassValue
      modelValue?: boolean
    }
  >(),
  {},
)

const emit = defineEmits<{
  'update:checked': [value: boolean]
  'update:modelValue': [value: boolean]
}>()

// reka-ui 的 SwitchRoot 使用 modelValue / update:modelValue 作为受控接口
// （checked 是其内部计算属性，非 prop/事件）。这里同时触发两个事件，
// 以兼容 v-model（update:modelValue）和历史 update:checked 用法。
function onChange(val: boolean) {
  emit('update:modelValue', val)
  emit('update:checked', val)
}
</script>

<template>
  <SwitchRoot
    :model-value="modelValue ?? false"
    :disabled="disabled"
    :name="name"
    :required="required"
    :value="value"
    @update:model-value="onChange($event as boolean)"
    :class="
      cn(
        'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
        props.class,
      )
    "
  >
    <SwitchThumb
      class="pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0"
    />
  </SwitchRoot>
</template>
