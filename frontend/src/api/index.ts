import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
  type AxiosResponse,
} from 'axios'
import { toast } from '@/components/ui/toast'

/**
 * Axios 实例
 * 统一处理请求/响应拦截、鉴权、错误处理
 *
 * 错误提示使用自研 Toast 系统
 */
const instance: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ---------- 请求拦截器 ----------
instance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 注入 Authorization
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 注入链路追踪 ID
    config.headers['X-Trace-Id'] = generateTraceId()

    return config
  },
  (error) => Promise.reject(error),
)

// ---------- 响应拦截器 ----------
instance.interceptors.response.use(
  (response: AxiosResponse) => {
    // 后端统一响应格式: { code, message, data, trace_id }
    // 解包: axios response.data → 后端响应体 → 取 data 字段
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
      // 标准响应体，返回 data 字段
      return body.data
    }
    // 非标准格式（如二进制下载），直接返回
    return body
  },
  async (error) => {
    const { response } = error
    const path = window.location.pathname
    const isLoginPage = path.includes('/login')
    const isPublicRoute = path.startsWith('/embed/')

    // 请求被取消（AbortController）：静默处理，不弹错误提示
    if (error.code === 'ERR_CANCELED' || error.name === 'CanceledError' || axios.isCancel(error)) {
      return Promise.reject(error)
    }

    // 统一错误提示（Toast 系统）- 先取到消息，避免下方 401 处理后无法读取
    const message =
      response?.data?.message ||
      response?.data?.detail ||
      error.message ||
      '请求失败，请稍后重试'

    // 401 未授权：清除登录态并跳转登录页
    if (response?.status === 401) {
      localStorage.removeItem('token')
      // 公开路由（如 /embed/）不跳转登录页，静默处理
      if (isPublicRoute) {
        return Promise.reject(error)
      }
      if (!isLoginPage) {
        // 非登录页的 401：静默跳转，不重复 toast（避免每个接口都弹）
        window.location.href = '/login'
      } else {
        // 登录页的 401（密码错误等）：必须提示用户，否则静默失败
        toast.error('登录失败', message)
      }
    } else {
      // 非 401：统一提示
      toast.error('请求失败', message)
    }

    return Promise.reject(error)
  },
)

// 生成简易链路追踪 ID
function generateTraceId(): string {
  return `trace-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 类型安全的 HTTP 封装
 * 因响应拦截器已解包 data，此处返回实际数据类型
 */
export const http = {
  get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return instance.get(url, config) as unknown as Promise<T>
  },
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return instance.post(url, data, config) as unknown as Promise<T>
  },
  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return instance.put(url, data, config) as unknown as Promise<T>
  },
  patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return instance.patch(url, data, config) as unknown as Promise<T>
  },
  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return instance.delete(url, config) as unknown as Promise<T>
  },
}

export default instance
