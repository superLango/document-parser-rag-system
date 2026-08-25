import { Navigate, Outlet, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { kbApi } from '@/api/modules/kb'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuthStore } from '@/stores/auth'
import { isPending } from '@/stores/rbac'
import type { KbDetailContext } from './KbDetailLayout'

/**
 * 结构化抽取结果独立视图布局。
 *
 * 只渲染抽取页面本身（不含知识库左侧菜单、顶部信息栏），
 * 供一站式对接结果页内嵌及独立 URL 访问。
 * 仍沿用 KbDetailLayout 的 Outlet context（kb / refetch），
 * 以便直接复用 KbExtractionDetailPage。
 */
export default function KbExtractionStandaloneLayout() {
  const { kbId } = useParams<{ kbId: string }>()
  const user = useAuthStore((s) => s.user)
  const { data: kb, isLoading, refetch } = useQuery({
    queryKey: ['kb-detail', kbId],
    queryFn: () => kbApi.get(kbId!),
    enabled: Boolean(kbId),
  })

  if (isPending(user)) {
    return <Navigate to="/pending" replace />
  }

  if (isLoading || !kb) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Skeleton className="h-64 w-3/4 max-w-2xl rounded-2xl" />
      </div>
    )
  }

  return <Outlet context={{ kb, refetch } satisfies KbDetailContext} />
}
