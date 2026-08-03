import { http } from '@/api'
import type { Paginated } from '@/api/types'

/** 通知类型（与后端 Notification.type 对齐） */
export type NotificationType =
  | 'task_done'
  | 'task_failed'
  | 'system'
  | 'audit_alert'
  | 'kb_member'

/** 通知条目（对应后端 Notification 序列化） */
export interface Notification {
  id: string
  type: NotificationType | string
  title: string
  content: string | null
  read: boolean
  resource_type: string | null
  resource_id: string | null
  kb_id: string | null
  created_at: string
}

/** 通知中心 API（按 user_id 隔离，对应后端 /notifications） */
export const notificationApi = {
  list(params?: {
    page?: number
    page_size?: number
    unread_only?: boolean
  }): Promise<Paginated<Notification>> {
    return http.get<Paginated<Notification>>('/notifications', { params })
  },

  unreadCount(): Promise<{ count: number }> {
    return http.get<{ count: number }>('/notifications/unread-count')
  },

  markRead(id: string): Promise<unknown> {
    return http.post(`/notifications/${id}/read`)
  },

  markAllRead(): Promise<{ updated: number }> {
    return http.post<{ updated: number }>('/notifications/read-all')
  },

  delete(id: string): Promise<unknown> {
    return http.delete(`/notifications/${id}`)
  },

  clearRead(): Promise<{ deleted: number }> {
    return http.delete<{ deleted: number }>('/notifications/read')
  },

  /** SSE 订阅 URL（供 EventSource 连接，实时推送通知） */
  subscribeUrl(): string {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
    return `${base}/notifications/subscribe`
  },

  /** 管理员公告（超管专属，向全体活跃用户发送系统通知） */
  broadcast(title: string, content?: string): Promise<{ sent_count: number }> {
    return http.post<{ sent_count: number }>('/notifications/broadcast', {
      title,
      content,
    })
  },
}
