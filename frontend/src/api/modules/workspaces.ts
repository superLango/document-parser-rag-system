import { http } from '@/api/client'
import type {
  GroupItem,
  GroupMemberItem,
  Paginated,
  Workspace,
  WorkspaceMemberItem,
} from '@/api/types'

export const workspacesApi = {
  list(params?: { page?: number; page_size?: number; keyword?: string }): Promise<Paginated<Workspace>> {
    return http.get<Paginated<Workspace>>('/workspaces', { params })
  },
  create(data: { name: string; code: string; description?: string }): Promise<Workspace> {
    return http.post<Workspace>('/workspaces', data)
  },
  remove(workspaceId: string): Promise<unknown> {
    return http.delete(`/workspaces/${workspaceId}`)
  },
  listMembers(workspaceId: string): Promise<WorkspaceMemberItem[]> {
    return http.get<WorkspaceMemberItem[]>(`/workspaces/${workspaceId}/members`)
  },
  addMember(
    workspaceId: string,
    data: { username: string; role: string },
  ): Promise<{ id: string; user_id: string; role: string }> {
    return http.post(`/workspaces/${workspaceId}/members`, data)
  },
  setMemberRole(workspaceId: string, userId: string, role: string): Promise<unknown> {
    return http.put(`/workspaces/${workspaceId}/members/${userId}`, { role })
  },
  removeMember(workspaceId: string, userId: string): Promise<unknown> {
    return http.delete(`/workspaces/${workspaceId}/members/${userId}`)
  },
  transfer(workspaceId: string, targetUserId: string): Promise<unknown> {
    return http.post(`/workspaces/${workspaceId}/transfer`, { target_user_id: targetUserId })
  },
  listGroups(workspaceId: string): Promise<GroupItem[]> {
    return http.get<GroupItem[]>(`/workspaces/${workspaceId}/groups`)
  },
  createGroup(
    workspaceId: string,
    data: { name: string; code: string; description?: string },
  ): Promise<GroupItem> {
    return http.post(`/workspaces/${workspaceId}/groups`, data)
  },
  removeGroup(workspaceId: string, groupId: string): Promise<unknown> {
    return http.delete(`/workspaces/${workspaceId}/groups/${groupId}`)
  },
  listGroupMembers(workspaceId: string, groupId: string): Promise<GroupMemberItem[]> {
    return http.get<GroupMemberItem[]>(`/workspaces/${workspaceId}/groups/${groupId}/members`)
  },
  addGroupMember(workspaceId: string, groupId: string, username: string): Promise<unknown> {
    return http.post(`/workspaces/${workspaceId}/groups/${groupId}/members`, { username })
  },
  removeGroupMember(workspaceId: string, groupId: string, userId: string): Promise<unknown> {
    return http.delete(`/workspaces/${workspaceId}/groups/${groupId}/members/${userId}`)
  },
}
