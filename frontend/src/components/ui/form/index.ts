/**
 * Form 组件集（shadcn-vue 风格简化版）。
 *
 * FormItem/FormLabel/FormControl/FormMessage 为纯样式与语义包装，
 * 不引入复杂的状态注入（如需要可后续对接 reka-ui Form）。
 * 用法：
 *   import { FormItem, FormLabel, FormControl, FormMessage } from '@/components/ui/form'
 */
import { defineComponent, h } from 'vue'
import { cn } from '@/lib/utils'

export const FormItem = defineComponent({
  name: 'FormItem',
  props: { class: { type: String, default: '' } },
  setup(props, { slots }) {
    return () =>
      h('div', { class: cn('space-y-1.5', props.class) }, { default: () => slots.default?.() })
  },
})

export const FormLabel = defineComponent({
  name: 'FormLabel',
  props: { class: { type: String, default: '' }, required: { type: Boolean, default: false } },
  setup(props, { slots }) {
    return () =>
      h(
        'label',
        { class: cn('text-sm font-medium leading-none text-foreground peer-disabled:cursor-not-allowed peer-disabled:opacity-70', props.class) },
        [
          slots.default?.(),
          props.required ? h('span', { class: 'ml-0.5 text-danger' }, '*') : null,
        ],
      )
  },
})

export const FormControl = defineComponent({
  name: 'FormControl',
  props: { class: { type: String, default: '' } },
  setup(props, { slots }) {
    return () =>
      h('div', { class: cn(props.class) }, { default: () => slots.default?.() })
  },
})

export const FormMessage = defineComponent({
  name: 'FormMessage',
  props: { class: { type: String, default: '' }, error: { type: String, default: '' } },
  setup(props) {
    return () =>
      props.error
        ? h('p', { class: cn('text-xs font-medium text-danger', props.class) }, props.error)
        : null
  },
})

export const FormDescription = defineComponent({
  name: 'FormDescription',
  props: { class: { type: String, default: '' } },
  setup(props, { slots }) {
    return () =>
      h('p', { class: cn('text-xs text-muted-foreground', props.class) }, { default: () => slots.default?.() })
  },
})
