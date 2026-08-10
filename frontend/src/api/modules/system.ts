import { http } from '@/api/client'
import type { HealthCheck, SystemInfo } from '@/api/types'

export const systemApi = {
  info(): Promise<SystemInfo> {
    return http.get<SystemInfo>('/system/info')
  },
  health(): Promise<{ status: string; timestamp: string }> {
    return http.get('/system/health')
  },
  deepHealth(): Promise<{
    status: string
    checks: Record<string, HealthCheck>
    timestamp: string
  }> {
    return http.get('/system/health/deep')
  },
  storageHealth(): Promise<{
    postgres: HealthCheck
    redis: HealthCheck
  }> {
    return http.get('/system/health/storage')
  },
}
