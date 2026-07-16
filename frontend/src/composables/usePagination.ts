/**
 * 分页逻辑组合式函数
 * 复用分页状态管理与数据加载逻辑
 */

import { ref } from 'vue'

export interface PaginationOptions {
  page?: number
  page_size?: number
  page_sizes?: number[]
}

export function usePagination<T>(
  fetchFn: (params: { page: number; page_size: number }) => Promise<{ items: T[]; total: number }>,
  options: PaginationOptions = {},
) {
  const page = ref(options.page ?? 1)
  const pageSize = ref(options.page_size ?? 20)
  const pageSizes = options.page_sizes ?? [10, 20, 50]
  const total = ref(0)
  const items = ref<T[]>([]) as { value: T[] }
  const loading = ref(false)

  async function load(extraParams?: Record<string, unknown>) {
    loading.value = true
    try {
      const res = await fetchFn({ page: page.value, page_size: pageSize.value })
      items.value = res.items
      total.value = res.total
    } catch {
      items.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  function handlePageChange(newPage: number) {
    page.value = newPage
    load()
  }

  function handleSizeChange(newSize: number) {
    pageSize.value = newSize
    page.value = 1
    load()
  }

  function reset() {
    page.value = 1
    load()
  }

  return {
    page,
    pageSize,
    pageSizes,
    total,
    items,
    loading,
    load,
    handlePageChange,
    handleSizeChange,
    reset,
  }
}
