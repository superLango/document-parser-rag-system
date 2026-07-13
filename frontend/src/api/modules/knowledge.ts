import { http } from '@/api'
import type { KnowledgeGraph } from '@/api/types'

/**
 * 知识图谱接口
 */
export const knowledgeApi = {
  // 获取知识图谱
  getGraph(params?: {
    document_id?: number
    node_type?: string
    keyword?: string
    limit?: number
  }): Promise<KnowledgeGraph> {
    return http.get<KnowledgeGraph>('/knowledge/graph', { params })
  },

  // 节点详情
  getNode(id: string): Promise<Record<string, unknown>> {
    return http.get<Record<string, unknown>>(`/knowledge/nodes/${id}`)
  },

  // 关联查询
  getRelations(nodeId: string): Promise<{ source: string; target: string; label: string }[]> {
    return http.get(`/knowledge/nodes/${nodeId}/relations`)
  },

  // 全文搜索
  search(keyword: string): Promise<KnowledgeGraph> {
    return http.get<KnowledgeGraph>('/knowledge/search', { params: { keyword } })
  },
}
