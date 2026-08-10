import { http } from '@/api/client'
import type { Paginated, User } from '@/api/types'

export const usersApi = {
  search(keyword: string, limit = 20): Promise<import('@/api/types').UserSearchItem[]> {
    return http.get<import('@/api/types').UserSearchItem[]>('/users/search', {
      params: { keyword, limit },
    })
  },
  list(params?: {
    page?: number
    page_size?: number
    keyword?: string
    is_active?: boolean
  }): Promise<Paginated<User>> {
    return http.get<Paginated<User>>('/users', { params })
  },
  create(data: {
    username: string
    email?: string
    password: string
    full_name?: string
    phone?: string
    department?: string
    is_superuser?: boolean
    role_codes?: string[]
  }): Promise<User> {
    return http.post<User>('/users', data)
  },
  update(
    userId: string,
    data: {
      email?: string
      full_name?: string
      phone?: string
      department?: string
      notes?: string
      is_active?: boolean
      is_superuser?: boolean
      role_codes?: string[]
    },
  ): Promise<User> {
    return http.put<User>(`/users/${userId}`, data)
  },
  setActive(userId: string, isActive: boolean): Promise<{ id: string; is_active: boolean }> {
    return http.patch(`/users/${userId}/active`, { is_active: isActive })
  },
  setSuperuser(
    userId: string,
    isSuperuser: boolean,
  ): Promise<{ id: string; is_superuser: boolean }> {
    return http.patch(`/users/${userId}/superuser`, { is_superuser: isSuperuser })
  },
  setRoles(
    userId: string,
    roleCodes: string[],
  ): Promise<{ id: string; roles: import('@/api/types').RoleBrief[] }> {
    return http.put(`/users/${userId}/roles`, { role_codes: roleCodes })
  },
  approve(userId: string): Promise<{ id: string; roles: import('@/api/types').RoleBrief[] }> {
    return http.post(`/users/${userId}/approve`)
  },
  resetPassword(userId: string, newPassword: string): Promise<unknown> {
    return http.post(`/users/${userId}/reset-password`, { new_password: newPassword })
  },
  delete(userId: string): Promise<unknown> {
    return http.delete(`/users/${userId}`)
  },
}
