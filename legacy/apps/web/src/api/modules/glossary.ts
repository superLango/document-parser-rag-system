import { http } from '@/api/client'
import type { Paginated, TermBase, TermItem } from '@/api/types'

export interface GlossaryCreatePayload {
  name: string
  description?: string
  source_type: 'manual' | 'api' | 'db'
  source_config?: Record<string, unknown>
  columns?: Array<{ name: string; type: string; label: string }>
  column_aliases?: Record<string, string>
  sync_enabled?: boolean
  sync_cron?: string
}

export const glossaryApi = {
  list(kbId: string, params?: { page?: number; page_size?: number; keyword?: string }): Promise<Paginated<TermBase>> {
    return http.get<Paginated<TermBase>>(`/kb/${kbId}/term-bases`, { params })
  },
  create(kbId: string, data: GlossaryCreatePayload): Promise<TermBase & { imported?: number }> {
    return http.post(`/kb/${kbId}/term-bases`, data)
  },
  get(kbId: string, baseId: string): Promise<TermBase> {
    return http.get<TermBase>(`/kb/${kbId}/term-bases/${baseId}`)
  },
  update(kbId: string, baseId: string, data: Partial<GlossaryCreatePayload>): Promise<TermBase> {
    return http.put(`/kb/${kbId}/term-bases/${baseId}`, data)
  },
  remove(kbId: string, baseId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/term-bases/${baseId}`)
  },
  testApi(kbId: string, config: Record<string, unknown>): Promise<{ ok: boolean; rows: Array<Record<string, unknown>>; columns: Array<{ name: string; type: string; label: string }>; total: number }> {
    return http.post(`/kb/${kbId}/term-bases/test-api`, config)
  },
  testDb(kbId: string, config: Record<string, unknown>): Promise<{ ok: boolean }> {
    return http.post(`/kb/${kbId}/term-bases/test-db`, config)
  },
  dbTables(kbId: string, config: Record<string, unknown>): Promise<{ tables: string[] }> {
    return http.post(`/kb/${kbId}/term-bases/db-tables`, config)
  },
  previewSql(kbId: string, config: Record<string, unknown>): Promise<{ rows: Array<Record<string, unknown>>; columns: Array<{ name: string; type: string; label: string }>; total: number }> {
    return http.post(`/kb/${kbId}/term-bases/preview-sql`, config)
  },
  sync(kbId: string, baseId: string): Promise<{ imported: number; total: number; skipped: number }> {
    return http.post(`/kb/${kbId}/term-bases/${baseId}/sync`)
  },
  validateCron(kbId: string, cron: string): Promise<{ cron: string; next_run_at: string }> {
    return http.post(`/kb/${kbId}/term-bases/cron-validate`, { cron })
  },
  batchSaveTerms(
    kbId: string,
    baseId: string,
    data: {
      items: Array<{
        id?: string
        term: string
        english_term?: string
        aliases?: string[]
        definition?: string
        category?: string
        standard_number?: string
        synonyms?: string[]
        extras?: Record<string, unknown>
      }>
      deleted_ids?: string[]
    },
  ): Promise<{ created: number; updated: number; deleted: number }> {
    return http.put(`/kb/${kbId}/term-bases/${baseId}/terms/batch`, data)
  },
  listTerms(kbId: string, params?: { page?: number; page_size?: number; term_base_id?: string; keyword?: string; search_field?: string }): Promise<Paginated<TermItem>> {
    return http.get<Paginated<TermItem>>(`/kb/${kbId}/terms`, { params })
  },
  listExpandedNames(kbId: string, baseId: string, field?: string): Promise<{ items: string[] }> {
    return http.get(`/kb/${kbId}/term-bases/${baseId}/expanded-names`, { params: field ? { field } : undefined })
  },
}
