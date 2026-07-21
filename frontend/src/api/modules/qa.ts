import { http } from '@/api'
import type { QARequest, QAResponse, QAMessage } from '@/api/types'
import { parseSSEStream } from '@/utils/sse'

/**
 * 流式问答引用信息（对应后端 SSE done 事件的 citations 字段）
 */
export interface Citation {
  document_id?: string
  chunk_id?: string
  content?: string
  score?: number
  source?: string  // vector/graph
}

/**
 * 流式问答回调
 */
export interface AskStreamCallbacks {
  onChunk?: (content: string) => void
  onDone?: (data: { answer: string; citations: Citation[] }) => void
  onError?: (message: string) => void
}

/**
 * 智能问答（RAG）接口
 */
export const qaApi = {
  // 提问
  ask(data: QARequest): Promise<QAResponse> {
    return http.post<QAResponse>('/qa/query', data)
  },

  // 流式问答（SSE）：POST /qa/stream，使用 fetch + ReadableStream 消费
  async askStream(
    query: string,
    callbacks: AskStreamCallbacks,
    options?: {
      top_k?: number
      doc_ids?: string[]
      use_graph?: boolean
      use_reranker?: boolean
    },
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/qa/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        question: query,
        top_k: options?.top_k,
        doc_ids: options?.doc_ids,
        use_graph: options?.use_graph ?? true,
        use_reranker: options?.use_reranker ?? true,
      }),
    })

    if (!response.ok) {
      callbacks.onError?.(`HTTP ${response.status}`)
      return
    }

    await parseSSEStream(
      response,
      callbacks.onChunk ?? (() => {}),
      callbacks.onDone ?? (() => {}),
      callbacks.onError ?? (() => {}),
    )
  },

  // 会话历史
  getHistory(conversationId: string): Promise<QAMessage[]> {
    return http.get<QAMessage[]>(`/qa/conversations/${conversationId}/messages`)
  },

  // 会话列表
  getConversations(): Promise<{ id: string; title: string; updated_at: string }[]> {
    return http.get('/qa/conversations')
  },
}
