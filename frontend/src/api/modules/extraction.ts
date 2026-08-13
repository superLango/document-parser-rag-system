import { getAccessToken, http } from '@/api/client'

export interface ExtractableDocument {
  id: string
  filename: string
  file_size: number
  page_count: number
  status: string
  extraction_status: string | null
  latest_schema_name: string | null
  history_count: number
  updated_at: string | null
}

export interface ExtractionStatusData {
  task_id: string | null
  task_status: string | null
  status: string | null
  progress: number
  error: { message?: string } | null
}

export interface ExtractionCategory {
  feature: string
  records: Record<string, unknown>[]
  rejected: Record<string, unknown>[]
  missing_fields: string[]
}

export interface ExtractionResultData {
  schema_template_id: string | null
  schema_name: string
  status: string
  progress: number
  categories: ExtractionCategory[]
  summary: Record<string, unknown>
  timing: Record<string, unknown>
  version: number
  error: { message?: string } | null
  updated_at: string | null
}

export interface ExtractionHistoryItem {
  id: string
  schema_template_id: string | null
  schema_name: string
  categories: ExtractionCategory[]
  summary: Record<string, unknown>
  timing: Record<string, unknown>
  version: number
  extracted_at: string
  archived_at: string
}

export interface ExtractionDocDetail {
  id: string
  filename: string
  file_type: string | null
  status: string
}

export const extractionApi = {
  listDocuments(kbId: string): Promise<{ items: ExtractableDocument[] }> {
    return http.get(`/kb/${kbId}/extraction/documents`)
  },
  start(kbId: string, docId: string): Promise<{ task_id: string; status: string }> {
    return http.post(`/kb/${kbId}/extraction/${docId}`, {})
  },
  status(kbId: string, docId: string): Promise<ExtractionStatusData> {
    return http.get(`/kb/${kbId}/extraction/${docId}/status`)
  },
  result(kbId: string, docId: string): Promise<ExtractionResultData | null> {
    return http.get(`/kb/${kbId}/extraction/${docId}/result`)
  },
  history(kbId: string, docId: string): Promise<{ items: ExtractionHistoryItem[] }> {
    return http.get(`/kb/${kbId}/extraction/${docId}/history`)
  },
  getDocument(kbId: string, docId: string): Promise<ExtractionDocDetail> {
    return http.get(`/kb/${kbId}/documents/${docId}`)
  },
  remove(kbId: string, docId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/extraction/${docId}/result`)
  },
  async exportCsv(kbId: string, docId: string): Promise<void> {
    const token = getAccessToken()
    const resp = await fetch(`/api/v1/kb/${kbId}/extraction/export?document_id=${docId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) throw new Error(`导出失败（${resp.status}）`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `extraction_${docId}.csv`
    a.click()
    URL.revokeObjectURL(url)
  },
}
