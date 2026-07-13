import { http } from '@/api'
import type { DashboardStats } from '@/api/types'

/**
 * 仪表盘统计接口
 */
export const dashboardApi = {
  // 获取统计数据
  getStats(): Promise<DashboardStats> {
    return http.get<DashboardStats>('/dashboard/stats')
  },
}
