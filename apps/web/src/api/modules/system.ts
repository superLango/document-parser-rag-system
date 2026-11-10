import { http } from '@/api/client'

export interface SystemInfo {
  app_name: string
  version: string
  env: string
  database: string
  python: string
  platform: string
  timestamp: string
  features: Record<string, boolean>
}

export const systemApi = {
  async info(): Promise<SystemInfo> {
    const health = await http.get<{
      status: string
      version: string
      ocr_backend: string
      extractor_backend: string
      business_dictionary: string
    }>('/../health').catch(() => null)
    const version = health?.version ?? '0.1.0'
    return {
      app_name: 'HansonDOC 文档结构化平台',
      version,
      env: 'production',
      database: 'PostgreSQL',
      python: '-',
      platform: 'Docker',
      timestamp: new Date().toISOString(),
      features: {
        ocr: Boolean(health?.ocr_backend),
        extractor: Boolean(health?.extractor_backend),
        dictionary: Boolean(health?.business_dictionary),
      },
    }
  },
}
