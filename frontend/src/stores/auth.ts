import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/modules/auth'

/**
 * 认证状态管理
 * 处理 token、用户信息、登录登出逻辑
 */
export const useAuthStore = defineStore('auth', () => {
  // 从 localStorage 恢复 token
  const token = ref<string>(localStorage.getItem('token') || '')

  // 用户信息
  const user = ref<AuthUser | null>(null)

  // 是否已登录
  const isAuthenticated = computed(() => !!token.value)

  // 是否超级管理员
  const isSuperuser = computed(() => !!user.value?.is_superuser)

  // 用户名首字母（头像占位）
  const userInitial = computed(() => {
    const name = user.value?.username || 'U'
    return name.charAt(0).toUpperCase()
  })

  // 登录
  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password })
    token.value = res.access_token
    localStorage.setItem('token', res.access_token)
    await fetchUser()
  }

  // 获取当前用户信息
  // 仅在 401（令牌无效/过期）时清除登录态，其他错误（如网络异常）保留 token
  async function fetchUser() {
    try {
      const res = await authApi.getCurrentUser()
      user.value = res
    } catch (error: any) {
      const status = error?.response?.status
      if (status === 401) {
        logout()
      }
      // 非 401 错误不清除 token，允许后续请求重试
    }
  }

  // 登出
  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
  }

  return {
    token,
    user,
    isAuthenticated,
    isSuperuser,
    userInitial,
    login,
    fetchUser,
    logout,
  }
})

// ---------- 类型 ----------
interface AuthUser {
  id: string
  username: string
  email: string
  is_active: boolean
  is_superuser?: boolean
  full_name?: string | null
  phone?: string | null
  department?: string | null
  avatar?: string | null
  last_login_at?: string | null
  created_at: string
}
