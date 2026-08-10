import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Braces, Eye, FileText, RefreshCcw, Trash2, UploadCloud } from 'lucide-react'
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import type { DocumentItem } from '@/api/types'
import { useKbDetail } from './KbDetailLayout'

const MAX_SIZE = 100 * 1024 * 1024

const statusMeta: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' | 'secondary' | 'outline' }> = {
  queued: { label: '排队中', variant: 'outline' },
  parsing: { label: '解析中', variant: 'warning' },
  completed: { label: '已完成', variant: 'success' },
  failed: { label: '失败', variant: 'destructive' },
  deleted: { label: '已删除', variant: 'secondary' },
}

const processSteps = ['queued', 'rendering', 'layout', 'ocr', 'rebuild', 'completed']
const processLabels: Record<string, string> = {
  queued: '等待中',
  rendering: '页面渲染',
  layout: '版面分析',
  ocr: 'OCR 识别',
  rebuild: '版面重建',
  completed: '已完成',
  failed: '失败',
}

function progressPercent(processStatus: string): number {
  const idx = processSteps.indexOf(processStatus)
  if (processStatus === 'failed') return 0
  if (idx < 0) return 0
  return Math.round((idx / (processSteps.length - 1)) * 100)
}

export default function KbDocumentsPage() {
  const { kb } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'
  const uploadInputRef = useRef<HTMLInputElement>(null)
  const pageUrlRef = useRef<string | null>(null)

  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null)
  const [previewDoc, setPreviewDoc] = useState<DocumentItem | null>(null)
  const [previewText, setPreviewText] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewPage, setPreviewPage] = useState(1)
  const [previewPageUrl, setPreviewPageUrl] = useState<string | null>(null)
  const [pageLoading, setPageLoading] = useState(false)
  const [layoutDoc, setLayoutDoc] = useState<DocumentItem | null>(null)
  const [layoutData, setLayoutData] = useState<Record<string, unknown> | null>(null)
  const [layoutLoading, setLayoutLoading] = useState(false)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['kb-documents', kb.id, page, search],
    queryFn: () => documentsApi.list(kb.id, { page, page_size: 20, keyword: search || undefined }),
  })
  const list = useMemo(() => data?.items ?? [], [data])

  // 解析中自动轮询（2s），完成后停止
  useEffect(() => {
    const hasActive = list.some((d) => d.status === 'queued' || d.status === 'parsing')
    if (!hasActive) return
    const timer = window.setInterval(() => { void refetch() }, 2000)
    return () => window.clearInterval(timer)
  }, [list, refetch])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['kb-documents'] })
    void refetch()
  }

  function validateFile(file: File): string {
    if (!file.name.toLowerCase().endsWith('.pdf')) return '仅支持 PDF 文件'
    if (file.size <= 0) return '文件为空'
    if (file.size > MAX_SIZE) return '文件超过 100MB 限制'
    return ''
  }

  function handleChooseFile(file: File | undefined) {
    if (!file) return
    const error = validateFile(file)
    setUploadError(error)
    if (error) {
      setUploadFile(null)
      return
    }
    setUploadFile(file)
  }

  function openUploadDialog() {
    setUploadFile(null)
    setUploadError('')
    setUploadOpen(true)
  }

  async function handleUpload() {
    if (!uploadFile) return
    setUploading(true)
    try {
      const result = await documentsApi.upload(kb.id, uploadFile)
      toast('success', '文档已上传', `解析任务已创建（${result.task.task_id.slice(0, 8)}）`)
      setUploadOpen(false)
      setUploadFile(null)
      setPage(1)
      invalidate()
    } catch (err) {
      toast('error', '上传失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setUploading(false)
      if (uploadInputRef.current) uploadInputRef.current.value = ''
    }
  }

  async function loadPreviewPage(doc: DocumentItem, pageIndex: number) {
    setPageLoading(true)
    try {
      const url = await documentsApi.page(kb.id, doc.id, pageIndex)
      if (pageUrlRef.current) URL.revokeObjectURL(pageUrlRef.current)
      pageUrlRef.current = url
      setPreviewPageUrl(url)
      setPreviewPage(pageIndex)
    } catch (err) {
      setPreviewPageUrl(null)
      toast('error', '页面预览失败', err instanceof ApiError ? err.message : '页面可能已清理')
    } finally {
      setPageLoading(false)
    }
  }

  async function openPreview(doc: DocumentItem) {
    setPreviewDoc(doc)
    setPreviewText('')
    setPreviewLoading(true)
    setPreviewPage(1)
    setPreviewPageUrl(null)
    if (pageUrlRef.current) {
      URL.revokeObjectURL(pageUrlRef.current)
      pageUrlRef.current = null
    }
    void loadPreviewPage(doc, 1)
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

  async function openLayout(doc: DocumentItem) {
    setLayoutDoc(doc)
    setLayoutData(null)
    setLayoutLoading(true)
    try {
      const data = await documentsApi.layout(kb.id, doc.id)
      setLayoutData(data)
    } catch (err) {
      setLayoutData(null)
      toast('error', '版面数据加载失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setLayoutLoading(false)
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

  function layoutStats() {
    if (!layoutData) return null
    const pages = (layoutData.pages ?? []) as Array<{ blocks?: Array<{ type: string }> }>
    const typeCount: Record<string, number> = {}
    let blocks = 0
    for (const p of pages) {
      for (const b of p.blocks ?? []) {
        blocks += 1
        typeCount[b.type] = (typeCount[b.type] ?? 0) + 1
      }
    }
    return { pages: pages.length, blocks, typeCount }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="解析"
        title="文档解析"
        description="上传 PDF 自动解析：DocLayout-YOLO 版面分析 + GLM-OCR 识别 + 结构树重建"
        actions={
          canManage ? (
            <Button onClick={openUploadDialog} disabled={uploading} data-testid="open-upload">
              <UploadCloud className="h-4 w-4" />
              上传 PDF
            </Button>
          ) : null
        }
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
            <Table className="min-w-[880px]">
              <TableHeader>
                <TableRow>
                  <TableHead>文档</TableHead>
                  <TableHead>大小</TableHead>
                  <TableHead>上传时间</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((doc) => {
                  const meta = statusMeta[doc.status] ?? { label: doc.status, variant: 'outline' as const }
                  const parsing = doc.status === 'parsing' || doc.status === 'queued'
                  return (
                    <TableRow key={doc.id} data-testid={`doc-row-${doc.id}`}>
                      <TableCell>
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                            <FileText className="h-4 w-4" strokeWidth={1.6} />
                          </span>
                          <div className="min-w-0">
                            <p className="max-w-[260px] truncate text-sm font-medium">{doc.filename}</p>
                            <p className="text-xs text-muted-foreground">{doc.page_count > 0 ? `${doc.page_count} 页` : '未解析'}</p>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{(doc.file_size / 1024).toFixed(1)} KB</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatDateTime(doc.created_at)}</TableCell>
                      <TableCell>
                        <div className="w-36">
                          <Badge variant={meta.variant}>{meta.label}</Badge>
                          {parsing ? (
                            <div className="mt-2 space-y-1">
                              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500 transition-all duration-500"
                                  style={{ width: `${progressPercent(doc.process_status)}%` }}
                                  data-testid={`progress-${doc.id}`}
                                />
                              </div>
                              <p className="text-[11px] text-muted-foreground">{processLabels[doc.process_status] ?? doc.process_status}</p>
                            </div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1">
                          {doc.status === 'completed' ? (
                            <>
                              <Button variant="ghost" size="icon" title="查看 Markdown 产物" data-testid={`preview-${doc.id}`} onClick={() => void openPreview(doc)}>
                                <Eye className="h-4 w-4" />
                              </Button>
                              <Button variant="ghost" size="icon" title="查看版面结构" data-testid={`layout-${doc.id}`} onClick={() => void openLayout(doc)}>
                                <Braces className="h-4 w-4" />
                              </Button>
                            </>
                          ) : null}
                          {canManage && doc.status !== 'parsing' && doc.status !== 'queued' && doc.status !== 'deleted' ? (
                            <Button variant="ghost" size="icon" title="重新解析" data-testid={`reparse-${doc.id}`} onClick={() => void handleReparse(doc)}>
                              <RefreshCcw className="h-4 w-4" />
                            </Button>
                          ) : null}
                          {canManage ? (
                            <Button variant="ghost" size="icon" title="删除" className="text-destructive" data-testid={`delete-${doc.id}`} onClick={() => setDeleteTarget(doc)}>
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
          {list.length > 0 ? (
            <div className="border-t border-border px-4 py-3">
              <Pagination page={page} pageSize={20} total={data?.total ?? 0} onPageChange={setPage} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* 上传弹窗 */}
      <Dialog
        open={uploadOpen}
        onOpenChange={(open) => { if (!open) setUploadOpen(false) }}
        title="上传 PDF"
        description="支持 PDF，单文件不超过 100MB；上传后自动创建解析任务"
      >
        <input
          ref={uploadInputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          data-testid="upload-input"
          onChange={(e) => { handleChooseFile(e.target.files?.[0]); e.target.value = '' }}
        />
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 p-8 text-center">
          {uploadFile ? (
            <>
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-primary shadow-soft">
                <FileText className="h-6 w-6" strokeWidth={1.6} />
              </span>
              <div>
                <p className="text-sm font-medium" data-testid="upload-filename">{uploadFile.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">{(uploadFile.size / 1024 / 1024).toFixed(2)} MB</p>
              </div>
            </>
          ) : (
            <>
              <UploadCloud className="h-10 w-10 text-primary" strokeWidth={1.4} />
              <p className="text-sm text-muted-foreground">点击选择要上传的 PDF 文件</p>
            </>
          )}
          {!uploadFile ? (
            <Button variant="secondary" onClick={() => uploadInputRef.current?.click()}>选择文件</Button>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => { setUploadFile(null); setUploadError('') }}>重新选择</Button>
          )}
          {uploadError ? <p className="text-xs text-destructive" data-testid="upload-error">{uploadError}</p> : null}
        </div>
        <DialogFooter
          uploading={uploading}
          disabled={!uploadFile || Boolean(uploadError)}
          onCancel={() => setUploadOpen(false)}
          onUpload={() => void handleUpload()}
        />
      </Dialog>

      {/* 产物预览 */}
      <Dialog
        open={previewDoc !== null}
        onOpenChange={(open) => { if (!open) setPreviewDoc(null) }}
        title="Markdown 产物"
        description={previewDoc ? `${previewDoc.filename} · ${previewDoc.page_count ?? 0} 页` : undefined}
        className="max-w-3xl"
      >
        <div className="mb-4 rounded-xl border border-border bg-muted/40 p-3">
          {pageLoading ? (
            <Skeleton className="h-52 w-full rounded-lg" />
          ) : previewPageUrl ? (
            <img
              src={previewPageUrl}
              alt={`第 ${previewPage} 页预览`}
              data-testid="page-preview"
              className="mx-auto max-h-72 rounded-lg border border-border bg-white object-contain"
            />
          ) : (
            <p className="py-10 text-center text-xs text-muted-foreground">页面预览不可用（可能已清理）</p>
          )}
          <div className="mt-3 flex items-center justify-between">
            <Button size="sm" variant="outline" disabled={!previewDoc || previewPage <= 1 || pageLoading} onClick={() => previewDoc && void loadPreviewPage(previewDoc, previewPage - 1)}>
              上一页
            </Button>
            <span className="text-xs text-muted-foreground">第 {previewPage} / {previewDoc?.page_count ?? 0} 页</span>
            <Button size="sm" variant="outline" disabled={!previewDoc || previewPage >= (previewDoc.page_count ?? 0) || pageLoading} onClick={() => previewDoc && void loadPreviewPage(previewDoc, previewPage + 1)}>
              下一页
            </Button>
          </div>
        </div>
        {previewLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">产物加载中...</div>
        ) : previewText ? (
          <pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap rounded-xl bg-muted/60 p-4 font-mono text-xs leading-relaxed text-foreground">
            {previewText}
          </pre>
        ) : (
          <div className="py-10 text-center text-sm text-muted-foreground">暂无产物内容</div>
        )}
        <div className="mt-4 flex justify-end">
          {previewDoc ? (
            <Button size="sm" variant="outline" data-testid="open-layout" onClick={() => { void openLayout(previewDoc) }}>
              <Braces className="h-4 w-4" />
              查看版面
            </Button>
          ) : null}
        </div>
      </Dialog>

      {/* 版面调试视图 */}
      <Dialog
        open={layoutDoc !== null}
        onOpenChange={(open) => { if (!open) setLayoutDoc(null) }}
        title="版面结构"
        description={layoutDoc ? `${layoutDoc.filename} · layout.json` : undefined}
        className="max-w-3xl"
      >
        {layoutLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">版面数据加载中...</div>
        ) : layoutData ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="页数" value={String(layoutStats()?.pages ?? 0)} />
              <Stat label="版面块" value={String(layoutStats()?.blocks ?? 0)} />
              <Stat label="引擎" value={String(layoutData.layout_engine ?? '—')} />
              <Stat label="Schema" value={String(layoutData.schema_version ?? '—')} />
            </div>
            {layoutStats() && Object.keys(layoutStats()!.typeCount).length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {Object.entries(layoutStats()!.typeCount).map(([type, count]) => (
                  <Badge key={type} variant="secondary">{type}: {count}</Badge>
                ))}
              </div>
            ) : null}
            <pre className="max-h-[46vh] overflow-auto whitespace-pre-wrap rounded-xl bg-muted/60 p-4 font-mono text-[11px] leading-relaxed text-foreground" data-testid="layout-json">
              {JSON.stringify(layoutData, null, 2)}
            </pre>
          </div>
        ) : (
          <div className="py-10 text-center text-sm text-muted-foreground">版面数据不可用</div>
        )}
      </Dialog>

      {/* 删除确认 */}
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

function DialogFooter({ uploading, disabled, onCancel, onUpload }: { uploading: boolean; disabled: boolean; onCancel: () => void; onUpload: () => void }) {
  return (
    <div className="mt-4 flex justify-end gap-2">
      <Button variant="outline" onClick={onCancel} disabled={uploading}>取消</Button>
      <Button onClick={onUpload} disabled={disabled || uploading} data-testid="confirm-upload">
        <UploadCloud className="h-4 w-4" />
        {uploading ? '上传中...' : '确认上传'}
      </Button>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-muted/40 px-3 py-2">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 truncate text-sm font-semibold">{value}</p>
    </div>
  )
}
