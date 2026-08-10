import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, ClipboardList, Eye, Filter, Users } from 'lucide-react'
import { auditApi } from '@/api/modules/audit'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/PageHeader'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard } from '@/components/StatCard'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime } from '@/lib/utils'
import type { AuditLog } from '@/api/types'

export default function AuditLogsPage() {
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [action, setAction] = useState('')
  const [resourceType, setResourceType] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [detail, setDetail] = useState<AuditLog | null>(null)

  const { data: actions } = useQuery({
    queryKey: ['audit-actions'],
    queryFn: auditApi.listActions,
  })

  const { data: stats } = useQuery({
    queryKey: ['audit-stats', 7],
    queryFn: () => auditApi.stats(7),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['audit-logs', page, pageSize, action, resourceType, startDate, endDate],
    queryFn: () =>
      auditApi.list({
        page,
        page_size: pageSize,
        action: action || undefined,
        resource_type: resourceType || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      }),
  })

  const statusVariant = (code: number | null): 'success' | 'destructive' | 'warning' | 'outline' => {
    if (code === null || code < 400) return 'success'
    if (code < 500) return 'warning'
    return 'destructive'
  }

  return (
    <div className="space-y-6">
      <PageHeader title="审计日志" description="系统全部敏感操作留痕，仅超级管理员可见" />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard title="近 7 天操作" value={stats?.total ?? 0} hint="审计记录总数" icon={Activity} tone="green" />
        <StatCard title="操作类型" value={Object.keys(stats?.by_action ?? {}).length} hint="不同动作类型" icon={Filter} tone="blue" />
        <StatCard title="操作用户" value={Object.keys(stats?.by_user ?? {}).length} hint="近 7 天活跃用户" icon={Users} tone="violet" />
        <StatCard title="资源类型" value={Object.keys(stats?.by_resource_type ?? {}).length} hint="覆盖的资源范围" icon={ClipboardList} tone="amber" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-primary" />
            筛选
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Select value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }}>
              <option value="">全部动作</option>
              {(actions ?? []).map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </Select>
            <Select value={resourceType} onChange={(e) => { setResourceType(e.target.value); setPage(1) }}>
              <option value="">全部资源类型</option>
              {Object.keys(stats?.by_resource_type ?? {}).map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </Select>
            <Input type="date" value={startDate} onChange={(e) => { setStartDate(e.target.value); setPage(1) }} />
            <Input type="date" value={endDate} onChange={(e) => { setEndDate(e.target.value); setPage(1) }} />
            <Button
              variant="outline"
              onClick={() => {
                setAction('')
                setResourceType('')
                setStartDate('')
                setEndDate('')
                setPage(1)
              }}
            >
              重置筛选
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>操作者</TableHead>
                <TableHead>动作</TableHead>
                <TableHead>资源类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>IP</TableHead>
                <TableHead>路径</TableHead>
                <TableHead className="text-right">详情</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={8}><Skeleton className="h-16 w-full" /></TableCell>
                </TableRow>
              ) : (data?.items ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-10 text-center text-sm text-muted-foreground">
                    暂无审计记录
                  </TableCell>
                </TableRow>
              ) : (
                (data?.items ?? []).map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="whitespace-nowrap text-xs">{formatDateTime(log.created_at)}</TableCell>
                    <TableCell className="font-medium">{log.username || '匿名'}</TableCell>
                    <TableCell className="text-xs">{log.action}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{log.resource_type || '—'}</TableCell>
                    <TableCell><Badge variant={statusVariant(log.status_code)}>{log.status_code ?? 200}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{log.ip || '—'}</TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">{log.path || '—'}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" title="查看详情" onClick={() => setDetail(log)}>
                        <Eye className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} onPageChange={setPage} />
        </CardContent>
      </Card>

      <Dialog
        open={detail !== null}
        onOpenChange={(open) => { if (!open) setDetail(null) }}
        title="审计详情"
      >
        {detail ? (
          <div className="space-y-3 text-sm">
            {[
              ['操作', detail.action],
              ['操作者', detail.username || '匿名'],
              ['时间', formatDateTime(detail.created_at)],
              ['方法', detail.method || '—'],
              ['路径', detail.path || '—'],
              ['状态码', String(detail.status_code ?? '—')],
              ['IP', detail.ip || '—'],
              ['资源类型', detail.resource_type || '—'],
              ['资源 ID', detail.resource_id || '—'],
              ['trace_id', detail.trace_id || '—'],
              ['User-Agent', detail.user_agent || '—'],
            ].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[90px_1fr] gap-3 border-b border-border pb-2 last:border-0">
                <span className="text-muted-foreground">{label}</span>
                <span className="break-all font-medium">{value}</span>
              </div>
            ))}
            {detail.details ? (
              <div>
                <p className="mb-1 text-muted-foreground">详情</p>
                <pre className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(detail.details, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Dialog>
    </div>
  )
}
