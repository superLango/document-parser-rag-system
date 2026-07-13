import { http } from '@/api'
import type { Task, Paginated } from '@/api/types'

/**
 * 解析任务接口
 */
export const taskApi = {
  // 任务列表
  getList(params?: {
    document_id?: number
    status?: string
    page?: number
    page_size?: number
  }): Promise<Paginated<Task>> {
    return http.get<Paginated<Task>>('/tasks/', { params })
  },

  // 任务详情
  getDetail(id: number): Promise<Task> {
    return http.get<Task>(`/tasks/${id}`)
  },

  // 取消任务
  cancel(id: number): Promise<Task> {
    return http.post<Task>(`/tasks/${id}/cancel`)
  },

  // 重试任务
  retry(id: number): Promise<Task> {
    return http.post<Task>(`/tasks/${id}/retry`)
  },
}
