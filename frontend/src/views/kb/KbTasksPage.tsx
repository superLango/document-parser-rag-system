import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ClipboardList, RefreshCcw } from 'lucide-react'
import { documentsApi } from '@/api/modules/documents'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDateTime } from '@/lib/utils'
import { useKbDetail } from './KbDetailLayout'

const taskStatusMeta: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' | 'secondary' | 'outline' }> = {
  queued: { label: '排队中', variant: 'outline' },
  running: { label: '运行中', variant: 'warning' },
  completed: { label: '已完成', variant: 'success' },
  failed: { label: '失败', variant: 'destructive' },
}

function checkpointSummary(checkpoint: Record<string, unknown>): string {
  const stages = checkpoint?.stages
  if (Array.isArray(stages) && stages.length > 0) {
    return stages.join(' → ')
  }
  return '—'
}

export default function KbTasksPage() {
  const { kb } = useKbDetail()
  const [page, setPage] = useState(1)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['kb-tasks', kb.id, page],
    queryFn: () => documentsApi.tasks(kb.id, { page, page_size: 20 }),
  })
  const items = data?.items ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="任务"
        title="任务列表"
        description="文档解析任务状态、尝试次数与断点进度"
        actions={
          <Button variant="ghost" size="icon" onClick={() => void refetch()} disabled={isFetching} aria-label="刷新任务">
            <RefreshCcw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
          </Button>
        }
      />
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6"><Skeleton className="h-40 w-full rounded-xl" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-primary">
                <ClipboardList className="h-7 w-7" strokeWidth={1.5} />
              </span>
              <p className="text-sm font-medium">暂无解析任务</p>
              <p className="text-xs text-muted-foreground">上传 PDF 后将在此展示任务</p>
            </div>
          ) : (
            <Table className="min-w-[860px]">
              <TableHeader>
                <TableRow>
                  <TableHead>文档</TableHead>
                  <TableHead>任务 ID</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>阶段进度</TableHead>
                  <TableHead>尝试</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead>错误</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((task) => {
                  const meta = taskStatusMeta[task.status] ?? { label: task.status, variant: 'outline' as const }
                  return (
                    <TableRow key={task.id} data-testid={`task-row-${task.task_id}`}>
                      <TableCell className="max-w-[220px] truncate text-xs font-medium">{task.filename ?? '—'}</TableCell>
                      <TableCell className="font-mono text-xs">{task.task_id.slice(0, 12)}</TableCell>
                      <TableCell><Badge variant={meta.variant}>{meta.label}</Badge></TableCell>
                      <TableCell className="text-xs text-muted-foreground">{checkpointSummary(task.checkpoint ?? {})}</TableCell>
                      <TableCell className="text-xs">{task.attempts}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatDateTime(task.created_at)}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs text-destructive">{String(task.error?.message ?? '—')}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
          {items.length > 0 ? (
            <div className="border-t border-border px-4 py-3">
              <Pagination page={page} pageSize={20} total={data?.total ?? 0} onPageChange={setPage} />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
