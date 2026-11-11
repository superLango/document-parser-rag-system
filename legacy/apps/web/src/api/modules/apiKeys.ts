import { http } from '@/api/client'
import type { ApiKeyItem } from '@/api/types'

interface RawApiKey {
  id: string
  name: string
  prefix: string
  scopes: string[]
  workspace_id: string
  kb_ids: string[]
  created_at: string
  revoked_at: string | null
  key?: string | null
}

function toItem(raw: RawApiKey): ApiKeyItem {
  return {
    id: raw.id,
    name: raw.name,
    key_prefix: raw.prefix,
    scopes: raw.scopes || [],
    expires_at: null,
    last_used_at: null,
    created_at: raw.created_at,
    revoked_at: raw.revoked_at,
    secret: raw.key ?? undefined,
  }
}

export const apiKeysApi = {
  async list(): Promise<ApiKeyItem[]> {
    const rows = await http.get<RawApiKey[]>('/api-keys')
    return rows.map(toItem)
  },
  async create(data: { name: string; scopes?: string[] }): Promise<ApiKeyItem> {
    return toItem(
      await http.post<RawApiKey>('/api-keys', {
        name: data.name,
        scopes: data.scopes?.length
          ? data.scopes
          : ['documents:read', 'documents:write', 'tasks:read'],
      }),
    )
  },
  revoke(id: string): Promise<unknown> {
    return http.delete(`/api-keys/${id}`)
  },
}
