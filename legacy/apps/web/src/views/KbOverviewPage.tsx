import { Link } from 'react-router-dom'
import { ArrowRight, BookOpenText, Braces, CalendarDays, Download, FileText, ListChecks, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { StatCard } from '@/components/StatCard'
import { formatDateTime } from '@/lib/utils'
import { useModule } from './ModuleLayout'

export default function KbOverviewPage() {
  const { module } = useModule()

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="概览"
        title={`${module.name}概览`}
        description={module.summary}
        actions={<Badge variant="success" dot>已上线</Badge>}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="文档"
          value={module.document_count}
          hint="已上传文档"
          icon={FileText}
          tone="blue"
        />
        <StatCard
          title="解析任务"
          value={module.task_count}
          hint="历史任务总数"
          icon={ListChecks}
          tone="amber"
        />
        <StatCard
          title="模块状态"
          value="已上线"
          hint="当前功能模块"
          icon={ShieldCheck}
          tone="violet"
        />
        <StatCard
          title="导出格式"
          value="4 种"
          hint="hanson / JSON / CSV / XLSX"
          icon={Download}
          tone="green"
        />
      </div>

      <Card className="animate-fade-up">
        <CardContent className="flex flex-col gap-4 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium">{module.name}</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {module.description}
            </p>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <CalendarDays className="h-3.5 w-3.5 text-primary" />
                创建于 {module.created_at ? formatDateTime(module.created_at) : '—'}
              </span>
              {module.input_types.map((type) => (
                <Badge key={type} variant="outline">{type}</Badge>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Link to="dictionary">
              <Button variant="secondary">
                <BookOpenText className="h-4 w-4" />
                业务词典
              </Button>
            </Link>
            <Link to="extraction">
              <Button variant="secondary">
                <Braces className="h-4 w-4" />
                结构化抽取
              </Button>
            </Link>
            <Link to="documents">
              <Button>
                文档解析
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
