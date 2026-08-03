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
  'w-full caption-bottom overflow-auto',
)
export const TableHeader = wrap('thead', '[&_tr]:border-b')
export const TableBody = wrap('tbody', '[&_tr:last-child]:border-0')
export const TableFooter = wrap('tfoot', 'border-t bg-muted/50 font-medium [&>tr]:last:border-b-0')
export const TableRow = wrap(
  'tr',
  'border-b border-border transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted',
)
export const TableHead = wrap(
  'th',
  'h-10 px-3 text-left align-middle text-xs font-medium uppercase tracking-wide text-muted-foreground [&:has([role=checkbox])]:pr-0',
)
export const TableCell = wrap(
  'td',
  'p-3 align-middle text-sm [&:has([role=checkbox])]:pr-0',
)
export const TableCaption = wrap(
  'caption',
  'mt-4 text-sm text-muted-foreground',
)

export { Table as default }
