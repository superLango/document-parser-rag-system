import { http } from '@/api/client'
import type { DashboardOverview, DashboardStats } from '@/api/types'

export const dashboardApi = {
  overview(): Promise<DashboardOverview> {
    return http.get<DashboardOverview>('/dashboard/overview')
  },
  stats(): Promise<DashboardStats> {
    return http.get<DashboardStats>('/dashboard/stats')
  },
  trends(days = 7): Promise<{ days: number; login: { date: string; count: number }[] }> {
    return http.get('/dashboard/trends', { params: { days } })
  },
}
