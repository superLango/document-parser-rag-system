import { http } from '@/api'
import type {
  Task,
  TaskCreateRequest,
  TaskSubmitResponse,
  Paginated,
} from '@/api/types'

/**
 * 解析任务接口
 */
export const taskApi = {
  // 任务列表
  getList(params?: {
    document_id?: string
    status?: string
    page?: number
    page_size?: number
  }): Promise<Paginated<Task>> {
    return http.get<Paginated<Task>>('/tasks/', { params })
  },

  // 任务详情
  getDetail(id: string): Promise<Task> {
    return http.get<Task>(`/tasks/${id}`)
  },

  // 提交解析任务
  submit(data: TaskCreateRequest): Promise<TaskSubmitResponse> {
    return http.post<TaskSubmitResponse>('/tasks/', data)
  },

  // 重试任务
  retry(id: string): Promise<TaskSubmitResponse> {
    return http.post<TaskSubmitResponse>(`/tasks/${id}/retry`)
  },

  // 获取任务进度 SSE 流地址（供 fetch 消费，需带鉴权头）
  getStreamUrl(id: string): string {
    return `/api/v1/tasks/${id}/stream`
  },
}
