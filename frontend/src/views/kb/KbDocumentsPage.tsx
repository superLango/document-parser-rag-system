import { useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, FileText, RefreshCcw, Trash2, UploadCloud } from 'lucide-react'
import { documentsApi } from '@/api/modules/documents'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/PageHeader'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import type { DocumentItem } from '@/api/types'
import { useKbDetail } from './KbDetailLayout'

const statusMeta: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' | 'secondary' | 'outline' }> = {
  queued: { label: '排队中', variant: 'outline' },
  parsing: { label: '解析中', variant: 'warning' },
  completed: { label: '已完成', variant: 'success' },
  failed: { label: '失败', variant: 'destructive' },
  deleted: { label: '已删除', variant: 'secondary' },
}

const processLabels: Record<string, string> = {
  queued: '等待中',
  rendering: '页面渲染',
  layout: '版面分析',
  ocr: 'OCR 识别',
  rebuild: '版面重建',
  completed: '已完成',
  failed: '失败',
}

export default function KbDocumentsPage() {
  const { kb } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'
  const fileRef = useRef<HTMLInputElement>(null)

  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [uploading, setUploading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null)
  const [previewDoc, setPreviewDoc] = useState<DocumentItem | null>(null)
  const [previewText, setPreviewText] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['kb-documents', kb.id, page, search],
    queryFn: () => documentsApi.list(kb.id, { page, page_size: 20, keyword: search || undefined }),
  })
  const list = useMemo(() => data?.items ?? [], [data])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['kb-documents'] })
    void refetch()
  }

  async function handleFile(file: File | undefined) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast('error', '仅支持 PDF 文件')
      return
    }
    if (file.size > 100 * 1024 * 1024) {
      toast('error', '文件超过 100MB 限制')
      return
    }
    setUploading(true)
    try {
      const result = await documentsApi.upload(kb.id, file)
      toast('success', '文档已上传', `解析任务已创建（${result.task.task_id.slice(0, 8)}）`)
      setPage(1)
      invalidate()
      // 同步执行器模式下任务很快完成，稍后刷新状态
      setTimeout(() => {
        void refetch()
      }, 1500)
    } catch (err) {
      toast('error', '上传失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function openPreview(doc: DocumentItem) {
    setPreviewDoc(doc)
    setPreviewText('')
    setPreviewLoading(true)
    try {
      const text = await documentsApi.markdown(kb.id, doc.id)
      setPreviewText(text)
    } catch (err) {
      setPreviewText('')
      toast('error', '预览失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleReparse(doc: DocumentItem) {
    if (doc.status === 'parsing' || doc.status === 'queued') {
      toast('error', '文档正在解析中', '请等待当前任务结束后再重新解析')
      return
    }
    try {
      await documentsApi.reparse(kb.id, doc.id)
      toast('success', '重新解析已启动', `已为「${doc.filename}」创建新任务`)
      invalidate()
      setTimeout(() => {
        void refetch()
      }, 1500)
    } catch (err) {
      toast('error', '重新解析失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await documentsApi.remove(kb.id, deleteTarget.id)
      toast('success', '文档已删除', `已删除「${deleteTarget.filename}」`)
      setDeleteTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="解析"
        title="文档解析"
        description="上传 PDF 创建解析任务（当前为 Phase 1：状态与任务骨架，真实解析后续阶段接入）"
        actions={
          canManage ? (
            <Button onClick={() => fileRef.current?.click()} disabled={uploading}>
              <UploadCloud className="h-4 w-4" />
              {uploading ? '上传中...' : '上传 PDF'}
            </Button>
          ) : null
        }
      />
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,application/pdf"
        className="hidden"
        onChange={(e) => void handleFile(e.target.files?.[0])}
      />

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <form
              className="flex flex-1 gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setPage(1)
                setSearch(keyword)
              }}
            >
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索文件名"
              />
              <Button type="submit" variant="secondary">搜索</Button>
            </form>
            <Button variant="ghost" size="icon" onClick={() => invalidate()} disabled={isFetching} aria-label="刷新">
              <RefreshCcw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6"><Skeleton className="h-48 w-full rounded-xl" /></div>
          ) : list.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-primary">
                <FileText className="h-7 w-7" strokeWidth={1.5} />
              </span>
              <p className="text-sm font-medium">暂无文档</p>
              <p className="text-xs text-muted-foreground">上传 PDF 后自动创建解析任务</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {list.map((doc) => {
                const meta = statusMeta[doc.status] ?? { label: doc.status, variant: 'outline' as const }
                return (
                  <div key={doc.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                      <FileText className="h-5 w-5" strokeWidth={1.6} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{doc.filename}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span>{(doc.file_size / 1024).toFixed(1)} KB</span>
                        <span>上传于 {formatDateTime(doc.created_at)}</span>
                        {doc.status === 'parsing' || doc.status === 'queued' ? (
                          <span>{processLabels[doc.process_status] ?? doc.process_status}</span>
                        ) : null}
                      </p>
                    </div>
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                    <div className="flex shrink-0 items-center gap-1">
                      {doc.status === 'completed' ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          title="查看 Markdown 产物"
                          data-testid={`preview-${doc.id}`}
                          onClick={() => void openPreview(doc)}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                      ) : null}
                      {canManage && doc.status !== 'parsing' && doc.status !== 'queued' && doc.status !== 'deleted' ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          title="重新解析"
                          data-testid={`reparse-${doc.id}`}
                          onClick={() => void handleReparse(doc)}
                        >
                          <RefreshCcw className="h-4 w-4" />
                        </Button>
                      ) : null}
                      {canManage ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          title="删除"
                          className="text-destructive"
                          onClick={() => setDeleteTarget(doc)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      ) : null}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          {list.length > 0 ? (
            <Pagination page={page} pageSize={20} total={data?.total ?? 0} onPageChange={setPage} />
          ) : null}
        </CardContent>
      </Card>

      <Dialog
        open={previewDoc !== null}
        onOpenChange={(open) => { if (!open) setPreviewDoc(null) }}
        title="Markdown 产物"
        description={previewDoc ? `${previewDoc.filename} · ${previewDoc.page_count ?? 0} 页` : undefined}
        className="max-w-3xl"
      >
        {previewLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">产物加载中...</div>
        ) : previewText ? (
          <pre className="max-h-[58vh] overflow-auto whitespace-pre-wrap rounded-xl bg-muted/60 p-4 font-mono text-xs leading-relaxed text-foreground">
            {previewText}
          </pre>
        ) : (
          <div className="py-10 text-center text-sm text-muted-foreground">暂无产物内容</div>
        )}
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="删除文档"
        description={`确认删除「${deleteTarget?.filename ?? ''}」？删除后文档与解析产物不可恢复。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={() => void handleDelete()}>确认删除</Button>
          </>
        }
      />
    </div>
  )
}
