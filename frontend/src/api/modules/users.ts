import { http } from '@/api'
import type { Paginated, User } from '@/api/types'

/** 用户管理 API（超管，对应后端 /users） */
export const usersApi = {
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
  }): Promise<User> {
    return http.post<User>('/users', data)
  },

  get(userId: string): Promise<User> {
    return http.get<User>(`/users/${userId}`)
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
    },
  ): Promise<User> {
    return http.put<User>(`/users/${userId}`, data)
  },

  setActive(userId: string, isActive: boolean): Promise<{ id: string; is_active: boolean }> {
    return http.patch(`/users/${userId}/active`, { is_active: isActive })
  },

  setSuperuser(userId: string, isSuperuser: boolean): Promise<{ id: string; is_superuser: boolean }> {
    return http.patch(`/users/${userId}/superuser`, { is_superuser: isSuperuser })
  },

  resetPassword(userId: string, newPassword: string): Promise<unknown> {
    return http.post(`/users/${userId}/reset-password`, { new_password: newPassword })
  },

  delete(userId: string): Promise<unknown> {
    return http.delete(`/users/${userId}`)
  },
}
