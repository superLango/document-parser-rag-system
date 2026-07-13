import { http } from '@/api'
import type { Schema, SchemaCreate, Paginated } from '@/api/types'

/**
 * 抽取 Schema 接口
 */
export const schemaApi = {
  // Schema 列表
  getList(params?: {
    doc_type?: string
    is_active?: boolean
    page?: number
    page_size?: number
  }): Promise<Paginated<Schema>> {
    return http.get<Paginated<Schema>>('/schemas', { params })
  },

  // Schema 详情
  getDetail(id: number): Promise<Schema> {
    return http.get<Schema>(`/schemas/${id}`)
  },

  // 创建 Schema
  create(data: SchemaCreate): Promise<Schema> {
    return http.post<Schema>('/schemas', data)
  },

  // 更新 Schema
  update(id: number, data: Partial<SchemaCreate>): Promise<Schema> {
    return http.put<Schema>(`/schemas/${id}`, data)
  },

  // 删除 Schema
  remove(id: number): Promise<void> {
    return http.delete<void>(`/schemas/${id}`)
  },

  // 启用/停用
  toggleActive(id: number, active: boolean): Promise<Schema> {
    return http.patch<Schema>(`/schemas/${id}/active`, { is_active: active })
  },
}
