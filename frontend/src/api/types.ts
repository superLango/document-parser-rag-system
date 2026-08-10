export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface RoleBrief {
  id: string
  code: string
  name: string
  is_system: boolean
}

export interface Role extends RoleBrief {
  description: string | null
  sort_order: number
  permission_count?: number
  permissions?: string[]
}

export interface PermissionItem {
  id: string
  code: string
  name: string
  resource_type: string | null
  description: string | null
}

export interface User {
  id: string
  username: string
  email: string | null
  is_active: boolean
  is_superuser: boolean
  full_name: string | null
  phone: string | null
  department: string | null
  notes: string | null
  avatar: string | null
  last_login_at: string | null
  last_login_ip: string | null
  password_changed_at: string | null
  created_at: string
  roles: RoleBrief[]
  permissions: string[]
}

export interface Token {
  access_token: string
  refresh_token?: string | null
  token_type: string
  expires_in: number
}

export interface AuditLog {
  id: string
  user_id: string | null
  username: string | null
  kb_id: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  method: string | null
  path: string | null
  status_code: number | null
  ip: string | null
  user_agent: string | null
  details: Record<string, unknown> | null
  trace_id: string | null
  created_at: string
}

export interface AuditStats {
  days: number
  total: number
  by_action: Record<string, number>
  by_day: { date: string; count: number }[]
  by_user: Record<string, number>
  by_resource_type: Record<string, number>
}

export interface DashboardOverview {
  project: {
    app_name: string
    version: string
    env: string
    debug: boolean
    database: string
  }
  user: {
    id: string
    username: string
    full_name: string | null
    email: string | null
    is_superuser: boolean
    last_login_at: string | null
    created_at: string | null
  }
  stats: {
    users_total: number
    users_active: number
    users_superuser: number
    kbs_count: number
    today_logins: number
    today_actions: number
  }
  login_trend: { date: string; count: number }[]
  recent_audit: AuditLog[]
  timestamp: string
}

export interface DashboardStats {
  users_total: number
  users_active: number
  users_superuser: number
  audit_total: number
  audit_today: number
  login_today: number
  kbs_count: number
}

export interface SystemInfo {
  app_name: string
  version: string
  env: string
  debug: boolean
  database: string
  python: string
  platform: string
  features: Record<string, unknown>
  timestamp: string
}

export type KbRole = 'owner' | 'admin' | 'editor' | 'viewer'

export interface KbItem {
  id: string
  name: string
  description: string | null
  domain_code: string
  template_code: string | null
  owner_id: string
  config: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string | null
  my_role: KbRole | null
  member_count: number
}

export interface KbMemberItem {
  id: string
  kb_id: string
  user_id: string
  username: string | null
  full_name: string | null
  role: KbRole
  status: 'active' | 'invited' | 'removed'
  invited_by: string | null
  expires_at: string | null
  created_at: string
}

export interface KbInvitationItem {
  id: string
  token: string
  kb_id: string
  kb_name: string | null
  inviter_id: string
  inviter_username: string | null
  invitee_id: string
  role: KbRole
  status: 'pending' | 'accepted' | 'revoked'
  expires_at: string | null
  created_at: string
}

export interface Workspace {
  id: string
  name: string
  code: string
  description: string | null
  owner_id: string
  config: Record<string, unknown>
  is_active: boolean
  created_at: string
  my_role: 'owner' | 'admin' | 'editor' | 'viewer' | null
  member_count: number
}

export interface WorkspaceMemberItem {
  id: string
  workspace_id: string
  user_id: string
  username: string | null
  full_name: string | null
  role: 'owner' | 'admin' | 'editor' | 'viewer'
  status: string
  created_at: string
}

export interface GroupItem {
  id: string
  workspace_id: string
  name: string
  code: string
  description: string | null
  created_at: string
  member_count: number
}

export interface GroupMemberItem {
  group_id: string
  user_id: string
  username: string | null
  full_name: string | null
  created_at: string
}

export interface KbGroupGrantItem {
  id: string
  kb_id: string
  group_id: string
  group_name: string
  group_code: string
  workspace_name: string
  role: 'admin' | 'editor' | 'viewer'
  created_at: string
}

export interface ApiKeyItem {
  id: string
  name: string
  key_prefix: string
  scopes: string[]
  expires_at: string | null
  last_used_at: string | null
  created_at: string
  revoked_at: string | null
  secret?: string
}

export interface HealthCheck {
  status: 'healthy' | 'unhealthy' | 'unavailable' | 'degraded' | 'timeout'
  error?: string
  database?: string
}
