import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, FileText, Loader2, PlayCircle, RefreshCcw, Trash2, UploadCloud } from 'lucide-react'
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
import {
  DOCUMENT_STATUS_META,
  PROCESS_LABELS,
  TERMINAL_STATUSES,
  pageProgressText,
  progressPercentForDoc,
} from '@/lib/documentStatus'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import type { DocumentItem } from '@/api/types'
import { useKbDetail } from './KbDetailLayout'

const MAX_SIZE = 100 * 1024 * 1024
const POLL_INTERVAL = 1500

export default function KbDocumentsPage() {
  const { kb } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'
  const uploadInputRef = useRef<HTMLInputElement>(null)

  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null)
  const [runningIds, setRunningIds] = useState<Record<string, boolean>>({})
  const sawNonTerminalRef = useRef<Record<string, boolean>>({})

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['kb-documents', kb.id, page, search],
    queryFn: () => documentsApi.list(kb.id, { page, page_size: 20, keyword: search || undefined }),
  })
  const list = useMemo(() => data?.items ?? [], [data])
  const runningList = useMemo(() => Object.keys(runningIds), [runningIds])
  const hasActive = runningList.length > 0 || list.some((d) => d.status === 'parsing')

  // 轮询：有进行中/已触发任务时定时刷新列表
  useEffect(() => {
    if (!hasActive) return
    const timer = window.setInterval(() => { void refetch() }, POLL_INTERVAL)
    return () => window.clearInterval(timer)
  }, [hasActive, refetch])

  // 服务端进入终态后清除本地“进行中”标记
  useEffect(() => {
    if (runningList.length === 0) return
    const done: string[] = []
    for (const id of runningList) {
      const doc = list.find((d) => d.id === id)
      if (!doc) continue
      if (TERMINAL_STATUSES.has(doc.status)) {
        if (!sawNonTerminalRef.current[id]) continue
        done.push(id)
      } else {
        sawNonTerminalRef.current[id] = true
      }
    }
    if (done.length > 0) {
      setRunningIds((prev) => {
        const next = { ...prev }
        for (const id of done) delete next[id]
        for (const id of done) delete sawNonTerminalRef.current[id]
        return next
      })
    }
  }, [list, runningList])

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
      await documentsApi.upload(kb.id, uploadFile)
      toast('success', '文档已上传', '状态为待解析，点击“开始解析”后执行')
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

  function markRunning(id: string) {
    setRunningIds((prev) => ({ ...prev, [id]: true }))
    sawNonTerminalRef.current[id] = false
  }

  function clearRunning(id: string) {
    setRunningIds((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  async function handleStartParse(doc: DocumentItem) {
    markRunning(doc.id)
    toast('success', '解析已开始', `「${doc.filename}」正在解析`)
    try {
      await documentsApi.startParse(kb.id, doc.id)
      invalidate()
    } catch (err) {
      clearRunning(doc.id)
      toast('error', '开始解析失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleReparse(doc: DocumentItem) {
    if (runningIds[doc.id] || doc.status === 'parsing') {
      toast('error', '文档正在解析中', '请等待当前任务结束后再重新解析')
      return
    }
    markRunning(doc.id)
    toast('success', '重新解析已启动', `已为「${doc.filename}」创建新任务`)
    try {
      await documentsApi.reparse(kb.id, doc.id)
      invalidate()
    } catch (err) {
      clearRunning(doc.id)
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
        description="上传 PDF 后进入待解析状态，手动点击“开始解析”执行 DocLayout-YOLO 版面分析 + GLM-OCR 识别"
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
              <p className="text-xs text-muted-foreground">上传 PDF 后进入待解析状态</p>
            </div>
          ) : (
            <Table className="min-w-[920px]">
              <TableHeader>
                <TableRow>
                  <TableHead>文档</TableHead>
                  <TableHead>大小</TableHead>
                  <TableHead>上传时间</TableHead>
                  <TableHead>状态 / 进度</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((doc) => {
                  const running = Boolean(runningIds[doc.id])
                  const parsing = running || doc.status === 'parsing'
                  const displayStatus = parsing && doc.status === 'queued' ? 'parsing' : doc.status
                  const displayMeta = DOCUMENT_STATUS_META[displayStatus] ?? { label: displayStatus, variant: 'outline' as const }
                  const percent = progressPercentForDoc(doc.process_status, doc.progress_page, doc.progress_total)
                  const stageLabel = PROCESS_LABELS[doc.process_status] ?? '排队中'
                  const pageText = pageProgressText(doc.progress_page, doc.progress_total)
                  return (
                    <TableRow key={doc.id} data-testid={`doc-row-${doc.id}`}>
                      <TableCell>
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                            <FileText className="h-4 w-4" strokeWidth={1.6} />
                          </span>
                          <div className="min-w-0">
                            <p className="max-w-[260px] truncate text-sm font-medium">{doc.filename}</p>
                            <p className="text-xs text-muted-foreground">
                              {doc.page_count > 0 ? `${doc.page_count} 页` : doc.status === 'queued' ? '待解析' : '未解析'}
                            </p>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{(doc.file_size / 1024).toFixed(1)} KB</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatDateTime(doc.created_at)}</TableCell>
                      <TableCell>
                        <div className="w-44">
                          <Badge variant={displayMeta.variant}>{displayMeta.label}</Badge>
                          {parsing ? (
                            <div className="mt-2 space-y-1">
                              <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                                <span className="truncate">{stageLabel}{pageText ? <span data-testid={`progress-page-${doc.id}`}> · {pageText}</span> : null}</span>
                                <span data-testid={`progress-text-${doc.id}`}>{percent}%</span>
                              </div>
                              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" data-testid={`progress-${doc.id}`}>
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500 transition-all duration-500"
                                  style={{ width: `${percent}%` }}
                                  data-testid={`progress-fill-${doc.id}`}
                                />
                              </div>
                            </div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1">
                          {canManage && doc.status === 'queued' && !running ? (
                            <Button
                              variant="ghost"
                              size="icon"
                              title="开始解析"
                              data-testid={`start-${doc.id}`}
                              className="text-primary hover:text-primary-strong"
                              onClick={() => void handleStartParse(doc)}
                            >
                              <PlayCircle className="h-4 w-4" />
                            </Button>
                          ) : null}
                          {canManage && (running || doc.status === 'parsing') ? (
                            <Button
                              variant="ghost"
                              size="icon"
                              title="解析中"
                              disabled
                              data-testid={`parsing-${doc.id}`}
                              className="text-muted-foreground"
                            >
                              <Loader2 className="h-4 w-4 animate-spin" />
                            </Button>
                          ) : null}
                          {doc.status !== 'deleted' ? (
                            <Link
                              to={`/kb/${kb.id}/documents/${doc.id}/viewer`}
                              title="查看"
                              data-testid={`view-${doc.id}`}
                              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted"
                            >
                              <Eye className="h-4 w-4" />
                            </Link>
                          ) : null}
                          {canManage && (doc.status === 'completed' || doc.status === 'failed') && !running ? (
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
                              data-testid={`delete-${doc.id}`}
                              onClick={() => setDeleteTarget(doc)}
                            >
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
        description="支持 PDF，单文件不超过 100MB；上传后进入待解析状态"
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
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setUploadOpen(false)} disabled={uploading}>取消</Button>
          <Button onClick={() => void handleUpload()} disabled={!uploadFile || Boolean(uploadError) || uploading} data-testid="confirm-upload">
            <UploadCloud className="h-4 w-4" />
            {uploading ? '上传中...' : '确认上传'}
          </Button>
        </div>
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
