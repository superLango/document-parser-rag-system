/**
 * 公开一体化抽取接口封装（免鉴权）
 *
 * 供嵌入预览页面及外部系统集成调用。使用独立 axios 实例，不注入 JWT
 * （公开接口无需登录态），仅保留链路追踪 ID 与响应解包。
 */
import axios, { type AxiosResponse } from 'axios'

/** 一体化处理状态 */
export type ProcessStatus =
  | 'queued'
  | 'ocr_processing'
  | 'ocr_done'
  | 'extracting'
  | 'completed'
  | 'failed'

/** 上传响应 */
export interface UploadResult {
  task_id: string
  document_id: string
  status: string
}

/** 状态查询响应 */
export interface StatusResult {
  task_id: string
  document_id: string
  process_status: ProcessStatus
  progress: number
  message: string
  filename: string
  is_terminal: boolean
}

/** 抽取结果中的类别记录 */
export interface ResultCategory {
  feature?: string
  records?: Array<Record<string, unknown>>
  [key: string]: unknown
}

/** 结果获取响应 */
export interface ResultData {
  status: string
  task_id?: string
  document_id?: string
  filename?: string
  schema_name?: string | null
  extracted_at?: string | null
  summary?: Record<string, unknown> | null
  timing?: Record<string, unknown> | null
  result: {
    categories?: ResultCategory[]
    summary?: Record<string, unknown>
    timing?: Record<string, unknown>
  } | null
  message?: string
}

function generateTraceId(): string {
  return `trace-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

const publicClient = axios.create({
  baseURL: '/api/v1/public/extraction',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：注入链路追踪 ID（不注入 JWT）
publicClient.interceptors.request.use((config) => {
  config.headers['X-Trace-Id'] = generateTraceId()
  return config
})

// 响应拦截：解包后端统一响应体 { code, message, data } → data
publicClient.interceptors.response.use(
  (response: AxiosResponse) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
      return body.data
    }
    return body
  },
  (error) => Promise.reject(error),
)

export const publicApi = {
  /** 上传 PDF，返回 task_id */
  uploadDocument(file: File, kbId?: string): Promise<UploadResult> {
    const formData = new FormData()
    formData.append('file', file)
    return publicClient.post('/upload', formData, {
      params: kbId ? { kb_id: kbId } : undefined,
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as unknown as Promise<UploadResult>
  },

  /** 查询处理状态 */
  getStatus(taskId: string): Promise<StatusResult> {
    return publicClient.get(`/${taskId}/status`) as unknown as Promise<StatusResult>
  },

  /** 获取抽取结果 JSON */
  getResult(taskId: string): Promise<ResultData> {
    return publicClient.get(`/${taskId}/result`) as unknown as Promise<ResultData>
  },
}
