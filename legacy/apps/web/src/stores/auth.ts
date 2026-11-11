import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { authApi } from '@/api/modules/auth'
import { clearTokens, setAuthRequired, setTokens } from '@/api/client'
import { safeStorage } from '@/lib/storage'
import type { User } from '@/api/types'

interface AuthState {
  user: User | null
  initialized: boolean
  requireAuth: boolean | null
  allowEmbed: boolean
  login: (username: string, password: string) => Promise<User>
  fetchUser: () => Promise<User | null>
  loadPublicConfig: () => Promise<void>
  logout: () => void
  setUser: (user: User) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      initialized: false,
      requireAuth: null,
      allowEmbed: true,

      async loadPublicConfig() {
        try {
          const config = await authApi.getPublicConfig()
          setAuthRequired(config.require_auth)
          set({
            requireAuth: config.require_auth,
            allowEmbed: config.allow_embed,
          })
        } catch {
          // 配置读取失败时按需要登录处理，避免误开放。
          setAuthRequired(true)
          set({ requireAuth: true })
        }
      },

      async login(username: string, password: string) {
        const token = await authApi.login({ username, password })
        setTokens(token.access_token)
        const user = await authApi.getCurrentUser()
        set({ user, initialized: true })
        return user
      },

      async fetchUser() {
        try {
          const user = await authApi.getCurrentUser()
          set({ user, initialized: true })
          return user
        } catch {
          set({ user: null, initialized: true })
          return null
        }
      },

      logout() {
        clearTokens()
        set({ user: null, initialized: true })
      },

      setUser(user: User) {
        set({ user })
      },
    }),
    {
      name: 'hanson-auth',
      storage: createJSONStorage(() => safeStorage),
      partialize: (state) => ({ user: state.user }),
    },
  ),
)

export function isAuthenticated(): boolean {
  return Boolean(safeStorage.getItem('access_token'))
}
