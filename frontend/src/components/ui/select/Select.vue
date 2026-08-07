<script setup lang="ts">
import { computed } from 'vue'
import { SelectRoot, SelectTrigger, SelectValue, SelectPortal, SelectContent, SelectViewport, SelectItem, SelectItemText, SelectItemIndicator, SelectScrollUpButton, SelectScrollDownButton, type SelectRootProps } from 'reka-ui'
import { ChevronDown, Check, ChevronUp } from 'lucide-vue-next'
import { cn } from '@/lib/utils'
import type { ClassValue } from 'clsx'

const EMPTY_VALUE = '__SELECT_EMPTY__'

interface Option {
  value: string
  label?: string
}

const props = withDefaults(
  defineProps<SelectRootProps & {
    options: Option[]
    placeholder?: string
    glass?: boolean
    class?: ClassValue
    modelValue?: string
  }>(),
  {
    glass: true,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

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
          'flex h-10 w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm transition-all duration-200',
          'border-input bg-background/50 text-foreground shadow-sm',
          'placeholder:text-muted-foreground',
          'hover:border-primary/50 hover:bg-background/80',
          'focus:outline-none focus:ring-2 focus:ring-ring/60 focus:border-primary/50 focus:shadow-md focus:shadow-primary/10',
          'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-input',
          'data-[placeholder]:text-muted-foreground',
          'data-[state=open]:border-primary/50 data-[state=open]:ring-2 data-[state=open]:ring-ring/60 data-[state=open]:shadow-md data-[state=open]:shadow-primary/10',
          props.class,
        )
      "
    >
      <SelectValue :placeholder="props.placeholder" />
      <ChevronDown
        class="size-4 shrink-0 text-muted-foreground transition-transform duration-200 data-[state=open]:rotate-180"
        :stroke-width="1.75"
      />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent
        :side-offset="6"
        position="popper"
        :class="
          cn(
            'relative z-[1400] max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border text-popover-foreground shadow-xl',
            props.glass
              ? 'bg-glass backdrop-blur-2xl saturate-150 border-glass-border shadow-lg shadow-black/10 dark:shadow-black/40'
              : 'bg-popover border-border shadow-lg',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2',
            'duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]',
          )
        "
      >
        <SelectScrollUpButton class="flex items-center justify-center h-6 cursor-default text-muted-foreground">
          <ChevronUp class="size-4" />
        </SelectScrollUpButton>
        <SelectViewport class="p-1.5">
          <SelectItem
            v-for="opt in internalOptions"
            :key="opt.value"
            :value="opt.value"
            :class="
              cn(
                'relative flex w-full cursor-pointer select-none items-center rounded-lg py-2 pl-8 pr-3 text-sm outline-none transition-all duration-150',
                'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
                'hover:bg-accent/80 hover:text-accent-foreground',
                'focus:bg-accent/80 focus:text-accent-foreground',
                'data-[highlighted]:bg-accent/80 data-[highlighted]:text-accent-foreground',
                'data-[state=checked]:bg-primary/10 data-[state=checked]:text-primary data-[state=checked]:font-medium',
              )
            "
          >
            <span class="absolute left-2 flex size-4 items-center justify-center">
              <SelectItemIndicator class="data-[state=checked]:animate-in data-[state=unchecked]:animate-out data-[state=unchecked]:fade-out-0 data-[state=checked]:fade-in-0 duration-150">
                <Check class="size-4 text-primary" :stroke-width="2.5" />
              </SelectItemIndicator>
            </span>
            <SelectItemText>{{ opt.label ?? opt.value }}</SelectItemText>
          </SelectItem>
        </SelectViewport>
        <SelectScrollDownButton class="flex items-center justify-center h-6 cursor-default text-muted-foreground">
          <ChevronDown class="size-4" />
        </SelectScrollDownButton>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
