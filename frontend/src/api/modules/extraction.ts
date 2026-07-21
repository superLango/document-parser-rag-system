import { http } from '@/api'
import { parseExtractionSSEStream } from '@/utils/extraction-sse'

/**
 * 可抽取文档（已完成 OCR 解析）
 */
export interface ExtractableDocument {
  id: string
  filename: string
  file_size: number
  file_type: string | null
  status: string
  text_length: number
  has_extraction: boolean
  latest_schema_id?: string | null
  created_at: string
  updated_at: string | null
}

/**
 * 可用于抽取的父分类 Schema
 */
export interface ExtractionSchema {
  id: string
  name: string
  description: string
  children_count: number
}

/**
 * 抽取结果中的字段定义
 */
export interface ExtractionField {
  name: string
  description?: string
  field_type?: string
  type?: string
  required?: boolean
}

/**
 * SSE 流式抽取事件回调
 */
export interface ExtractionStreamCallbacks {
  /** Schema 信息事件 */
  onSchemaInfo?: (data: {
    schema_name: string
    schema_description: string
    field_count: number
    has_samples: boolean
  }) => void
  /** 进度事件 */
  onProgress?: (data: {
    progress: number
    message: string
    chunk_index: number
    total_chunks: number
  }) => void
  /** 单块抽取完成事件 */
  onChunkResult?: (data: {
    data: Record<string, unknown>
    chunk_index: number
    progress: number
    message: string
  }) => void
  /** 单块抽取失败事件 */
  onChunkError?: (data: {
    chunk_index: number
    error: string
    message: string
  }) => void
  /** 抽取完成事件 */
  onDone?: (data: {
    data: Record<string, unknown>
    missing: string[]
    progress: number
    message: string
  }) => void
  /** 警告事件（如保存失败） */
  onWarning?: (data: { message: string }) => void
  /** 错误事件 */
  onError?: (message: string) => void
}

/**
 * 文档抽取 API
 */
export const extractionApi = {
  // 获取已完成 OCR 解析的文档列表（供抽取页面使用）
  listDocuments(): Promise<{ items: ExtractableDocument[]; total: number }> {
    return http.get('/extraction/documents')
  },

  // 获取所有可用于抽取的父分类 Schema
  listSchemas(): Promise<ExtractionSchema[]> {
    return http.get('/extraction/schemas')
  },

  // 获取指定文档已保存的抽取结果
  getResults(documentId: string): Promise<{
    document_id: string
    filename: string
    extractions: Record<string, { result: Record<string, unknown> }>
    latest_schema_id: string | null
    latest_result: Record<string, unknown> | null
  }> {
    return http.get(`/extraction/results/${documentId}`)
  },

  // 同步抽取（一次性返回完整结果）
  extract(data: {
    document_id: string
    schema_id: string
    save_result?: boolean
  }): Promise<{
    document_id: string
    schema_id: string
    schema_name: string
    result: Record<string, unknown>
    missing: string[]
  }> {
    return http.post('/extraction/', {
      document_id: data.document_id,
      schema_id: data.schema_id,
      save_result: data.save_result ?? true,
    })
  },

  /**
   * SSE 流式抽取
   * 通过 fetch + ReadableStream 消费 SSE 事件流
   */
  async extractStream(
    payload: {
      document_id: string
      schema_id: string
      chunk_size?: number
      overlap?: number
      save_result?: boolean
    },
    callbacks: ExtractionStreamCallbacks,
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/extraction/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        document_id: payload.document_id,
        schema_id: payload.schema_id,
        chunk_size: payload.chunk_size ?? 4000,
        overlap: payload.overlap ?? 200,
        save_result: payload.save_result ?? true,
      }),
    })

    if (!response.ok) {
      callbacks.onError?.(`HTTP ${response.status}`)
      return
    }

    await parseExtractionSSEStream(response, callbacks)
  },
}
