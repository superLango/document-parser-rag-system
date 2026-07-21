import { http } from '@/api'
import type { Document, Paginated } from '@/api/types'

/**
 * 文档管理接口
 */
export const documentApi = {
  // 文档列表（分页）
  getList(params?: {
    page?: number
    page_size?: number
    doc_type?: string
    status?: string
    keyword?: string
  }): Promise<Paginated<Document>> {
    return http.get<Paginated<Document>>('/documents/', { params })
  },

  // 文档详情
  getDetail(id: string): Promise<Document> {
    return http.get<Document>(`/documents/${id}`)
  },

  // 上传文档（multipart/form-data）
  // 后端仅接收 file 字段，filename/file_size/file_type 由后端自动从文件中提取
  upload(file: File): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    return http.post<Document>('/documents/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 删除文档
  remove(id: string): Promise<void> {
    return http.delete<void>(`/documents/${id}`)
  },
}
