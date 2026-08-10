import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CalendarDays, FileText, Inbox, Settings2, ShieldCheck, Users } from 'lucide-react'
import { kbApi } from '@/api/modules/kb'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard } from '@/components/StatCard'
import { formatDateTime } from '@/lib/utils'
import { useKbDetail } from './KbDetailLayout'

export default function KbOverviewPage() {
  const { kb } = useKbDetail()
  const navigate = useNavigate()
  const { data: overview, isLoading } = useQuery({
    queryKey: ['kb-overview', kb.id],
    queryFn: () => kbApi.overview(kb.id),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="概览"
        title="知识库概览"
        description="以知识库为隔离边界，文档解析、抽取、图谱与问答将按阶段迁移"
      />

      {isLoading || !overview ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard title="活跃成员" value={overview.stats?.members_active ?? 0} hint="已接受邀请的成员" icon={Users} tone="green" />
            <StatCard title="待接受邀请" value={overview.stats?.pending_invites ?? 0} hint="邀请已发送未接受" icon={Inbox} tone="amber" />
            <StatCard title="文档" value={overview.stats?.documents ?? 0} hint="文档解析阶段启用" icon={FileText} tone="blue" />
            <StatCard title="任务" value={overview.stats?.tasks ?? 0} hint="异步任务阶段启用" icon={Settings2} tone="violet" />
          </div>

          <Card className="animate-fade-up">
            <CardContent className="flex flex-col gap-4 p-6 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <p className="text-sm font-medium">{overview.name}</p>
                <p className="mt-1 text-sm text-muted-foreground">{overview.description || '暂无描述'}</p>
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                    我的角色：{overview.my_role}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <CalendarDays className="h-3.5 w-3.5 text-primary" />
                    创建于 {formatDateTime(overview.created_at)}
                  </span>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button variant="secondary" onClick={() => navigate('members')}>
                  <Users className="h-4 w-4" />
                  成员管理
                </Button>
                <Button onClick={() => navigate('resources')}>
                  资源与配置
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <p className="text-sm font-medium">主流程模块将按阶段开放</p>
              <p className="max-w-lg text-xs leading-5 text-muted-foreground">
                文档解析、向量搜索、结构化抽取、抽取配置·专业术语集、任务列表、知识图谱、
                知识问答将在后续阶段依次迁移；知识库成员与资源/配置已可用。
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
