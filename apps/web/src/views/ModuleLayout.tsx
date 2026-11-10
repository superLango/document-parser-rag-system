import { Link, NavLink, Outlet, useOutletContext } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  BookOpenText,
  Braces,
  ClipboardList,
  FileSearch,
  LayoutDashboard,
} from 'lucide-react'
import { modulesApi, type ModuleItem } from '@/api/modules/modules'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'

const navItems = [
  { to: '', label: '概览', icon: LayoutDashboard, end: true },
  { to: 'documents', label: '文档解析', icon: FileSearch },
  { to: 'extraction', label: '结构化抽取', icon: Braces },
  { to: 'dictionary', label: '业务词典', icon: BookOpenText },
  { to: 'tasks', label: '任务列表', icon: ClipboardList },
]

export interface ModuleContext {
  module: ModuleItem
  canManage: boolean
  refetch: () => Promise<unknown>
}

export default function ModuleLayout({ moduleKey }: { moduleKey: string }) {
  const user = useAuthStore((s) => s.user)
  const { data: module, isLoading, isError, refetch } = useQuery({
    queryKey: ['module', moduleKey],
    queryFn: () => modulesApi.get(moduleKey),
  })

  if (isLoading || (!module && !isError)) {
    return (
      <div className="min-h-dvh bg-background-soft p-6">
        <Skeleton className="h-16 w-full rounded-2xl" />
      </div>
    )
  }

  if (!module) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background-soft p-6">
        <div className="rounded-2xl border border-border bg-card p-8 text-center shadow-soft">
          <p className="text-sm font-medium">模块加载失败</p>
          <p className="mt-1 text-xs text-muted-foreground">请稍后重试或返回工作台</p>
          <Link to="/" className="mt-4 inline-block text-sm text-primary hover:underline">
            返回工作台
          </Link>
        </div>
      </div>
    )
  }

  const canManage =
    Boolean(user?.is_superuser) ||
    module.role === 'owner' ||
    module.role === 'editor'

  return (
    <div className="min-h-dvh bg-background-soft">
      {/* 顶部信息栏：返回工作台 + 模块名称/描述 */}
      <header className="sticky top-0 z-30 border-b border-border/80 bg-card/85 backdrop-blur-md">
        <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            to="/"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-100 bg-white/80 text-primary-strong shadow-soft transition-all hover:shadow-glow"
            title="返回工作台"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
            <FileSearch className="h-5 w-5" strokeWidth={1.6} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate font-display text-lg font-semibold tracking-tight">
                {module.name}
              </h1>
              <Badge variant="success" dot>
                已上线
              </Badge>
            </div>
            <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">
              {module.summary}
            </p>
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
        {/* 左侧模块内部菜单 */}
        <aside className="sticky top-16 hidden h-[calc(100dvh-4rem)] w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar p-3 lg:flex">
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
        <main className="min-w-0 flex-1 p-4 sm:p-6 lg:px-7 lg:py-6">
          <div className="mx-auto w-full max-w-[1440px]">
            <Outlet context={{ module, canManage, refetch } satisfies ModuleContext} />
          </div>
        </main>
      </div>
    </div>
  )
}

export function useModule() {
  return useOutletContext<ModuleContext>()
}
