import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  Database,
  GitBranch,
  Inbox,
  LogIn,
  Server,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Users,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { dashboardApi } from '@/api/modules/dashboard'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard } from '@/components/StatCard'
import { cn, formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'

const actionMeta: Record<string, { label: string; icon: typeof Activity }> = {
  'auth.login': { label: '登录', icon: LogIn },
  'auth.register': { label: '注册', icon: UserCheck },
  'auth.update_profile': { label: '更新资料', icon: UserCheck },
  'auth.change_password': { label: '修改密码', icon: ShieldCheck },
  'auth.reset_password': { label: '重置密码', icon: ShieldCheck },
  'user.create': { label: '创建用户', icon: UserCheck },
  'user.update': { label: '更新用户', icon: UserCheck },
  'user.toggle_active': { label: '启停用户', icon: UserCheck },
  'user.toggle_superuser': { label: '切换超管', icon: ShieldCheck },
  'user.reset_password': { label: '超管重置密码', icon: ShieldCheck },
  'user.delete': { label: '删除用户', icon: UserCheck },
}

function actionInfo(action: string) {
  return actionMeta[action] || { label: action, icon: Activity }
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard-overview'],
    queryFn: dashboardApi.overview,
  })

  const today = new Date().toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  })

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="概览"
        title="工作台"
        description={today}
        actions={
          data ? (
            <>
              <Badge variant="success" dot>{data.project.env}</Badge>
              <Badge variant="secondary">v{data.project.version}</Badge>
            </>
          ) : null
        }
      />

      {/* ===== 签名横幅：绿意光晕 + 文档网格 ===== */}
      <div className="relative overflow-hidden rounded-2xl border border-emerald-100 bg-gradient-to-r from-emerald-50 via-white to-teal-50 shadow-soft">
        <div className="doc-grid absolute inset-0" aria-hidden="true" />
        <div className="aurora aurora-a -left-20 -top-24 h-72 w-72" aria-hidden="true" />
        <div className="aurora aurora-b -bottom-28 right-16 h-64 w-64" aria-hidden="true" />
        <div className="relative flex flex-col gap-5 p-6 sm:p-8 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-4">
            <div className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
              <Sparkles className="h-7 w-7" strokeWidth={1.6} />
              <span className="pulse-dot absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-emerald-400" />
            </div>
            <div>
              <p className="mb-1.5 flex items-center gap-2 text-xs font-medium text-emerald-700">
                <span className="pulse-dot h-2 w-2 rounded-full bg-success" />
                服务运行中 · 系统状态正常
              </p>
              <h2 className="font-display text-2xl font-semibold tracking-tight">
                {isLoading || !data
                  ? '加载中...'
                  : `欢迎回来，${data.user.full_name || data.user.username}`}
              </h2>
              <p className="mt-1.5 max-w-xl text-sm leading-6 text-muted-foreground">
                框架与登录权限体系已就绪。知识库、文档解析、抽取、问答等主流程将按迁移计划逐步上线。
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <div className="flex items-center gap-2 rounded-xl border border-emerald-100 bg-white/80 px-3.5 py-2.5 shadow-soft backdrop-blur">
              <Database className="h-4 w-4 text-primary" />
              <div>
                <p className="text-[11px] text-muted-foreground">主数据库</p>
                <p className="font-mono text-xs font-medium">{data?.project.database || 'hanson_doc_rag'}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-emerald-100 bg-white/80 px-3.5 py-2.5 shadow-soft backdrop-blur">
              <LogIn className="h-4 w-4 text-primary" />
              <div>
                <p className="text-[11px] text-muted-foreground">今日登录</p>
                <p className="font-display text-sm font-semibold">{data?.stats.today_logins ?? 0} 次</p>
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-emerald-100 bg-white/80 px-3.5 py-2.5 shadow-soft backdrop-blur">
              <Activity className="h-4 w-4 text-primary" />
              <div>
                <p className="text-[11px] text-muted-foreground">今日操作</p>
                <p className="font-display text-sm font-semibold">{data?.stats.today_actions ?? 0} 次</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ===== 统计卡片 ===== */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            title="用户总数"
            value={data?.stats.users_total ?? 0}
            hint={`活跃 ${data?.stats.users_active ?? 0} 人`}
            icon={Users}
            tone="green"
            delay={0}
          />
          <StatCard
            title="超级管理员"
            value={data?.stats.users_superuser ?? 0}
            hint="系统级最高权限"
            icon={ShieldCheck}
            tone="violet"
            delay={60}
          />
          <StatCard
            title="知识库"
            value={data?.stats.kbs_count ?? 0}
            hint="阶段 1 迁移后启用"
            icon={Database}
            tone="blue"
            delay={120}
          />
          <StatCard
            title="今日操作"
            value={data?.stats.today_actions ?? 0}
            hint="安全审计留痕"
            icon={Activity}
            tone="amber"
            delay={180}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* ===== 登录趋势 ===== */}
        <Card interactive className="animate-fade-up lg:col-span-2" style={{ animationDelay: '120ms' } as CSSProperties}>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-primary" />
              近 7 天登录趋势
            </CardTitle>
            <Badge variant="outline">按审计记录统计</Badge>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-64 rounded-xl" />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data?.login_trend ?? []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                    <defs>
                      <linearGradient id="loginGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10B981" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#10B981" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#DFEBE4" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => (v ? v.slice(5, 10) : '')}
                      tick={{ fontSize: 12, fill: '#64748B' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 12, fill: '#64748B' }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip
                      formatter={(value) => [`${value} 次`, '登录']}
                      labelFormatter={(label) => `日期：${label}`}
                      contentStyle={{
                        borderRadius: 12,
                        border: '1px solid #DFEBE4',
                        fontSize: 12,
                        boxShadow: '0 8px 24px rgba(6,78,59,0.08)',
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="count"
                      stroke="#10B981"
                      strokeWidth={2.5}
                      fill="url(#loginGradient)"
                      activeDot={{ r: 5, fill: '#059669' }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ===== 系统信息 ===== */}
        <Card interactive className="animate-fade-up" style={{ animationDelay: '180ms' } as CSSProperties}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-4 w-4 text-primary" />
              系统信息
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {isLoading || !data ? (
              <Skeleton className="h-48 rounded-xl" />
            ) : (
              <>
                {[
                  { label: '应用名称', value: data.project.app_name },
                  { label: '版本', value: `v${data.project.version}` },
                  { label: '运行环境', value: data.project.env },
                  { label: '主数据库', value: data.project.database },
                  { label: '账号角色', value: data.user.is_superuser ? '超级管理员' : '普通用户' },
                  { label: '最近登录', value: formatDateTime(data.user.last_login_at) },
                  { label: '注册时间', value: formatDateTime(data.user.created_at) },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="group flex items-center justify-between gap-4 border-b border-border pb-2 last:border-0"
                  >
                    <span className="text-muted-foreground">{item.label}</span>
                    <span className="truncate font-medium transition-colors group-hover:text-primary-strong">
                      {item.value}
                    </span>
                  </div>
                ))}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ===== 最近活动 ===== */}
      <Card className="animate-fade-up" style={{ animationDelay: '240ms' } as CSSProperties}>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            最近活动
          </CardTitle>
          {user?.is_superuser ? (
            <Link
              to="/admin/audit-logs"
              className={cn(
                buttonVariants({ variant: 'ghost', size: 'sm' }),
                'text-primary-strong',
              )}
            >
              查看全部
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          ) : null}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-48 w-full rounded-xl" />
          ) : (data?.recent_audit ?? []).length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-primary">
                <Inbox className="h-7 w-7" strokeWidth={1.5} />
              </div>
              <div>
                <p className="text-sm font-medium">还没有活动记录</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  完成登录、更新资料或管理用户后，活动会出现在这里
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              {(data?.recent_audit ?? []).map((log) => {
                const info = actionInfo(log.action)
                return (
                  <div
                    key={log.id}
                    className="group flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors duration-150 hover:bg-emerald-50/60"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                      <info.icon className="h-4 w-4" strokeWidth={1.8} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">
                        {info.label}
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          {log.username || '匿名'}
                        </span>
                      </p>
                      <p className="truncate font-mono text-[11px] text-muted-foreground">
                        {log.path || '—'}
                      </p>
                    </div>
                    <Badge
                      variant={log.status_code && log.status_code >= 400 ? 'destructive' : 'success'}
                      dot
                    >
                      {log.status_code ?? 200}
                    </Badge>
                    <span className="hidden w-36 shrink-0 text-right text-xs text-muted-foreground sm:block">
                      {formatDateTime(log.created_at)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <UserCheck className="h-3.5 w-3.5" />
        当前登录：{user?.username || '—'}
      </p>
    </div>
  )
}
