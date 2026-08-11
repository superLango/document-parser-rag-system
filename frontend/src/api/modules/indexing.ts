import { http } from '@/api/client'
import type { Paginated, SearchFilters, SearchResponse } from '@/api/types'
import type { DocumentTaskItem } from '@/api/types'

export const indexingApi = {
  search(
    kbId: string,
    query: string,
    topK: number,
    filters?: SearchFilters,
  ): Promise<SearchResponse> {
    return http.post<SearchResponse>(`/kb/${kbId}/search`, {
      query,
      top_k: topK,
      filters: filters ?? null,
    })
  },
  indexDocument(kbId: string, documentId: string): Promise<{ document: unknown; task: DocumentTaskItem }> {
    return http.post(`/kb/${kbId}/documents/${documentId}/index`)
  },
  tasks(kbId: string, params?: { page?: number; page_size?: number }): Promise<Paginated<DocumentTaskItem>> {
    return http.get<Paginated<DocumentTaskItem>>(`/kb/${kbId}/index/tasks`, { params })
  },
}
