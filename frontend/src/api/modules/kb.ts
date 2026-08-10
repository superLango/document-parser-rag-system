import { http } from '@/api/client'
import type {
  KbInvitationItem,
  KbItem,
  KbMemberItem,
  KbRole,
  Paginated,
} from '@/api/types'

export const kbApi = {
  list(params?: {
    page?: number
    page_size?: number
    keyword?: string
  }): Promise<Paginated<KbItem>> {
    return http.get<Paginated<KbItem>>('/kb', { params })
  },
  create(data: {
    name: string
    description?: string
    domain_code?: string
    template_code?: string
  }): Promise<KbItem> {
    return http.post<KbItem>('/kb', data)
  },
  get(kbId: string): Promise<KbItem> {
    return http.get<KbItem>(`/kb/${kbId}`)
  },
  update(
    kbId: string,
    data: { name?: string; description?: string; domain_code?: string },
  ): Promise<KbItem> {
    return http.put<KbItem>(`/kb/${kbId}`, data)
  },
  remove(kbId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}`)
  },
  listMembers(kbId: string): Promise<KbMemberItem[]> {
    return http.get<KbMemberItem[]>(`/kb/${kbId}/members`)
  },
  invite(
    kbId: string,
    data: { username: string; role: KbRole; expires_at?: string },
  ): Promise<{ id: string; token: string; role: KbRole; expires_at: string | null }> {
    return http.post(`/kb/${kbId}/invitations`, data)
  },
  revokeInvitation(kbId: string, invitationId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/invitations/${invitationId}`)
  },
  myInvitations(): Promise<KbInvitationItem[]> {
    return http.get<KbInvitationItem[]>('/kb/invitations/mine')
  },
  acceptInvitation(token: string): Promise<{
    kb_id: string
    kb_name: string
    role: KbRole
    status: string
  }> {
    return http.post(`/kb/invitations/${token}/accept`)
  },
  setMemberRole(
    kbId: string,
    userId: string,
    role: KbRole,
  ): Promise<unknown> {
    return http.put(`/kb/${kbId}/members/${userId}`, { role })
  },
  removeMember(kbId: string, userId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/members/${userId}`)
  },
  transfer(kbId: string, targetUserId: string): Promise<unknown> {
    return http.post(`/kb/${kbId}/transfer`, { target_user_id: targetUserId })
  },
}
