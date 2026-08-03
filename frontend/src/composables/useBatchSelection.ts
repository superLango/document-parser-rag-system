/**
 * 批量选择 composable
 *
 * 为列表页提供统一的批量选择状态管理：选中集合、全选/反选、跨页保持、清空。
 * 适用于 Documents/Tasks 等需要批量操作的列表场景。
 *
 * 用法：
 *   const sel = useBatchSelection<Task>({ idKey: 'id' })
 *   sel.toggle(task.id)
 *   sel.isAllSelected(items.value.map(i => i.id))
 */
import { computed, ref } from 'vue'

export interface UseBatchSelectionOptions<T> {
  /** 主键字段名，默认 'id' */
  idKey?: keyof T & string
}

export function useBatchSelection<T extends Record<string, unknown>>(
  options: UseBatchSelectionOptions<T> = {},
) {
  const idKey = options.idKey ?? 'id'
  /** 已选中的 id 集合（跨页保持） */
  const selectedIds = ref<Set<string>>(new Set())

  /** 已选数量 */
  const selectedCount = computed(() => selectedIds.value.size)

  /** 是否已选某项 */
  function isSelected(id: string): boolean {
    return selectedIds.value.has(id)
  }

  /** 切换某项选中状态 */
  function toggle(id: string): void {
    const next = new Set(selectedIds.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selectedIds.value = next
  }

  /** 直接设置某项是否选中 */
  function setSelected(id: string, checked: boolean): void {
    const next = new Set(selectedIds.value)
    if (checked) next.add(id)
    else next.delete(id)
    selectedIds.value = next
  }

  /** 全选/取消全选当前可见列表 */
  function selectAll(visibleIds: string[], checked: boolean): void {
    const next = new Set(selectedIds.value)
    if (checked) {
      visibleIds.forEach((id) => next.add(id))
    } else {
      visibleIds.forEach((id) => next.delete(id))
    }
    selectedIds.value = next
  }

  /** 当前页是否全选（当前可见 id 全部在选中集合中且非空） */
  function isAllSelected(visibleIds: string[]): boolean {
    if (visibleIds.length === 0) return false
    return visibleIds.every((id) => selectedIds.value.has(id))
  }

  /** 当前页是否半选（部分选中） */
  function isIndeterminate(visibleIds: string[]): boolean {
    if (visibleIds.length === 0) return false
    const selectedInPage = visibleIds.filter((id) => selectedIds.value.has(id)).length
    return selectedInPage > 0 && selectedInPage < visibleIds.length
  }

  /** 清空选择 */
  function clear(): void {
    selectedIds.value = new Set()
  }

  /** 获取选中 id 列表 */
  function getSelectedIds(): string[] {
    return Array.from(selectedIds.value)
  }

  return {
    selectedIds,
    selectedCount,
    isSelected,
    toggle,
    setSelected,
    selectAll,
    isAllSelected,
    isIndeterminate,
    clear,
    getSelectedIds,
  }
}
