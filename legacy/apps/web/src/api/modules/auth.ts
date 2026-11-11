import { http } from '@/api/client'
import type { Token, User } from '@/api/types'

export interface RawUser {
  id: string
  username: string
  display_name?: string
  role?: string
}

export function toUiUser(raw: RawUser): User {
  const isAdmin = raw.role === 'admin'
  return {
    id: raw.id,
    username: raw.username,
    email: null,
    is_active: true,
    is_superuser: isAdmin,
    full_name: raw.display_name || raw.username,
    phone: null,
    department: null,
    notes: null,
    avatar: null,
    last_login_at: null,
    last_login_ip: null,
    password_changed_at: null,
    created_at: '',
    roles: [],
    permissions: [],
  }
}

export interface PublicAuthConfig {
  require_auth: boolean
  anonymous: boolean
  anonymous_username: string
  allow_embed: boolean
}

export const authApi = {
  async getPublicConfig(): Promise<PublicAuthConfig> {
    return http.get<PublicAuthConfig>('/auth/config')
  },
  async login(data: { username: string; password: string }): Promise<Token> {
    const response = await http.post<{
      access_token: string
      token_type: string
      expires_in: number
      user: RawUser
    }>('/auth/login', data)
    return {
      access_token: response.access_token,
      refresh_token: null,
      token_type: response.token_type,
      expires_in: response.expires_in,
    }
  },
  async getCurrentUser(): Promise<User> {
    // `/auth/me` returns { actor_type, user } for user tokens and
    // { actor_type, api_key } for key tokens.
    const payload = await http.get<RawUser & { user?: RawUser }>('/auth/me')
    const raw = payload.user ?? payload
    return toUiUser(raw)
  },
  async updateProfile(data: { full_name?: string }): Promise<User> {
    const raw = await http.patch<RawUser>('/auth/me', {
      display_name: data.full_name,
    })
    return toUiUser(raw)
  },
  changePassword(data: {
    old_password: string
    new_password: string
  }): Promise<unknown> {
    return http.post('/auth/password', data)
  },
}
