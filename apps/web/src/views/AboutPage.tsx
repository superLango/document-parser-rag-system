import { useQuery } from '@tanstack/react-query'
import { CircleCheck, Database, FileSearch, Info, Server, Sparkles, Tag } from 'lucide-react'
import { systemApi } from '@/api/modules/system'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/utils'

const featureLabels: Record<string, string> = {
  auth: '认证',
  rbac: 'RBAC 权限',
  audit_log: '审计日志',
  ip_whitelist: 'IP 白名单',
  registration: '自助注册',
}

export default function AboutPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['system-info'],
    queryFn: systemApi.info,
  })

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="系统" title="关于" description="当前系统信息与技术栈" />

      {isLoading || !data ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Skeleton className="h-52 rounded-2xl" />
          <Skeleton className="h-52 rounded-2xl" />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="animate-fade-up">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                应用信息
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <InfoRow icon={<Tag className="h-4 w-4 text-primary" />} label="应用名称" value={data.app_name} />
              <InfoRow icon={<Server className="h-4 w-4 text-primary" />} label="版本" value={`v${data.version}`} />
              <InfoRow icon={<CircleCheck className="h-4 w-4 text-primary" />} label="运行环境" value={data.env} />
              <InfoRow icon={<Database className="h-4 w-4 text-primary" />} label="主数据库" value={data.database} />
              <InfoRow icon={<Info className="h-4 w-4 text-primary" />} label="信息时间" value={formatDateTime(data.timestamp)} />
            </CardContent>
          </Card>

          <Card className="animate-fade-up" style={{ animationDelay: '80ms' }}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Server className="h-4 w-4 text-primary" />
                运行环境与功能特性
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <InfoRow icon={<Server className="h-4 w-4 text-primary" />} label="Python" value={data.python} />
              <InfoRow icon={<Server className="h-4 w-4 text-primary" />} label="平台" value={data.platform} />
              <div className="flex items-start justify-between gap-3 border-b border-border pb-2">
                <span className="text-muted-foreground">功能特性</span>
                <span className="flex flex-wrap justify-end gap-1.5">
                  {Object.entries(data.features).map(([key, enabled]) => (
                    <Badge key={key} variant={enabled ? 'success' : 'outline'}>
                      {featureLabels[key] ?? key}
                      {enabled ? ' ✓' : ''}
                    </Badge>
                  ))}
                </span>
              </div>
              <div className="flex items-start gap-3 pt-1">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                  <FileSearch className="h-4 w-4" />
                </span>
                <p className="text-xs leading-5 text-muted-foreground">
                  HansonDOC 文档结构化平台 · 面向材料检测领域的文档解析与结构化产品。
                  技术栈：React + FastAPI + PostgreSQL + MinIO + Redis/arq。
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0">
      <span className="flex items-center gap-2 text-muted-foreground">
        {icon}
        {label}
      </span>
      <span className="truncate font-medium">{value}</span>
    </div>
  )
}
