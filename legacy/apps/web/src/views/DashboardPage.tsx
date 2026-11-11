import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  ClipboardList,
  FileSearch,
  FileStack,
  FileText,
  ListChecks,
} from 'lucide-react'
import { http } from '@/api/client'
import { modulesApi } from '@/api/modules/modules'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard } from '@/components/StatCard'
import { formatDateTime, cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'

interface RawTask {
  job_id: string
  document_id: string
  kb_id: string | null
  status: string
  stage: string
  progress: number
  source_name?: string | null
  created_at?: string | null
}

const moduleIcons = {
  standard_split: FileSearch,
  order_parse: ClipboardList,
  certificate_parse: BadgeCheck,
  outsource_report: FileStack,
} as const

const moduleRoutes: Record<string, string> = {
  standard_split: '/standard',
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const [modules, tasks] = await Promise.all([
        modulesApi.list(),
        http.get<RawTask[]>('/tasks', {
          params: { module: 'standard_split', limit: 200, offset: 0 },
        }),
      ])
      const running = tasks.filter((task) => task.status === 'running' || task.status === 'queued')
      const completed = tasks.filter((task) => task.status === 'succeeded' || task.status === 'review')
      const failed = tasks.filter((task) => task.status === 'failed')
      const standard = modules.find((item) => item.key === 'standard_split') ?? null
      return { modules, tasks, running, completed, failed, standard }
    },
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
          <Badge variant="success" dot>
            服务运行中
          </Badge>
        }
      />

      <div className="animate-fade-up relative overflow-hidden rounded-2xl border border-emerald-100 bg-gradient-to-r from-emerald-50 via-white to-teal-50 shadow-soft">
        <div className="doc-grid absolute inset-0" aria-hidden="true" />
        <div className="aurora aurora-a -left-20 -top-24 h-72 w-72" aria-hidden="true" />
        <div className="aurora aurora-b -bottom-28 right-16 h-64 w-64" aria-hidden="true" />
        <div className="relative flex flex-col gap-5 p-6 sm:p-8 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="mb-1.5 flex items-center gap-2 text-xs font-medium text-emerald-700">
              <span className="pulse-dot h-2 w-2 rounded-full bg-success" />
              文档结构化平台
            </p>
            <h2 className="font-display text-2xl font-semibold tracking-tight">
              {isLoading ? '加载中...' : `欢迎回来，${user?.full_name || user?.username || ''}`}
            </h2>
            <p className="mt-1.5 max-w-xl text-sm leading-6 text-muted-foreground">
              选择功能模块进入对应工作区。当前标准拆分已上线，可完成上传、解析、结构化抽取与导出。
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Link to="/standard">
              <Button className="gap-1.5">
                进入标准拆分
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {isLoading
          ? [1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-28 rounded-2xl" />)
          : (data?.modules ?? []).map((module) => {
              const Icon = moduleIcons[module.key as keyof typeof moduleIcons] ?? FileText
              const route = moduleRoutes[module.key]
              return (
                <Card
                  key={module.key}
                  className={cn(
                    'animate-fade-up flex flex-col transition-all duration-200',
                    module.status === 'active' ? 'hover:shadow-glow' : 'opacity-80',
                  )}
                >
                  <CardContent className="flex flex-1 flex-col gap-3 p-5">
                    <div className="flex items-start justify-between gap-2">
                      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-primary-strong">
                        <Icon className="h-5 w-5" strokeWidth={1.7} />
                      </span>
                      <Badge variant={module.status === 'active' ? 'success' : 'outline'}>
                        {module.status === 'active' ? '已上线' : '规划中'}
                      </Badge>
                    </div>
                    <div>
                      <p className="font-display text-base font-semibold">{module.name}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {module.summary}
                      </p>
                    </div>
                    <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                      <span className="text-xs text-muted-foreground">
                        {module.status === 'active'
                          ? `${module.document_count} 份文档 · ${module.task_count} 个任务`
                          : '能力规划中'}
                      </span>
                      {route ? (
                        <Link to={route} className="text-xs font-medium text-primary hover:underline">
                          进入
                        </Link>
                      ) : (
                        <span className="text-xs text-muted-foreground">暂未开放</span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="标准文档"
          value={data?.standard?.document_count ?? 0}
          hint="标准拆分模块"
          icon={FileText}
          tone="blue"
        />
        <StatCard
          title="进行中任务"
          value={data?.running.length ?? 0}
          hint="排队 + 解析中"
          icon={Activity}
          tone="amber"
        />
        <StatCard
          title="解析完成"
          value={data?.completed.length ?? 0}
          hint="成功 + 待查看"
          icon={BadgeCheck}
          tone="violet"
        />
        <StatCard
          title="解析失败"
          value={data?.failed.length ?? 0}
          hint="需要重新解析"
          icon={Activity}
          tone="green"
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="gap-2 text-base">
            <ListChecks className="h-4 w-4 text-primary" />
            最近任务
          </CardTitle>
          <Link to="/standard/tasks" className="text-xs text-primary hover:underline">
            查看全部
          </Link>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-3 p-4">
              <Skeleton className="h-12 w-full rounded-lg" />
              <Skeleton className="h-12 w-full rounded-lg" />
            </div>
          ) : (data?.tasks.length ?? 0) === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              暂无解析任务，先到标准拆分上传文档。
            </p>
          ) : (
            <div className="divide-y divide-border/50">
              {data!.tasks.slice(0, 8).map((task) => (
                <div
                  key={task.job_id}
                  className="flex flex-wrap items-center gap-3 px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {task.source_name || task.document_id}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {task.stage} · {task.progress}%
                      {task.created_at ? ` · ${formatDateTime(task.created_at)}` : ''}
                    </p>
                  </div>
                  <Badge
                    variant={
                      task.status === 'succeeded'
                        ? 'success'
                        : task.status === 'failed'
                          ? 'destructive'
                          : task.status === 'review'
                            ? 'warning'
                            : 'outline'
                    }
                  >
                    {task.status}
                  </Badge>
                  {task.kb_id ? (
                    <Link
                      to={`/standard/extraction/${task.document_id}`}
                      className="text-xs text-primary hover:underline"
                    >
                      查看结果
                    </Link>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
