import { http } from '@/api'
import type { Document, DocumentCreate, Paginated } from '@/api/types'

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
  upload(file: File, meta: DocumentCreate): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', meta.title)
    formData.append('doc_type', meta.doc_type)
    if (meta.standard_number) {
      formData.append('standard_number', meta.standard_number)
    }
    return http.post<Document>('/documents/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 删除文档
  remove(id: string): Promise<void> {
    return http.delete<void>(`/documents/${id}`)
  },
}
