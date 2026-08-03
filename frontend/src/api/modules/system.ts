import { http } from '@/api'

/** 单项依赖健康状态 */
export interface HealthCheck {
  status: 'healthy' | 'unhealthy' | 'unavailable' | 'degraded'
  error?: string
  host?: string
  endpoint?: string
  model?: string
  latency_ms?: number | null
}

/** 深度健康检查结果 */
export interface DeepHealth {
  status: 'healthy' | 'degraded' | 'unhealthy'
  checks: Record<string, HealthCheck>
  timestamp: string
}

/** 系统信息 */
export interface SystemInfo {
  app_name: string
  version: string
  env: string
  debug: boolean
  python: string
  platform: string
  components: Record<string, string>
  features: Record<string, unknown>
  timestamp: string
}

/** 模型健康检查结果 */
export interface ModelsHealth {
  llm: HealthCheck
  embedding: HealthCheck
  ocr_layout?: HealthCheck
  ocr_vllm?: HealthCheck
}

/** 系统 API（对应后端 /system） */
export const systemApi = {
  health(): Promise<{ status: string; timestamp: string }> {
    return http.get('/system/health')
  },

  deepHealth(): Promise<DeepHealth> {
    return http.get<DeepHealth>('/system/health/deep')
  },

  modelsHealth(): Promise<ModelsHealth> {
    return http.get('/system/health/models')
  },

  /** 检查 OCR 版面分析模型是否可用 */
  checkOcrLayout(): Promise<HealthCheck & { model_dir?: string }> {
    return http.get('/system/check-ocr-layout')
  },

  /** 检查 NebulaGraph 图数据库可用性（连接状态 + space 数量） */
  checkNebulaGraph(): Promise<{
    status: 'healthy' | 'unavailable' | 'degraded' | 'timeout'
    host: string
    port: number
    host_count?: number
    space_count?: number
    spaces?: string[]
    message?: string
    error?: string
  }> {
    return http.get('/system/check-nebula-graph')
  },

  storageHealth(): Promise<{
    postgres: HealthCheck
    redis: HealthCheck
    minio: HealthCheck
    milvus: HealthCheck
    nebula: HealthCheck
  }> {
    return http.get('/system/health/storage')
  },

  info(): Promise<SystemInfo> {
    return http.get<SystemInfo>('/system/info')
  },
}
