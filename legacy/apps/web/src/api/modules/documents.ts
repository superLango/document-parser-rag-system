import { http } from '@/api/client'
import type { DocumentItem, DocumentTaskItem, Paginated } from '@/api/types'

interface RawDocument {
  id: string
  kb_id: string
  file_name: string
  sha256: string
  status: string
  job_id: string | null
  review_status: string
  review_version: number
  standard_no: string | null
  title: string | null
  created_at: string
  file_size?: number
  page_count?: number
  latest_schema_name?: string | null
  history_count?: number
  task?: RawTask | null
}

interface RawTask {
  job_id: string
  document_id: string
  kb_id: string | null
  status: string
  stage: string
  progress: number
  error: string | null
  summary?: Record<string, unknown>
  created_at: string | null
}

interface RawPage {
  page_no: number
  image_url?: string | null
  layout_url?: string | null
  markdown?: string | null
}

interface RawPreview {
  document_id?: string
  pages?: RawPage[]
  markdown?: string | null
}

function mapStatus(raw: RawDocument): string {
  if (raw.status === 'running') return 'parsing'
  if (raw.status === 'succeeded' || raw.status === 'review') return 'completed'
  if (raw.status === 'failed') return 'failed'
  return 'queued'
}

function mapStage(task: RawTask | null | undefined): string {
  if (!task) return 'queued'
  if (task.status === 'succeeded' || task.status === 'review') return 'completed'
  if (task.status === 'failed') return 'failed'
  if (task.progress >= 90) return 'rebuild'
  if (task.progress >= 55) return 'ocr'
  if (task.progress >= 25) return 'layout'
  if (task.status === 'running') return 'rendering'
  return 'queued'
}

export function toDocumentItem(raw: RawDocument): DocumentItem {
  return {
    id: raw.id,
    kb_id: raw.kb_id,
    filename: raw.file_name,
    file_type: 'pdf',
    file_size: raw.file_size ?? 0,
    sha256: raw.sha256,
    status: mapStatus(raw),
    process_status: mapStage(raw.task),
    progress_page: null,
    progress_total: null,
    page_count: raw.page_count ?? Number(raw.task?.summary?.pages ?? 0),
    markdown_path: null,
    layout_path: null,
    pages_cleaned_at: null,
    error: raw.task?.error ? { message: raw.task.error } : null,
    created_at: raw.created_at,
    updated_at: null,
  }
}

export function toTaskItem(raw: RawTask): DocumentTaskItem {
  return {
    id: raw.job_id,
    kb_id: raw.kb_id || '',
    document_id: raw.document_id,
    task_id: raw.job_id,
    type: 'standard_extraction',
    filename: null,
    status: raw.status,
    attempts: 1,
    heartbeat_at: null,
    checkpoint: raw.summary || {},
    error: raw.error ? { message: raw.error } : null,
    created_at: raw.created_at || '',
    updated_at: null,
  }
}

export interface CrossStandardTask {
  task_id: string
  inspection_item: string | null
  missing_fields: string[]
  requirement_standard: string
  requirement_edition: string | null
  clause_id: string | null
  page_no: number | null
  status: string
  resolution_basis: string | null
  resolved_source_file: string | null
  gap: string | null
  quote?: string | null
  expansion?: {
    clause_id?: string | null
    table_id?: string | null
    page_no?: number | null
    extracted?: Array<{ field?: string; requirement?: string; value?: string; unit?: string }>
    confidence?: number
  } | null
  merge?: { requirement?: string | null; applied?: boolean } | null
  provenance?: Array<Record<string, unknown>>
}

export interface CrossStandardPayload {
  tasks: CrossStandardTask[]
  summary: Record<string, number>
}

export const documentsApi = {
  async list(
    moduleKey: string,
    params?: { page?: number; page_size?: number; keyword?: string; status?: string },
  ): Promise<Paginated<DocumentItem>> {
    const page = params?.page ?? 1
    const pageSize = params?.page_size ?? 20
    const rows = await http.get<RawDocument[]>('/documents', {
      params: {
        module: moduleKey,
        q: params?.keyword || undefined,
        status: params?.status || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      },
    })
    return {
      items: rows.map(toDocumentItem),
      total: (page - 1) * pageSize + rows.length,
      page,
      page_size: pageSize,
    }
  },
  async get(_kbId: string, docId: string): Promise<DocumentItem> {
    return toDocumentItem(await http.get<RawDocument>(`/documents/${docId}`))
  },
  async upload(moduleKey: string, file: File): Promise<DocumentItem> {
    const form = new FormData()
    form.append('module', moduleKey)
    form.append('file', file)
    return toDocumentItem(
      await http.post<RawDocument>('/documents', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    )
  },
  startParse(_kbId: string, docId: string): Promise<unknown> {
    return http.post(`/documents/${docId}/parse`)
  },
  reparse(_kbId: string, docId: string): Promise<unknown> {
    return http.post(`/documents/${docId}/parse?force=true`)
  },
  remove(_kbId: string, docId: string): Promise<unknown> {
    return http.delete(`/documents/${docId}`)
  },
  async tasks(
    moduleKey: string,
    params?: { page?: number; page_size?: number; status?: string },
  ): Promise<Paginated<DocumentTaskItem>> {
    const page = params?.page ?? 1
    const pageSize = params?.page_size ?? 20
    const rows = await http.get<RawTask[]>('/tasks', {
      params: {
        module: moduleKey,
        status: params?.status || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      },
    })
    return {
      items: rows.map(toTaskItem),
      total: (page - 1) * pageSize + rows.length,
      page,
      page_size: pageSize,
    }
  },
  async preview(docId: string): Promise<RawPreview> {
    return http.get<RawPreview>(`/documents/${docId}/preview`)
  },
  async layout(_kbId: string, docId: string): Promise<RawPreview> {
    return documentsApi.preview(docId)
  },
  async markdown(docId: string): Promise<{ markdown: string }> {
    const preview = await documentsApi.preview(docId)
    return { markdown: preview.markdown || '' }
  },
  original(_kbId: string, docId: string): string {
    return `/v1/documents/${docId}/preview`
  },
  page(_kbId: string, docId: string, pageNo: number): string {
    return `/v1/documents/${docId}/pages/${pageNo}/image`
  },
  crossStandardTasks(docId: string): Promise<CrossStandardPayload> {
    return http.get<CrossStandardPayload>(`/documents/${docId}/cross-standard/tasks`)
  },
  crossStandardIgnore(docId: string, taskId: string): Promise<unknown> {
    return http.post(`/documents/${docId}/cross-standard/tasks/${taskId}/ignore`, {})
  },
  crossStandardConfirm(
    docId: string,
    taskId: string,
    payload: { requirement?: string; field?: string; inspection_item?: string },
  ): Promise<unknown> {
    return http.post(`/documents/${docId}/cross-standard/tasks/${taskId}/confirm`, payload)
  },
  crossStandardExpand(docId: string, taskId: string): Promise<unknown> {
    return http.post(`/documents/${docId}/cross-standard/tasks/${taskId}/expand`, {})
  },
}
