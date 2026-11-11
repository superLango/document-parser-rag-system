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
  fields?: string[]
  records: Record<string, unknown>[]
  rejected: Record<string, unknown>[]
  missing_fields: string[]
  hit_score?: number | null
  hit_count?: number
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

export interface FeedbackTarget {
  record_id?: string
  property?: string
  table_id?: string
  feature?: string
  page_no?: number
  grade?: string
  condition?: string
}

export interface FeedbackItem {
  feedback_id: string
  doc_id: string
  job_id: string
  category: string
  target: FeedbackTarget
  description: string
  expected_value: string | null
  source_quote: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface FeedbackMessage {
  message_id: string
  role: string
  content: string
  created_at: string
}

export interface FeedbackDetail {
  feedback: FeedbackItem
  messages: FeedbackMessage[]
  findings: Array<Record<string, unknown>>
}

export interface FeedbackCreatePayload extends FeedbackTarget {
  category: string
  description?: string
  expected_value?: string
  source_quote?: string
}

export interface FeedbackCreateResult {
  feedback: FeedbackItem
  problems: string[]
  finding_id: string | null
}

export interface FeedbackOutcome {
  feedback_id: string
  status: string
  proposal_id: string | null
  level: string | null
  decision: string | null
  reply: string
  diff: Record<string, unknown> | null
  iterations: number
}

interface RawDocument {
  id: string
  kb_id: string
  file_name: string
  status: string
  job_id: string | null
  review_status: string
  review_version: number
  created_at: string
  file_size?: number
  page_count?: number
  latest_schema_name?: string | null
  history_count?: number
  task?: {
    job_id: string
    status: string
    stage: string
    progress: number
    error: string | null
    summary?: Record<string, unknown>
  } | null
}

function docStatus(raw: RawDocument): string {
  if (raw.status === 'running') return 'parsing'
  if (raw.status === 'succeeded' || raw.status === 'review') return 'completed'
  if (raw.status === 'failed') return 'failed'
  return 'queued'
}

function extractionStatus(raw: RawDocument): string | null {
  if (!raw.job_id) return null
  if (raw.status === 'succeeded' || raw.status === 'review') return 'completed'
  if (raw.status === 'failed') return 'failed'
  if (raw.status === 'running' || raw.status === 'queued') return 'running'
  return null
}

export const feedbackApi = {
  features(): Promise<{ selfheal: boolean }> {
    return http.get<{ selfheal: boolean }>('/system/features')
  },
  list(docId: string): Promise<{ items: FeedbackItem[] }> {
    return http.get<{ items: FeedbackItem[] }>(`/documents/${docId}/feedback`)
  },
  create(docId: string, payload: FeedbackCreatePayload): Promise<FeedbackCreateResult> {
    return http.post<FeedbackCreateResult>(`/documents/${docId}/feedback`, payload)
  },
  detail(docId: string, feedbackId: string): Promise<FeedbackDetail> {
    return http.get<FeedbackDetail>(`/documents/${docId}/feedback/${feedbackId}`)
  },
  process(docId: string, feedbackId: string): Promise<FeedbackOutcome> {
    return http.post<FeedbackOutcome>(
      `/documents/${docId}/feedback/${feedbackId}/process`,
      undefined,
      { timeout: 900000 },
    )
  },
  repair(docId: string, feedbackId: string): Promise<{
    available: boolean
    kind?: string
    summary?: Record<string, number>
    out_dir?: string
  }> {
    return http.get(`/documents/${docId}/feedback/${feedbackId}/repair`)
  },
  apply(docId: string, feedbackId: string): Promise<{
    applied: boolean
    feedback_id: string
    kind: string
    summary: Record<string, number> | null
    counts: Record<string, number>
    backup: string
    document_rule_saved?: boolean
    template_signature?: string
    template_status?: string
    rule_learning?: {
      status?: string
      level?: string
      reason?: string
      alias?: { detail?: string } | null
    }
  }> {
    return http.post(
      `/documents/${docId}/feedback/${feedbackId}/apply`,
      undefined,
      { timeout: 180000 },
    )
  },
  approveTemplate(signature: string): Promise<{ signature: string; status: string }> {
    return http.post(`/system/template-repairs/${signature}/approve`)
  },
}

export const extractionApi = {
  async listDocuments(moduleKey: string): Promise<{ items: ExtractableDocument[] }> {
    const rows = await http.get<RawDocument[]>('/documents', {
      params: { module: moduleKey, limit: 500, offset: 0 },
    })
    return {
      items: rows.map((row) => ({
        id: row.id,
        filename: row.file_name,
        file_size: row.file_size ?? 0,
        page_count: row.page_count ?? Number(row.task?.summary?.pages ?? 0),
        status: docStatus(row),
        extraction_status: extractionStatus(row),
        latest_schema_name: row.latest_schema_name ?? null,
        history_count: row.history_count ?? 0,
        updated_at: row.created_at,
      })),
    }
  },
  start(_kbId: string, docId: string): Promise<{ task_id: string; status: string }> {
    return http.post(`/documents/${docId}/parse`)
  },
  async status(_kbId: string, docId: string): Promise<ExtractionStatusData> {
    const raw = await http.get<RawDocument>(`/documents/${docId}`)
    const task = raw.task
    return {
      task_id: task?.job_id ?? raw.job_id,
      task_status: task?.status ?? null,
      status:
        raw.status === 'succeeded' || raw.status === 'review'
          ? 'completed'
          : raw.status === 'failed'
            ? 'failed'
            : task?.status === 'running' || raw.status === 'running'
              ? 'running'
              : 'idle',
      progress: task?.progress ?? (raw.status === 'succeeded' ? 100 : 0),
      error: task?.error ? { message: task.error } : null,
    }
  },
  async result(_kbId: string, docId: string): Promise<ExtractionResultData | null> {
    try {
      const payload = await http.get<{
        schema_template_id: string | null
        schema_name: string
        categories: ExtractionCategory[]
        summary: Record<string, unknown>
        timing: Record<string, unknown>
      }>(`/documents/${docId}/result/schema`)
      const document = await http.get<RawDocument>(`/documents/${docId}`)
      return {
        schema_template_id: payload.schema_template_id,
        schema_name: payload.schema_name,
        status: 'completed',
        progress: 100,
        categories: payload.categories || [],
        summary: payload.summary || {},
        timing: payload.timing || {},
        version: document.review_version ?? 1,
        error: null,
        updated_at: document.created_at,
      }
    } catch {
      return null
    }
  },
  async history(
    _kbId: string,
    docId: string,
  ): Promise<{ items: ExtractionHistoryItem[] }> {
    try {
      const rows = await http.get<
        Array<{
          job_id: string
          version: number
          status: string
          created_at: string
          schema_name: string
          category_count: number
          record_count: number
        }>
      >(`/documents/${docId}/result/versions`)
      return {
        items: rows.map((row) => ({
          id: row.job_id,
          schema_template_id: null,
          schema_name: row.schema_name,
          categories: [],
          summary: {
            category_count: row.category_count,
            record_count: row.record_count,
          },
          timing: {},
          version: row.version,
          extracted_at: row.created_at,
          archived_at: row.created_at,
        })),
      }
    } catch {
      return { items: [] }
    }
  },
  async getDocument(_kbId: string, docId: string): Promise<ExtractionDocDetail> {
    const raw = await http.get<RawDocument>(`/documents/${docId}`)
    return {
      id: raw.id,
      filename: raw.file_name,
      file_type: 'pdf',
      status: docStatus(raw),
    }
  },
  async exportFile(
    docId: string,
    format: 'hanson' | 'json' | 'csv' | 'xlsx',
  ): Promise<void> {
    const token = getAccessToken()
    const resp = await fetch(`/v1/documents/${docId}/export?format=${format}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) throw new Error(`导出失败（${resp.status}）`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${docId}-${format}.${format === 'hanson' ? 'json' : format}`
    link.click()
    URL.revokeObjectURL(url)
  },
}
