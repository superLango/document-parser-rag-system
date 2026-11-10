import { http } from '@/api/client'
import type { AuditLog, AuditStats } from '@/api/types'

interface RawAudit {
  id: string
  actor_id: string
  actor_type: string
  workspace_id: string
  action: string
  target_type: string
  target_id: string
  detail: string
  created_at: string
}

function toLog(raw: RawAudit): AuditLog {
  let details: Record<string, unknown> | null = null
  if (raw.detail) {
    try {
      details = JSON.parse(raw.detail) as Record<string, unknown>
    } catch {
      details = { detail: raw.detail }
    }
  }
  return {
    id: raw.id,
    user_id: raw.actor_id,
    username: raw.actor_id,
    kb_id: raw.workspace_id || null,
    action: raw.action,
    resource_type: raw.target_type,
    resource_id: raw.target_id,
    method: null,
    path: null,
    status_code: null,
    ip: null,
    user_agent: null,
    details,
    trace_id: null,
    created_at: raw.created_at,
  }
}

export async function exportAuditCsv(params?: {
  action?: string
  resource_type?: string
  start_date?: string
  end_date?: string
}): Promise<Blob> {
  const result = await auditApi.list({
    action: params?.action,
    resource_type: params?.resource_type,
    start_date: params?.start_date,
    end_date: params?.end_date,
    page: 1,
    page_size: 500,
  })
  const header = ['时间', '动作', '资源类型', '资源ID', '操作者', '详情']
  const lines = [header.join(',')]
  for (const row of result.items) {
    lines.push(
      [
        row.created_at,
        row.action,
        row.resource_type ?? '',
        row.resource_id ?? '',
        row.username ?? '',
        JSON.stringify(row.details ?? {}).replaceAll('"', '""'),
      ]
        .map((value) => `"${String(value).replaceAll('"', '""')}"`)
        .join(','),
    )
  }
  return new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
}

export const auditApi = {
  async list(params?: {
    action?: string
    user_id?: string
    resource_type?: string
    start_date?: string
    end_date?: string
    page?: number
    page_size?: number
  }): Promise<{ items: AuditLog[]; total: number; page: number; page_size: number }> {
    const page = params?.page ?? 1
    const pageSize = params?.page_size ?? 20
    const rows = await http.get<RawAudit[]>('/audit-logs', {
      params: { limit: pageSize, offset: (page - 1) * pageSize },
    })
    const start = params?.start_date ? new Date(params.start_date).getTime() : null
    const end = params?.end_date ? new Date(params.end_date).getTime() + 86400000 : null
    const filtered = rows.filter((row) => {
      if (params?.action && row.action !== params.action) return false
      if (params?.resource_type && row.target_type !== params.resource_type) return false
      const at = new Date(row.created_at).getTime()
      if (start !== null && at < start) return false
      if (end !== null && at >= end) return false
      return true
    })
    return {
      items: filtered.map(toLog),
      total: filtered.length,
      page,
      page_size: pageSize,
    }
  },
  async listActions(): Promise<string[]> {
    const rows = await http.get<RawAudit[]>('/audit-logs', {
      params: { limit: 500, offset: 0 },
    })
    return Array.from(new Set(rows.map((row) => row.action))).sort()
  },
  async stats(days = 7): Promise<AuditStats> {
    const rows = await http.get<RawAudit[]>('/audit-logs', {
      params: { limit: 500, offset: 0 },
    })
    const cutoff = Date.now() - days * 24 * 3600 * 1000
    const recent = rows.filter(
      (row) => new Date(row.created_at).getTime() >= cutoff,
    )
    const byAction: Record<string, number> = {}
    const byUser: Record<string, number> = {}
    const byResource: Record<string, number> = {}
    const byDay: Record<string, number> = {}
    for (const row of recent) {
      byAction[row.action] = (byAction[row.action] ?? 0) + 1
      byUser[row.actor_id] = (byUser[row.actor_id] ?? 0) + 1
      byResource[row.target_type] = (byResource[row.target_type] ?? 0) + 1
      const day = row.created_at.slice(0, 10)
      byDay[day] = (byDay[day] ?? 0) + 1
    }
    return {
      days,
      total: recent.length,
      by_action: byAction,
      by_day: Object.entries(byDay)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, count]) => ({ date, count })),
      by_user: byUser,
      by_resource_type: byResource,
    }
  },
}
