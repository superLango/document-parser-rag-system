import { Link, NavLink, Outlet, useOutletContext, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  BookOpenText,
  Braces,
  ClipboardList,
  Database,
  FileSearch,
  GitBranch,
  LayoutDashboard,
  MessageSquareText,
  SearchCode,
  Settings2,
  Users,
} from 'lucide-react'
import { kbApi } from '@/api/modules/kb'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { KbItem } from '@/api/types'

const roleLabels: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

const navItems = [
  { to: '', label: '概览', icon: LayoutDashboard, end: true },
  { to: 'documents', label: '文档解析', icon: FileSearch },
  { to: 'vector-search', label: '向量搜索', icon: SearchCode },
  { to: 'extraction', label: '结构化抽取', icon: Braces },
  { to: 'extraction-config', label: '抽取配置·专业术语集', icon: BookOpenText },
  { to: 'tasks', label: '任务列表', icon: ClipboardList },
  { to: 'graph', label: '知识图谱', icon: GitBranch },
  { to: 'qa', label: '知识问答', icon: MessageSquareText },
  { to: 'resources', label: '资源与配置', icon: Settings2 },
  { to: 'members', label: '知识库成员', icon: Users },
]

export interface KbDetailContext {
  kb: KbItem
  refetch: () => Promise<unknown>
}

export default function KbDetailLayout() {
  const { kbId } = useParams<{ kbId: string }>()
  const { data: kb, isLoading, refetch } = useQuery({
    queryKey: ['kb-detail', kbId],
    queryFn: () => kbApi.get(kbId!),
    enabled: Boolean(kbId),
  })

  if (isLoading || !kb) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-20 w-full rounded-2xl" />
        <Skeleton className="h-12 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Card className="relative overflow-hidden rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50 via-white to-teal-50 shadow-soft">
        <div className="doc-grid absolute inset-0" aria-hidden="true" />
        <div className="aurora aurora-a -right-16 -top-24 h-56 w-56" aria-hidden="true" />
        <CardContent className="relative flex flex-col gap-4 p-5 sm:p-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-4">
            <Link
              to="/kb"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-100 bg-white/80 text-primary-strong shadow-soft transition-all hover:shadow-glow"
              title="返回知识库列表"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
              <Database className="h-6 w-6" strokeWidth={1.6} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-display text-xl font-semibold tracking-tight">{kb.name}</h1>
                <Badge variant={kb.my_role === 'owner' ? 'success' : 'outline'}>
                  {kb.my_role ? roleLabels[kb.my_role] ?? kb.my_role : '—'}
                </Badge>
                <Badge variant="secondary"><Users className="h-3 w-3" /> {kb.member_count} 人</Badge>
              </div>
              <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
                {kb.description || '暂无描述'}
              </p>
            </div>
          </div>
          <p className="shrink-0 text-xs text-muted-foreground">
            以知识库为隔离边界的垂直领域文档智能产品
          </p>
        </CardContent>
      </Card>

      <div className="flex gap-1 overflow-x-auto border-b border-border pb-0">
        {navItems.map((item) => (
          <NavLink
            key={item.to || 'overview'}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'flex shrink-0 items-center gap-1.5 rounded-t-lg border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary bg-accent/60 text-accent-foreground'
                  : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
              )
            }
          >
            <item.icon className="h-4 w-4" strokeWidth={1.8} />
            {item.label}
          </NavLink>
        ))}
      </div>

      <Outlet context={{ kb, refetch } satisfies KbDetailContext} />
    </div>
  )
}

export function useKbDetail() {
  return useOutletContext<KbDetailContext>()
}
