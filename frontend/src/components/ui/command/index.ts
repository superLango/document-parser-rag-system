/**
 * Command 组件集（简化版命令面板）。
 *
 * 提供搜索输入 + 过滤列表的交互模式，用于下拉命令选择、
 * 全局搜索等场景。基于原生 input + 列表渲染，轻量无额外依赖。
 *
 * 用法：
 *   <Command :items="items" v-model="selected" placeholder="搜索..." />
 *   items: Array<{ value: string; label: string; group?: string; icon?: any }>
 */
import { defineComponent, h, ref, computed, type Component } from 'vue'
import { Search } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

export interface CommandItem {
  value: string
  label: string
  group?: string
  icon?: Component
  description?: string
}

export const Command = defineComponent({
  name: 'Command',
  props: {
    items: { type: Array as () => CommandItem[], default: () => [] },
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: '搜索...' },
    class: { type: String, default: '' },
  },
  emits: ['update:modelValue', 'select'],
  setup(props, { emit }) {
    const query = ref('')
    const activeIndex = ref(0)

    const filtered = computed(() => {
      const q = query.value.trim().toLowerCase()
      if (!q) return props.items
      return props.items.filter((it) =>
        [it.label, it.description ?? '', it.group ?? '']
          .join(' ')
          .toLowerCase()
          .includes(q),
      )
    })

    const grouped = computed(() => {
      const map = new Map<string, CommandItem[]>()
      for (const it of filtered.value) {
        const g = it.group ?? ''
        if (!map.has(g)) map.set(g, [])
        map.get(g)!.push(it)
      }
      return Array.from(map.entries())
    })

    const flat = computed(() => grouped.value.flatMap(([, items]) => items))

    function onKeydown(e: KeyboardEvent) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        activeIndex.value = Math.min(activeIndex.value + 1, flat.value.length - 1)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        activeIndex.value = Math.max(activeIndex.value - 1, 0)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const item = flat.value[activeIndex.value]
        if (item) {
          emit('update:modelValue', item.value)
          emit('select', item)
        }
      }
    }

    return () =>
      h('div', { class: cn('flex flex-col overflow-hidden rounded-md border border-border bg-popover text-popover-foreground', props.class) }, [
        h('div', { class: 'flex items-center gap-2 border-b border-border px-3' }, [
          h(Search, { class: 'size-4 shrink-0 text-muted-foreground', 'stroke-width': 1.5 }),
          h('input', {
            value: query.value,
            onInput: (e: Event) => { query.value = (e.target as HTMLInputElement).value; activeIndex.value = 0 },
            onKeydown,
            placeholder: props.placeholder,
            class: 'h-10 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground',
          }),
        ]),
        h('div', { class: 'max-h-64 overflow-y-auto p-1' },
          flat.value.length === 0
            ? h('div', { class: 'px-3 py-6 text-center text-sm text-muted-foreground' }, '无匹配项')
            : grouped.value.map(([group, items]) =>
                h('div', { key: group, class: 'mb-1' }, [
                  group ? h('div', { class: 'px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground' }, group) : null,
                  ...items.map((it) => {
                    const idx = flat.value.indexOf(it)
                    return h('button', {
                      key: it.value,
                      type: 'button',
                      class: cn(
                        'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors',
                        idx === activeIndex.value ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-muted',
                      ),
                      onClick: () => { emit('update:modelValue', it.value); emit('select', it) },
                    }, [
                      it.icon ? h(it.icon, { class: 'size-4 shrink-0', 'stroke-width': 1.5 }) : null,
                      h('div', { class: 'min-w-0 flex-1' }, [
                        h('div', { class: 'truncate font-medium' }, it.label),
                        it.description ? h('div', { class: 'truncate text-xs text-muted-foreground' }, it.description) : null,
                      ]),
                    ])
                  }),
                ]),
              ),
        ),
      ])
  },
})

export { Command as default }
