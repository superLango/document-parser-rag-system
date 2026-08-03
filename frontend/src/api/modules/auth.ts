import { http } from '@/api'
import type { LoginRequest, Token, User } from '@/api/types'

/**
 * 认证相关接口（阶段 1.1 扩展）
 */
export const authApi = {
  // 登录获取 token
  login(data: LoginRequest): Promise<Token> {
    return http.post<Token>('/auth/login', data)
  },

  // 获取当前登录用户
  getCurrentUser(): Promise<User> {
    return http.get<User>('/auth/me')
  },

  // 登出
  logout(): Promise<void> {
    return http.post<void>('/auth/logout')
  },

  // 注册（开放注册，默认普通用户）
  register(data: {
    username: string
    password: string
    email?: string
    full_name?: string
  }): Promise<User> {
    return http.post<User>('/auth/register', data)
  },

  // 修改密码（需旧密码）
  changePassword(data: { old_password: string; new_password: string }): Promise<unknown> {
    return http.post('/auth/change-password', data)
  },

  // 重置密码（携带令牌）
  resetPassword(data: { token: string; new_password: string }): Promise<unknown> {
    return http.post('/auth/reset-password', data)
  },

  // 更新个人资料
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
