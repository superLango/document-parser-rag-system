import { http } from '@/api/client'

export type ModuleKey =
  | 'standard_split'
  | 'order_parse'
  | 'certificate_parse'
  | 'outsource_report'

export interface ModuleItem {
  key: ModuleKey
  name: string
  summary: string
  description: string
  status: 'active' | 'planned'
  input_types: string[]
  highlights: string[]
  kb_id: string | null
  role: string
  document_count: number
  task_count: number
  pending_review_count: number
  confirmed_count: number
  created_at: string | null
}

export const modulesApi = {
  list(): Promise<ModuleItem[]> {
    return http.get<ModuleItem[]>('/modules')
  },
  get(key: string): Promise<ModuleItem> {
    return http.get<ModuleItem>(`/modules/${key}`)
  },
}
