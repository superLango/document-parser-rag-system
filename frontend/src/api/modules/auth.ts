import { http } from '@/api'
import type { LoginRequest, Token, User } from '@/api/types'

/**
 * 认证相关接口
 */
export const authApi = {
  // 登录获取 token
  login(data: LoginRequest): Promise<Token> {
    // 后端 OAuth2PasswordRequestForm 需要 form-data
    const formData = new URLSearchParams()
    formData.append('username', data.username)
    formData.append('password', data.password)
    return http.post<Token>('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
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
