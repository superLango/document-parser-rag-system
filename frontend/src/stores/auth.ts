import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi } from '@/api/modules/auth'
import { clearTokens, setTokens } from '@/api/client'
import type { User } from '@/api/types'

interface AuthState {
  user: User | null
  initialized: boolean
  login: (username: string, password: string) => Promise<User>
  fetchUser: () => Promise<User | null>
  logout: () => void
  setUser: (user: User) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      initialized: false,

      async login(username: string, password: string) {
        const token = await authApi.login({ username, password })
        setTokens(token.access_token, token.refresh_token)
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
      name: 'hansondoc-auth',
      partialize: (state) => ({ user: state.user }),
    },
  ),
)

export function isAuthenticated(): boolean {
  return Boolean(localStorage.getItem('access_token'))
}
