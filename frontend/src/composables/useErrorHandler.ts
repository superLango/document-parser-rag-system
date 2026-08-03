import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/components/ui/toast'

/**
 * 统一 API 错误处理 composable（阶段 4 - 错误边界）。
 *
 * 在 ``setup`` 中调用获取 ``handleError``，对异步 API 错误（Promise rejection）
 * 进行统一处理：按 HTTP 状态码展示对应 toast，401 自动登出并跳转登录页。
 *
 * 与 ``ErrorBoundary`` 互补：
 * - ``ErrorBoundary`` 捕获组件渲染期的同步错误。
 * - ``useErrorHandler`` 处理异步回调中的错误。
 *
 * 用法：
 *   const { handleError } = useErrorHandler()
 *   try { await api.fetch() }
 *   catch (err) { handleError(err) }
 *
 * 注意：必须在 ``setup`` 上下文调用（依赖 ``useRouter`` / ``useAuthStore``）。
 */
export function useErrorHandler() {
  const router = useRouter()
  const auth = useAuthStore()

  function handleError(err: unknown): void {
    if (!err) return

    // 解析 axios 错误结构
    const status = (err as { response?: { status?: number } }).response?.status
    const message =
      (err as { response?: { data?: { message?: string } } }).response?.data?.message ||
      (err as { message?: string })?.message ||
      '未知错误'

    switch (status) {
      case 401:
        toast.error('登录已过期', '请重新登录')
        auth.logout()
        router.push({
          name: 'Login',
          query: { redirect: router.currentRoute.value.fullPath },
        })
        break
      case 403:
        toast.error('权限不足', message)
        break
      case 404:
        toast.error('未找到', message)
        break
      case 500:
        toast.error('服务器错误', '请稍后重试')
        break
      case undefined:
        // 无 response：网络错误或请求被取消
        toast.error('网络错误', '请检查网络连接')
        break
      default:
        toast.error('操作失败', message)
    }
  }

  return { handleError }
}
