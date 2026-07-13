import { http } from '@/api'
import type { QARequest, QAResponse, QAMessage } from '@/api/types'

/**
 * 智能问答（RAG）接口
 */
export const qaApi = {
  // 提问
  ask(data: QARequest): Promise<QAResponse> {
    return http.post<QAResponse>('/qa/query', data)
  },

  // 流式问答（SSE）
  askStream(data: QARequest): EventSource {
    const params = new URLSearchParams({
      question: data.question,
      top_k: String(data.top_k ?? 5),
    })
    if (data.conversation_id) {
      params.append('conversation_id', data.conversation_id)
    }
    return new EventSource(`/api/v1/qa/ask/stream?${params.toString()}`)
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
