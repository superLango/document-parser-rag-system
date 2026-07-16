import { http } from '@/api'
import type { KnowledgeGraph } from '@/api/types'

/**
 * 图谱任务提交响应
 * 后端 POST /kg/documents/{doc_id}/graph、/kg/rebuild、DELETE /kg/documents/{doc_id}
 * 均返回 { task_id, status }
 */
export interface GraphTaskResponse {
  task_id: string
  status: string
}

/**
 * 图统计信息
 * 后端 GET /kg/stats 返回字段
 */
export interface GraphStats {
  total_nodes: number
  total_relations: number
  node_labels: string[]
}

/**
 * 知识图谱接口
 * 后端前缀为 /kg（非 /knowledge）
 */
export const knowledgeApi = {
  // 获取全局知识图谱（限制节点数）
  getGraph(params?: {
    limit?: number
  }): Promise<KnowledgeGraph> {
    return http.get<KnowledgeGraph>('/kg/graph', { params })
  },

  // 搜索节点（按名称关键词模糊匹配）
  search(keyword: string): Promise<KnowledgeGraph> {
    return http.get<KnowledgeGraph>('/kg/search', {
      params: { name: keyword },
    })
  },

  // 获取子图（以指定实体为中心，N 跳邻居）
  getSubgraph(entity: string, maxHops?: number): Promise<KnowledgeGraph> {
    return http.get<KnowledgeGraph>('/kg/subgraph', {
      params: { entity, max_hops: maxHops ?? 2 },
    })
  },

  // 图统计信息
  getStats(): Promise<GraphStats> {
    return http.get<GraphStats>('/kg/stats')
  },

  // 构建文档知识图谱（异步任务）
  buildGraph(docId: string): Promise<GraphTaskResponse> {
    return http.post<GraphTaskResponse>(`/kg/documents/${docId}/graph`)
  },

  // 重建全部知识图谱（异步任务）
  rebuildGraph(): Promise<GraphTaskResponse> {
    return http.post<GraphTaskResponse>('/kg/rebuild')
  },

  // 删除文档知识图谱（异步任务）
  deleteGraph(docId: string): Promise<GraphTaskResponse> {
    return http.delete<GraphTaskResponse>(`/kg/documents/${docId}`)
  },
}
