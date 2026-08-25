import { http } from '@/api/client'

export interface IntegrationTaskStatus {
  task_id: string
  kb_id: string
  document_id: string | null
  prompt_id: string | null
  schema_template_id: string | null
  filename: string
  ocr_status: string
  ocr_progress: number
  extract_status: string
  extract_progress: number
  error: string
  result_version: number | null
  created_at: string | null
  updated_at: string | null
}

export const integrationApi = {
  status(taskId: string): Promise<IntegrationTaskStatus> {
    return http.get(`/integration/tasks/${taskId}/status`)
  },
  retrigger(taskId: string): Promise<IntegrationTaskStatus> {
    return http.post(`/integration/tasks/${taskId}/retrigger`)
  },
}
