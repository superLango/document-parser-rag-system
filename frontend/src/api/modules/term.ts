import { http } from '@/api'
import type { Term, TermCreate, Paginated } from '@/api/types'

/**
 * 术语库接口
 */
export const termApi = {
  // 术语列表
  getList(params?: {
    category?: string
    keyword?: string
    page?: number
    page_size?: number
  }): Promise<Paginated<Term>> {
    return http.get<Paginated<Term>>('/terms', { params })
  },

  // 术语详情
  getDetail(id: number): Promise<Term> {
    return http.get<Term>(`/terms/${id}`)
  },

  // 创建术语
  create(data: TermCreate): Promise<Term> {
    return http.post<Term>('/terms', data)
  },

  // 更新术语
  update(id: number, data: Partial<TermCreate>): Promise<Term> {
    return http.put<Term>(`/terms/${id}`, data)
  },

  // 删除术语
  remove(id: number): Promise<void> {
    return http.delete<void>(`/terms/${id}`)
  },

  // 批量导入
  batchImport(data: TermCreate[]): Promise<{ imported: number }> {
    return http.post<{ imported: number }>('/terms/batch', data)
  },

  // 分类列表
  getCategories(): Promise<string[]> {
    return http.get<string[]>('/terms/categories')
  },
}
