import { http } from '@/api'
import type { KnowledgeGraph } from '@/api/types'

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
  getStats(): Promise<{
    total_nodes: number
    total_relations: number
    node_labels: string[]
  }> {
    return http.get('/kg/stats')
  },
}
