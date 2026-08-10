import { http } from '@/api/client'
import type { ApiKeyItem } from '@/api/types'

export const apiKeysApi = {
  list(): Promise<ApiKeyItem[]> {
    return http.get<ApiKeyItem[]>('/api-keys')
  },
  create(data: { name: string; scopes?: string[]; expires_at?: string }): Promise<ApiKeyItem> {
    return http.post<ApiKeyItem>('/api-keys', data)
  },
  revoke(keyId: string): Promise<unknown> {
    return http.delete(`/api-keys/${keyId}`)
  },
}
