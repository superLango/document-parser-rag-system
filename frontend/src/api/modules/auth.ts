import { http } from '@/api'
import type { LoginRequest, Token, User } from '@/api/types'

/**
 * 认证相关接口
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
}
