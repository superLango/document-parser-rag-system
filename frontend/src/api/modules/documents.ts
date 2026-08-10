import axios from 'axios'
import { getAccessToken } from '@/api/client'
import { http, ApiError } from '@/api/client'
import type { DocumentItem, DocumentTaskItem, Paginated } from '@/api/types'

export const documentsApi = {
  list(kbId: string, params?: { page?: number; page_size?: number; keyword?: string }): Promise<Paginated<DocumentItem>> {
    return http.get<Paginated<DocumentItem>>(`/kb/${kbId}/documents`, { params })
  },
  async upload(kbId: string, file: File): Promise<{ document: DocumentItem; task: DocumentTaskItem }> {
    const form = new FormData()
    form.append('file', file, file.name)
    const token = localStorage.getItem('access_token')
    try {
      const resp = await axios.post(`/api/v1/kb/${kbId}/documents`, form, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      return resp.data.data
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const body = err.response?.data
        throw new ApiError(
          body?.code ?? 10001,
          body?.message ?? '上传失败',
          body?.trace_id ?? '',
        )
      }
      throw err
    }
  },
  get(kbId: string, documentId: string): Promise<DocumentItem> {
    return http.get<DocumentItem>(`/kb/${kbId}/documents/${documentId}`)
  },
  async markdown(kbId: string, documentId: string): Promise<string> {
    const token = getAccessToken()
    const resp = await axios.get(`/api/v1/kb/${kbId}/documents/${documentId}/markdown`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 30000,
    })
    return String(resp.data)
  },
  layout(kbId: string, documentId: string): Promise<Record<string, unknown>> {
    return http.get<Record<string, unknown>>(`/kb/${kbId}/documents/${documentId}/layout`)
  },
  reparse(kbId: string, documentId: string): Promise<{ document: DocumentItem; task: DocumentTaskItem }> {
    return http.post<{ document: DocumentItem; task: DocumentTaskItem }>(`/kb/${kbId}/documents/${documentId}/reparse`)
  },
  remove(kbId: string, documentId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/documents/${documentId}`)
  },
  tasks(kbId: string, params?: { page?: number; page_size?: number }): Promise<Paginated<DocumentTaskItem>> {
    return http.get<Paginated<DocumentTaskItem>>(`/kb/${kbId}/documents/tasks`, { params })
  },
}
