import { http } from '@/api/client'
import type { PermissionItem, Role } from '@/api/types'

export const rolesApi = {
  list(): Promise<Role[]> {
    return http.get<Role[]>('/roles')
  },
  listPermissions(): Promise<PermissionItem[]> {
    return http.get<PermissionItem[]>('/roles/permissions')
  },
  get(roleId: string): Promise<Role> {
    return http.get<Role>(`/roles/${roleId}`)
  },
  getPermissions(roleId: string): Promise<string[]> {
    return http.get<string[]>(`/roles/${roleId}/permissions`)
  },
  create(data: { code: string; name: string; description?: string }): Promise<Role> {
    return http.post<Role>('/roles', data)
  },
  update(
    roleId: string,
    data: { name?: string; description?: string },
  ): Promise<Role> {
    return http.put<Role>(`/roles/${roleId}`, data)
  },
  setPermissions(roleId: string, permissionCodes: string[]): Promise<string[]> {
    return http.put<string[]>(`/roles/${roleId}/permissions`, {
      permission_codes: permissionCodes,
    })
  },
  remove(roleId: string): Promise<unknown> {
    return http.delete(`/roles/${roleId}`)
  },
}
