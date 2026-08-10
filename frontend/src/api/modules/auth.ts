import { http } from '@/api/client'
import type { Token, User } from '@/api/types'

export const authApi = {
  login(data: { username: string; password: string }): Promise<Token> {
    return http.post<Token>('/auth/login', data)
  },
  refresh(): Promise<Token> {
    return http.post<Token>('/auth/refresh')
  },
  getCurrentUser(): Promise<User> {
    return http.get<User>('/auth/me')
  },
  register(data: {
    username: string
    password: string
    email?: string
    full_name?: string
  }): Promise<User> {
    return http.post<User>('/auth/register', data)
  },
  changePassword(data: { old_password: string; new_password: string }): Promise<unknown> {
    return http.post('/auth/change-password', data)
  },
  resetPassword(data: { token: string; new_password: string }): Promise<unknown> {
    return http.post('/auth/reset-password', data)
  },
  updateProfile(data: {
    email?: string
    full_name?: string
    phone?: string
    department?: string
    avatar?: string
  }): Promise<User> {
    return http.put<User>('/auth/profile', data)
  },
}
