import { Link, Navigate, NavLink, Outlet, useOutletContext, useParams } from 'react-router-dom'
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
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { isPending } from '@/stores/rbac'
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
  const user = useAuthStore((s) => s.user)
  const { data: kb, isLoading, refetch } = useQuery({
    queryKey: ['kb-detail', kbId],
    queryFn: () => kbApi.get(kbId!),
    enabled: Boolean(kbId),
  })

  if (isPending(user)) {
    return <Navigate to="/pending" replace />
  }

  return (
    <div className="min-h-dvh bg-background-soft">
      {/* 顶部信息栏：返回外部 + 知识库名称/描述（替换外部导航栏） */}
      <header className="sticky top-0 z-30 border-b border-border/80 bg-card/85 backdrop-blur-md">
        <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            to="/kb"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-100 bg-white/80 text-primary-strong shadow-soft transition-all hover:shadow-glow"
            title="返回知识库列表（外部导航）"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
            <Database className="h-5 w-5" strokeWidth={1.6} />
          </span>
          <div className="min-w-0 flex-1">
            {isLoading || !kb ? (
              <Skeleton className="h-6 w-64 max-w-full rounded-lg" />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="truncate font-display text-lg font-semibold tracking-tight">{kb.name}</h1>
                  <Badge variant={kb.my_role === 'owner' ? 'success' : 'outline'}>
                    {kb.my_role ? roleLabels[kb.my_role] ?? kb.my_role : '—'}
                  </Badge>
                  <Badge variant="secondary"><Users className="h-3 w-3" /> {kb.member_count} 人</Badge>
                </div>
                <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">
                  {kb.description || '暂无描述'}
                </p>
              </>
            )}
          </div>
        </div>
        {/* 移动端横向菜单 */}
        <div className="flex gap-1 overflow-x-auto border-t border-border px-3 py-1.5 lg:hidden">
          {navItems.map((item) => (
            <NavLink
              key={item.to || 'overview'}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )
              }
            >
              <item.icon className="h-4 w-4" strokeWidth={1.8} />
              {item.label}
            </NavLink>
          ))}
        </div>
      </header>

      <div className="flex">
        {/* 左侧知识库内部菜单（替换外部侧栏） */}
        <aside className="sticky top-[104px] hidden h-[calc(100dvh-104px)] w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar p-3 lg:flex">
          <nav className="space-y-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to || 'overview'}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    'group relative flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
                    isActive
                      ? 'bg-accent text-accent-foreground shadow-soft'
                      : 'text-sidebar-foreground hover:bg-muted hover:pl-4',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={cn(
                        'absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary transition-all duration-200',
                        isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-40',
                      )}
                    />
                    <item.icon className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                    {item.label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </aside>

        {/* 内容区 */}
        <main className="min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
          {isLoading || !kb ? (
            <div className="space-y-6">
              <Skeleton className="h-64 w-full rounded-2xl" />
              <Skeleton className="h-40 w-full rounded-2xl" />
            </div>
          ) : (
            <Outlet context={{ kb, refetch } satisfies KbDetailContext} />
          )}
        </main>
      </div>
    </div>
  )
}

export function useKbDetail() {
  return useOutletContext<KbDetailContext>()
}
