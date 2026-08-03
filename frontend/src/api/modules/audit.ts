import { http } from '@/api'
import type { Paginated } from '@/api/types'

/** 审计日志条目 */
export interface AuditLog {
  id: string
  user_id: string | null
  username: string | null
  kb_id: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  method: string | null
  path: string | null
  status_code: number | null
  ip: string | null
  user_agent: string | null
  details: Record<string, unknown> | null
  trace_id: string | null
  created_at: string
}

/** 审计统计数据 */
export interface AuditStats {
  days: number
  total: number
  by_action: Record<string, number>
  by_day: { date: string; count: number }[]
  by_user: Record<string, number>
  by_resource_type: Record<string, number>
}

/** 审计日志 API（超管，对应后端 /audit-logs） */
export const auditApi = {
  list(params?: {
    page?: number
    page_size?: number
    action?: string
    user_id?: string
    kb_id?: string
    resource_type?: string
    start_date?: string
    end_date?: string
  }): Promise<Paginated<AuditLog>> {
    return http.get<Paginated<AuditLog>>('/audit-logs', { params })
  },

  listActions(): Promise<string[]> {
    return http.get<string[]>('/audit-logs/actions')
  },

  stats(days?: number): Promise<AuditStats> {
    return http.get<AuditStats>('/audit-logs/stats', { params: { days } })
  },
}
