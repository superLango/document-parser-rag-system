/**
 * 仪表盘 API 模块。
 *
 * 对接后端 /dashboard 端点：全局统计、30 天趋势、分布。
 */
import { http } from '@/api'

export interface DashboardStats {
  documents_count: number
  tasks_count: number
  schemas_count: number
  terms_count: number
  kbs_count: number
  users_count: number
  success_rate: number
}

export interface DashboardTrends {
  dates: string[]
  documents: number[]
  tasks: number[]
}

export interface DistributionItem {
  name: string
  value: number
}

export interface DashboardDistribution {
  doc_types: DistributionItem[]
  task_statuses: DistributionItem[]
  task_types: DistributionItem[]
}

export const dashboardApi = {
  stats: () => http.get<DashboardStats>('/dashboard/stats'),
  trends: (days = 30) =>
    http.get<DashboardTrends>('/dashboard/trends', { params: { days } }),
  distribution: () => http.get<DashboardDistribution>('/dashboard/distribution'),
}
