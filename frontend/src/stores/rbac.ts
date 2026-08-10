import type { User } from '@/api/types'

const SUPER_ADMIN_ROLE = 'super_admin'

export function hasPermission(user: User | null, code: string): boolean {
  if (!user) return false
  if (user.is_superuser) return true
  if (user.roles?.some((r) => r.code === SUPER_ADMIN_ROLE)) return true
  return user.permissions?.includes(code) ?? false
}

export function hasAnyPermission(user: User | null, codes: string[]): boolean {
  if (!user) return false
  return codes.some((code) => hasPermission(user, code))
}

export function roleBadgeName(user: User | null): string {
  if (!user) return '未登录'
  const role = user.roles?.[0]
  if (role) return role.name
  return user.is_superuser ? '超级管理员' : '普通用户'
}
