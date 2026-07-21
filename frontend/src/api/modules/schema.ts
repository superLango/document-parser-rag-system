import { http } from '@/api'
import type { Schema, SchemaCreate, MergedSchema, Paginated } from '@/api/types'

/**
 * 抽取 Schema 接口 - 支持父子层级结构
 *
 * - 父分类：parent_id 为 null，作为 Schema 分组容器
 * - 子 Schema：parent_id 指向父分类，包含具体字段定义
 * - 合并 Schema：将父分类下所有启用的子 Schema 字段整合，供 LangExtract 抽取使用
 */
export const schemaApi = {
  // 查询所有父分类（含子 Schema 数量统计）
  listCategories(): Promise<Schema[]> {
    return http.get<Schema[]>('/schemas/categories')
  },

  // 查询父分类下的所有子 Schema
  listChildren(
    parentId: string,
    options?: { only_active?: boolean },
  ): Promise<Schema[]> {
    return http.get<Schema[]>(`/schemas/${parentId}/children`, {
      params: options,
    })
  },

  // 合并父分类下所有启用的子 Schema 为整体 Schema（供 LangExtract 抽取使用）
  getMergedSchema(parentId: string): Promise<MergedSchema> {
    return http.get<MergedSchema>(`/schemas/${parentId}/merged`)
  },

  // Schema 列表（兼容旧接口）
  getList(params?: {
    parent_id?: string
    only_parent?: boolean
    page?: number
    page_size?: number
  }): Promise<Paginated<Schema>> {
    return http.get<Paginated<Schema>>('/schemas/', { params })
  },

  // Schema 详情
  getDetail(id: string): Promise<Schema> {
    return http.get<Schema>(`/schemas/${id}`)
  },

  // 创建 Schema（parent_id 为 null 时创建父分类）
  create(data: SchemaCreate): Promise<Schema> {
    return http.post<Schema>('/schemas/', data)
  },

  // 更新 Schema
  update(id: string, data: Partial<SchemaCreate>): Promise<Schema> {
    return http.put<Schema>(`/schemas/${id}`, data)
  },

  // 删除 Schema
  remove(id: string): Promise<void> {
    return http.delete<void>(`/schemas/${id}`)
  },

  // 启用/停用 Schema（直接修改 is_active 字段，确保状态一致）
  toggleActive(id: string, active: boolean): Promise<Schema> {
    return http.patch<Schema>(`/schemas/${id}/active`, { is_active: active })
  },
}
