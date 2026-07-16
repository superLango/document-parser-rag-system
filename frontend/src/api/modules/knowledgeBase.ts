import { http } from '@/api'
import type {
  TaskSubmitResponse,
  KBStats,
  KBSearchResponse,
} from '@/api/types'

/**
 * 知识库管理接口
 * 后端前缀为 /kb，所有索引/检索操作均通过 arq 异步任务执行
 */
export const knowledgeBaseApi = {
  // 知识库统计
  stats(): Promise<KBStats> {
    return http.get<KBStats>('/kb/stats')
  },

  // 索引单个文档（异步任务，返回 task_id 供轮询）
  indexDocument(docId: string): Promise<TaskSubmitResponse> {
    return http.post<TaskSubmitResponse>(`/kb/documents/${docId}/index`)
  },

  // 重建全部索引（异步任务，清空 Milvus 并重新索引所有已解析文档）
  rebuild(): Promise<TaskSubmitResponse> {
    return http.post<TaskSubmitResponse>('/kb/rebuild')
  },

  // 移除文档索引（异步任务，仅清理向量索引，不删除文档记录）
  removeDocument(docId: string): Promise<TaskSubmitResponse> {
    return http.delete<TaskSubmitResponse>(`/kb/documents/${docId}`)
  },

  // 知识库搜索（测试用，不经过 LLM 生成）
  search(query: string, topK?: number): Promise<KBSearchResponse> {
    return http.get<KBSearchResponse>('/kb/search', {
      params: { q: query, top_k: topK },
    })
  },
}
