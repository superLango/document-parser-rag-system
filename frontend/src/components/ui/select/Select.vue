<script setup lang="ts">
import { computed } from 'vue'
import { SelectRoot, SelectTrigger, SelectValue, SelectPortal, SelectContent, SelectViewport, SelectItem, SelectItemText, SelectItemIndicator, type SelectRootProps } from 'reka-ui'
import { ChevronDown, Check } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const EMPTY_VALUE = '__SELECT_EMPTY__'

interface Option {
  value: string
  label?: string
}

const props = withDefaults(
  defineProps<SelectRootProps & {
    options: Option[]
    placeholder?: string
    class?: string
    modelValue?: string
  }>(),
  {},
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

// 内部映射：空字符串 <-> EMPTY_VALUE（reka-ui SelectItem 不允许 value=''）
const internalModelValue = computed({
  get: () => (props.modelValue === '' ? EMPTY_VALUE : props.modelValue ?? EMPTY_VALUE),
  set: (v: string) => emit('update:modelValue', v === EMPTY_VALUE ? '' : v),
})

const internalOptions = computed(() =>
  props.options.map((opt) => ({
    ...opt,
    value: opt.value === '' ? EMPTY_VALUE : opt.value,
  })),
)
</script>

<template>
  <SelectRoot
    v-model="internalModelValue"
    :disabled="props.disabled"
    :name="props.name"
    :required="props.required"
    @update:model-value="(v: string) => { internalModelValue = v }"
  >
    <SelectTrigger
      :class="
        cn(
          'flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm',
          'placeholder:text-muted-foreground',
          'focus:outline-none focus:ring-2 focus:ring-ring',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'data-[placeholder]:text-muted-foreground',
          props.class,
        )
      "
    >
      <SelectValue :placeholder="props.placeholder" />
      <ChevronDown class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent
        :side-offset="4"
        :class="
          cn(
            'relative z-[1400] max-h-72 min-w-[8rem] overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 duration-150',
          )
        "
      >
        <SelectViewport class="p-1">
          <SelectItem
            v-for="opt in internalOptions"
            :key="opt.value"
            :value="opt.value"
            :class="
              cn(
                'relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors',
                'focus:bg-muted focus:text-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
              )
            "
          >
            <span class="absolute left-2 flex size-4 items-center justify-center">
              <SelectItemIndicator>
                <Check class="size-4 text-primary" :stroke-width="1.5" />
              </SelectItemIndicator>
            </span>
            <SelectItemText>{{ opt.label ?? opt.value }}</SelectItemText>
          </SelectItem>
        </SelectViewport>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
