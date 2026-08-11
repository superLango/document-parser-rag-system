import type { ComponentType, ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  ChevronDown,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  ShieldCheck,
  User as UserIcon,
  Users,
  FileSearch,
  Database,
  Inbox,
  Building2,
  KeyRound,
  BookOpen,
  Info,
} from 'lucide-react'
import { useAuthStore } from '@/stores/auth'
import { hasPermission, isPending } from '@/stores/rbac'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

const titleMap: Record<string, string> = {
  '/': '工作台',
  '/profile': '个人中心',
  '/pending': '待审批',
  '/kb': '知识库',
  '/kb/invitations': '我的邀请',
  '/workspaces': '工作空间',
  '/api-keys': 'API 密钥',
  '/help': '帮助文档',
  '/about': '关于',
  '/admin/users': '用户管理',
  '/admin/roles': '角色管理',
  '/admin/audit-logs': '审计日志',
}

const eyebrowMap: Record<string, string> = {
  '/': '概览',
  '/profile': '账户',
  '/pending': '账户',
  '/kb': '资源',
  '/kb/invitations': '资源',
  '/workspaces': '组织',
  '/api-keys': '开发者',
  '/help': '系统',
  '/about': '系统',
  '/admin/users': '系统管理',
  '/admin/roles': '系统管理',
  '/admin/audit-logs': '系统管理',
}

function NavItem({ to, label, icon: Icon, end }: {
  to: string
  label: string
  icon: ComponentType<{ className?: string; strokeWidth?: number }>
  end?: boolean
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
          isActive
            ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-soft'
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
          <Icon className="h-4 w-4 shrink-0" strokeWidth={1.9} />
          {label}
        </>
      )}
    </NavLink>
  )
}

function UserMenu() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg p-1 pr-2 text-sm transition-all duration-200 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 text-sm font-semibold text-primary-strong ring-1 ring-emerald-200">
          {(user?.full_name || user?.username || 'U').slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden font-medium sm:inline">{user?.username || '未登录'}</span>
        <ChevronDown
          className={cn('h-3.5 w-3.5 text-muted-foreground transition-transform duration-200', open && 'rotate-180')}
        />
      </button>
      {open ? (
        <div className="animate-scale-in absolute right-0 z-50 mt-2 w-56 rounded-xl border border-border bg-card p-1 shadow-modal">
          <div className="border-b border-border px-3 py-2.5">
            <p className="text-sm font-medium">{user?.full_name || user?.username}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.email || user?.username}</p>
            {user?.is_superuser ? (
              <div className="mt-1.5">
                <Badge variant="success" dot>超级管理员</Badge>
              </div>
            ) : (
              <div className="mt-1.5">
                <Badge variant="secondary">普通用户</Badge>
              </div>
            )}
          </div>
          <button
            type="button"
            className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-muted"
            onClick={() => {
              setOpen(false)
              navigate('/profile')
            }}
          >
            <UserIcon className="h-4 w-4 text-muted-foreground" />
            个人信息
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-destructive transition-colors hover:bg-rose-50"
            onClick={handleLogout}
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      ) : null}
    </div>
  )
}

export default function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const title =
    location.pathname.startsWith('/kb/') && location.pathname !== '/kb' && location.pathname !== '/kb/invitations'
      ? '知识库'
      : titleMap[location.pathname] || 'HansonDOC RAG'
  const eyebrow = eyebrowMap[location.pathname]

  const nav = (
    <nav className="space-y-1 px-3">
      {!isPending(user) ? (
        <>
          <NavItem to="/" label="工作台" icon={LayoutDashboard} end />
          <NavItem to="/kb" label="知识库" icon={Database} end />
          <NavItem to="/kb/invitations" label="我的邀请" icon={Inbox} />
          <NavItem to="/workspaces" label="工作空间" icon={Building2} />
          <NavItem to="/api-keys" label="API 密钥" icon={KeyRound} />
        </>
      ) : null}
      <NavItem to="/profile" label="个人中心" icon={UserIcon} />
      {hasPermission(user, 'user.view') || hasPermission(user, 'role.view') || hasPermission(user, 'audit.view') ? (
        <>
          <p className="mb-1 mt-4 px-3 text-xs font-medium uppercase tracking-widest text-muted-foreground">
            系统管理
          </p>
          {hasPermission(user, 'user.view') ? (
            <NavItem to="/admin/users" label="用户管理" icon={Users} />
          ) : null}
          {hasPermission(user, 'role.view') ? (
            <NavItem to="/admin/roles" label="角色管理" icon={ShieldCheck} />
          ) : null}
          {hasPermission(user, 'audit.view') ? (
            <NavItem to="/admin/audit-logs" label="审计日志" icon={ClipboardList} />
          ) : null}
        </>
      ) : null}
      <p className="mb-1 mt-4 px-3 text-xs font-medium uppercase tracking-widest text-muted-foreground">
        其他
      </p>
      <NavItem to="/help" label="帮助文档" icon={BookOpen} />
      <NavItem to="/about" label="关于" icon={Info} />
    </nav>
  )

  return (
    <div className="min-h-dvh bg-background-soft">
      {/* 侧边栏 */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-sidebar-border bg-gradient-to-b from-sidebar via-white to-sidebar md:flex">
        <div className="relative flex items-center gap-3 overflow-hidden px-5 py-6">
          <div className="aurora aurora-a -left-10 -top-16 h-40 w-40" />
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
            <FileSearch className="h-5 w-5" strokeWidth={1.7} />
            <span className="pulse-dot absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-emerald-300" />
          </div>
          <div className="relative">
            <p className="font-display text-[15px] font-semibold leading-tight">HansonDOC RAG</p>
            <p className="text-xs text-muted-foreground">文档智能解析平台</p>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto py-2">{nav}</div>
        <div className="border-t border-sidebar-border p-4">
          <div className="rounded-xl border border-emerald-100 bg-white/70 p-3 shadow-soft">
            <div className="flex items-center gap-2 text-xs font-medium text-foreground">
              <span className="pulse-dot h-2 w-2 rounded-full bg-success" />
              服务运行中
              <Badge variant="outline" className="ml-auto text-[10px]">v3.0.0</Badge>
            </div>
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <ShieldCheck className="h-3 w-3 text-primary" />
              RBAC · 审计 · 内网部署
            </p>
          </div>
        </div>
      </aside>

      <div className="md:pl-60">
        {/* 顶栏 */}
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border/80 bg-card/85 px-4 backdrop-blur-md sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white md:hidden">
              <FileSearch className="h-4 w-4" />
            </div>
            <div>
              {eyebrow ? (
                <p className="text-[10px] font-medium uppercase tracking-widest text-primary-strong">{eyebrow}</p>
              ) : null}
              <h2 className="font-display text-base font-semibold leading-tight">{title}</h2>
            </div>
          </div>
          <UserMenu />
        </header>
        {/* 移动端导航 */}
        <div className="overflow-x-auto border-b border-border bg-card/85 backdrop-blur-md md:hidden">
          <div className="flex gap-1 px-3 py-2">{nav}</div>
        </div>
        <main className="p-4 sm:p-6 lg:p-8">{children}</main>
      </div>
    </div>
  )
}
