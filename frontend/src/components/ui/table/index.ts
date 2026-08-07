/**
 * Table 组件集（shadcn-vue 风格）。
 *
 * 子组件（Table/TableHeader/TableBody/TableRow/TableHead/TableCell/
 * TableCaption/TableFooter）均为原生 table 元素的纯样式包装，
 * 故用 defineComponent + h() 统一定义，避免 8 个 Vue 单文件碎片化。
 *
 * 用法：
 *   import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
 */
import { defineComponent, h } from 'vue'
import { cn } from '@/lib/utils'

const wrap = (tag: string, baseClass: string) =>
  defineComponent({
    name: tag.charAt(0).toUpperCase() + tag.slice(1),
    props: { class: { type: String, default: '' } },
    setup(props, { slots }) {
      return () =>
        h(
          tag,
          { class: cn(baseClass, props.class) },
          { default: () => slots.default?.() },
        )
    },
  })

export const Table = wrap(
  'div',
  'w-full caption-bottom overflow-auto rounded-xl border border-border bg-card/50 shadow-sm',
)
export const TableHeader = wrap(
  'thead',
  '[&_tr]:border-b [&_tr]:border-border/80 [&_tr]:bg-muted/30',
)
export const TableBody = wrap(
  'tbody',
  '[&_tr:last-child]:border-0 [&_tr:nth-child(even)]:bg-muted/20',
)
export const TableFooter = wrap(
  'tfoot',
  'border-t border-border/80 bg-muted/50 font-medium [&>tr]:last:border-b-0',
)
export const TableRow = wrap(
  'tr',
  'border-b border-border/60 transition-all duration-150 hover:bg-accent/60 data-[state=selected]:bg-primary/10 hover:shadow-sm',
)
export const TableHead = wrap(
  'th',
  'h-11 px-4 text-left align-middle text-xs font-semibold uppercase tracking-wider text-muted-foreground [&:has([role=checkbox])]:pr-0',
)
export const TableCell = wrap(
  'td',
  'p-4 align-middle text-sm [&:has([role=checkbox])]:pr-0 transition-colors duration-150',
)
export const TableCaption = wrap(
  'caption',
  'mt-4 text-sm text-muted-foreground',
)

export { Table as default }
