import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import { ApiError, clearTokens, getAccessToken } from '@/api/client'

/**
 * 一站式对接兼容客户端。
 *
 * hansonDoc_RAG 的对接地址是 `/api/v1/integration/...`，当前平台常规 API
 * 是 `/v1/...`。这里单独建 axios 实例，保持旧地址与旧响应信封
 * `{code, message, data, trace_id}` 不变。
 */
const instance = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

instance.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

instance.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      throw new ApiError(200, body.message || '请求失败', body)
    }
    return body
  },
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      clearTokens()
    }
    const data = error.response?.data as
      | { message?: string; detail?: unknown }
      | undefined
    const detail = data?.message ?? data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail
          ? String((detail as { message?: unknown }).message ?? '请求失败')
          : error.message || '请求失败'
    return Promise.reject(
      new ApiError(error.response?.status ?? 0, message, detail),
    )
  },
)

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

export interface IntegrationCategory {
  feature: string
  records: Array<Record<string, unknown>>
  rejected: unknown[]
  missing_fields: string[]
  hit_count: number
}

export interface IntegrationResult {
  schema_template_id: string | null
  schema_name: string
  status: string
  progress: number
  categories: IntegrationCategory[]
  summary: Record<string, number>
  timing: Record<string, number>
  version: number | null
  error: string | null
  updated_at: string | null
}

export interface IntegrationSessionToken {
  task_id: string
  token: string
  document_id: string | null
  kb_id: string
  expires_at?: string
  path?: string
}

export const integrationApi = {
  upload(
    file: File,
    kbId: string,
    promptId: string,
  ): Promise<IntegrationTaskStatus> {
    const form = new FormData()
    form.append('file', file)
    return instance.post('/integration/upload', form, {
      params: { kb_id: kbId, prompt_id: promptId },
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as unknown as Promise<IntegrationTaskStatus>
  },
  status(
    taskId: string,
    config?: AxiosRequestConfig,
  ): Promise<IntegrationTaskStatus> {
    return instance.get(
      `/integration/tasks/${taskId}/status`,
      config,
    ) as unknown as Promise<IntegrationTaskStatus>
  },
  result(
    taskId: string,
    config?: AxiosRequestConfig,
  ): Promise<IntegrationResult | null> {
    return instance.get(
      `/integration/tasks/${taskId}/result`,
      config,
    ) as unknown as Promise<IntegrationResult | null>
  },
  retrigger(taskId: string): Promise<IntegrationTaskStatus> {
    return instance.post(
      `/integration/tasks/${taskId}/retrigger`,
    ) as unknown as Promise<IntegrationTaskStatus>
  },
  sessionToken(taskId: string): Promise<IntegrationSessionToken> {
    return instance.get(
      `/integration/tasks/${taskId}/session-token`,
    ) as unknown as Promise<IntegrationSessionToken>
  },
}
