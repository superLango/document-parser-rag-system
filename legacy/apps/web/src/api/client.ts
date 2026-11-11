import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import { safeStorage } from '@/lib/storage'

const ACCESS_KEY = 'access_token'
let authRequired: boolean | null = null

export function setAuthRequired(value: boolean | null): void {
  authRequired = value
}

export class ApiError extends Error {
  code: number
  detail: unknown

  constructor(code: number, message: string, detail: unknown = null) {
    super(message)
    this.code = code
    this.detail = detail
  }
}

const instance = axios.create({
  baseURL: '/v1',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

export function getAccessToken(): string | null {
  return safeStorage.getItem(ACCESS_KEY)
}

export function setTokens(accessToken: string): void {
  safeStorage.setItem(ACCESS_KEY, accessToken)
}

export function clearTokens(): void {
  safeStorage.removeItem(ACCESS_KEY)
}

instance.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

instance.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      clearTokens()
      // 免登录嵌入模式下不要跳登录页，避免 iframe 被重定向后白屏。
      if (authRequired !== false && !window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    const data = error.response?.data as { detail?: unknown } | undefined
    const detail = data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'error' in detail
          ? String((detail as { error?: unknown }).error ?? '请求失败')
          : error.message || '请求失败'
    return Promise.reject(new ApiError(error.response?.status ?? 0, message, detail))
  },
)

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
