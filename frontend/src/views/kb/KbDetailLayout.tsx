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
        <div className="flex gap-6">
          <Skeleton className="h-96 w-52 rounded-2xl" />
          <Skeleton className="h-96 flex-1 rounded-2xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 顶部信息栏：返回 + 知识库名称与描述 */}
      <div className="flex items-center gap-4 rounded-2xl border border-emerald-100 bg-gradient-to-r from-emerald-50 via-white to-teal-50 px-4 py-4 shadow-soft sm:px-6">
        <Link
          to="/kb"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-100 bg-white/80 text-primary-strong shadow-soft transition-all hover:shadow-glow"
          title="返回知识库列表"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
          <Database className="h-5 w-5" strokeWidth={1.6} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-lg font-semibold tracking-tight">{kb.name}</h1>
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

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* 左侧知识库内部菜单 */}
        <aside className="shrink-0 lg:w-56">
          <nav className="space-y-1 rounded-2xl border border-border bg-card p-2 shadow-soft">
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
        <div className="min-w-0 flex-1">
          <Outlet context={{ kb, refetch } satisfies KbDetailContext} />
        </div>
      </div>
    </div>
  )
}

export function useKbDetail() {
  return useOutletContext<KbDetailContext>()
}
