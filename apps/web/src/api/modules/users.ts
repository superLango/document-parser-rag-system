import { http } from '@/api/client'
import type { UserAdminItem, UserSearchItem } from '@/api/types'

interface RawUser {
  id: string
  username: string
  display_name: string
  role: string
  is_active: boolean
  created_at: string
}

function toAdmin(raw: RawUser): UserAdminItem {
  return {
    id: raw.id,
    username: raw.username,
    email: null,
    full_name: raw.display_name || raw.username,
    phone: null,
    department: null,
    is_active: raw.is_active,
    is_superuser: raw.role === 'admin',
    roles: [],
    last_login_at: null,
    created_at: raw.created_at,
    status: raw.is_active ? 'active' : 'disabled',
  }
}

export const usersApi = {
  async list(params?: {
    page?: number
    page_size?: number
    keyword?: string
  }): Promise<{ items: UserAdminItem[]; total: number; page: number; page_size: number }> {
    const page = params?.page ?? 1
    const pageSize = params?.page_size ?? 20
    const rows = await http.get<RawUser[]>('/users', {
      params: {
        q: params?.keyword || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      },
    })
    return {
      items: rows.map(toAdmin),
      total: (page - 1) * pageSize + rows.length,
      page,
      page_size: pageSize,
    }
  },
  async search(keyword: string): Promise<UserSearchItem[]> {
    const rows = await http.get<RawUser[]>('/users', {
      params: { q: keyword, limit: 20 },
    })
    return rows.map((row) => ({
      id: row.id,
      username: row.username,
      full_name: row.display_name || null,
      department: null,
      email: null,
    }))
  },
  async create(data: {
    username: string
    password: string
    full_name?: string
    is_superuser?: boolean
  }): Promise<UserAdminItem> {
    return toAdmin(
      await http.post<RawUser>('/users', {
        username: data.username,
        password: data.password,
        display_name: data.full_name || data.username,
        role: data.is_superuser ? 'admin' : 'user',
      }),
    )
  },
  async update(
    id: string,
    data: {
      full_name?: string
      is_superuser?: boolean
      is_active?: boolean
      password?: string
    },
  ): Promise<UserAdminItem> {
    return toAdmin(
      await http.patch<RawUser>(`/users/${id}`, {
        display_name: data.full_name,
        role: data.is_superuser === undefined ? undefined : data.is_superuser ? 'admin' : 'user',
        is_active: data.is_active,
        password: data.password,
      }),
    )
  },
  setActive(id: string, active: boolean): Promise<UserAdminItem> {
    return usersApi.update(id, { is_active: active })
  },
  setSuperuser(id: string, value: boolean): Promise<UserAdminItem> {
    return usersApi.update(id, { is_superuser: value })
  },
  resetPassword(id: string, password: string): Promise<UserAdminItem> {
    return usersApi.update(id, { password })
  },
}
