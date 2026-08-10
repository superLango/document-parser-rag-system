import { http } from '@/api/client'
import type { AuditLog, AuditStats, Paginated } from '@/api/types'

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
  stats(days = 7): Promise<AuditStats> {
    return http.get<AuditStats>('/audit-logs/stats', { params: { days } })
  },
}
