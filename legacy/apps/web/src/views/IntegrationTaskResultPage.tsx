import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Loader2,
  MessageSquarePlus,
  RefreshCcw,
} from 'lucide-react'
import {
  integrationApi,
  type IntegrationTaskStatus,
} from '@/api/modules/integration'
import { isAuthenticated, useAuthStore } from '@/stores/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import KbExtractionDetailPage from '@/views/KbExtractionDetailPage'

const EXPORT_FORMATS = [
  { format: 'csv' as const, title: 'CSV', desc: '与结果表格内容一致，可直接打开' },
  { format: 'xlsx' as const, title: 'XLSX', desc: '每个检验项目一个工作表，内容与表格一致' },
]

function statusBadge(
  status: string | undefined,
  doneLabel: string,
  runningLabel: string,
) {
  if (status === 'completed')
    return (
      <Badge variant="success">
        <CheckCircle2 className="h-3 w-3" /> {doneLabel}
      </Badge>
    )
  if (status === 'failed')
    return (
      <Badge variant="destructive">
        <AlertCircle className="h-3 w-3" /> 失败
      </Badge>
    )
  if (status === 'running' || status === 'processing' || status === 'queued')
    return (
      <Badge variant="info">
        <Loader2 className="h-3 w-3 animate-spin" /> {runningLabel}
      </Badge>
    )
  return (
    <Badge variant="outline">
      <Clock className="h-3 w-3" /> 等待中
    </Badge>
  )
}

export default function IntegrationTaskResultPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const [task, setTask] = useState<IntegrationTaskStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [retriggering, setRetriggering] = useState(false)
  const [shareToken, setShareToken] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState('')
  const [feedbackSignal, setFeedbackSignal] = useState(0)
  const pollRef = useRef<number | null>(null)
  const { requireAuth, loadPublicConfig } = useAuthStore()
  const configReady = requireAuth !== null
  const authed = isAuthenticated() || requireAuth === false

  useEffect(() => {
    if (requireAuth === null) {
      void loadPublicConfig()
    }
  }, [requireAuth, loadPublicConfig])

  // 只读分享令牌同时用于：未登录跳转 /share、以及页面顶部的导出下载。
  useEffect(() => {
    if (!taskId) return
    let alive = true
    integrationApi
      .sessionToken(taskId)
      .then((res) => {
        if (alive) setShareToken(res.token)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [taskId])

  const load = useCallback(async () => {
    if (!taskId) return
    try {
      setTask(await integrationApi.status(taskId))
    } catch {
      // 瞬时失败不覆盖已有状态
    }
  }, [taskId])

  useEffect(() => {
    setLoading(true)
    void load().finally(() => setLoading(false))
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [load])

  useEffect(() => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current)
    const done =
      task?.extract_status === 'completed' ||
      task?.extract_status === 'failed' ||
      task?.ocr_status === 'failed'
    if (done || !task) return
    pollRef.current = window.setInterval(() => {
      void load()
    }, 2000)
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [task, load])

  const documentId = task?.document_id
    ? task.document_id.replace(/-/g, '')
    : null
  const completed = task?.extract_status === 'completed' && Boolean(documentId)
  const failed =
    task?.ocr_status === 'failed' || task?.extract_status === 'failed'

  useEffect(() => {
    if (!configReady || authed || !completed || !shareToken) return
    navigate(`/share/${shareToken}`, { replace: true })
  }, [configReady, authed, completed, shareToken, navigate])

  async function retrigger() {
    if (!taskId) return
    if (!authed) {
      toast('error', '需要登录', '重新触发是写操作，请先登录系统')
      return
    }
    setRetriggering(true)
    try {
      setTask(await integrationApi.retrigger(taskId))
      toast('success', '已重新触发', '任务将重新执行 OCR 解析与结构化抽取')
    } catch (err) {
      toast(
        'error',
        '重触发失败',
        err instanceof Error ? err.message : '未知错误',
      )
    } finally {
      setRetriggering(false)
    }
  }

  async function exportResult(format: 'csv' | 'xlsx') {
    if (!taskId || exporting) return
    setExporting(format)
    try {
      let token = shareToken
      if (!token) {
        token = (await integrationApi.sessionToken(taskId)).token
        setShareToken(token)
      }
      const response = await fetch(
        `/v1/share/${token}/export?format=${format}`,
      )
      if (!response.ok) throw new Error(`导出失败（${response.status}）`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const stem = (task?.filename || 'result').replace(/\.pdf$/i, '')
      link.href = url
      link.download = `${stem}-${format}.${format}`
      link.click()
      URL.revokeObjectURL(url)
      setExportOpen(false)
      toast('success', '导出完成', `${format.toUpperCase()} 文件已开始下载`)
    } catch (err) {
      toast('error', '导出失败', err instanceof Error ? err.message : '请稍后重试')
    } finally {
      setExporting('')
    }
  }

  function openFeedback() {
    if (!authed) {
      toast('error', '需要登录', '问题反馈是写操作，请先登录系统')
      return
    }
    setFeedbackSignal((value) => value + 1)
  }

  if (loading || !configReady) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border/50 px-4 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => window.history.back()}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" /> 返回
          </Button>
          <div className="h-5 w-px bg-border/60" />
          <div>
            <h1 className="flex items-center gap-2 text-sm font-medium">
              <FileText className="h-4 w-4 text-primary/70" />
              <span className="max-w-[320px] truncate">
                {task?.filename || '对接任务'}
              </span>
            </h1>
            <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
              task_id：{task?.task_id}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={openFeedback}
            disabled={!completed}
            title={authed ? undefined : '问题反馈需要登录'}
            className="gap-1.5"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            问题反馈
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setExportOpen(true)}
            disabled={!completed}
            className="gap-1.5"
          >
            <Download className="h-3.5 w-3.5" />
            导出
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={retrigger}
            disabled={retriggering || !task?.document_id || !authed}
            title={authed ? undefined : '重新触发需要登录'}
            className="gap-1.5"
          >
            {retriggering ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCcw className="h-3.5 w-3.5" />
            )}
            重新触发
          </Button>
        </div>
      </header>

      <div className="border-b border-border/50 bg-card/50 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            OCR 解析 {statusBadge(task?.ocr_status, '完成', '解析中')}
            {task && task.ocr_progress > 0 && (
              <span className="font-mono">{task.ocr_progress}%</span>
            )}
          </span>
          <span className="flex items-center gap-1.5 text-muted-foreground">
            结构化抽取 {statusBadge(task?.extract_status, '完成', '抽取中')}
            {task && task.extract_progress > 0 && (
              <span className="font-mono">{task.extract_progress}%</span>
            )}
          </span>
          {task?.result_version != null && (
            <span className="text-muted-foreground">
              结果版本 v{task.result_version}
            </span>
          )}
          {task?.updated_at && (
            <span className="text-muted-foreground">
              更新时间：{formatDateTime(task.updated_at)}
            </span>
          )}
        </div>
        {task?.error && (
          <p className="mt-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
            失败原因：{task.error}
          </p>
        )}
      </div>

      {completed && documentId ? (
        authed ? (
          <div className="min-h-0 flex-1 overflow-auto">
            <KbExtractionDetailPage
              standalone
              documentId={documentId}
              openFeedbackSignal={feedbackSignal}
            />
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
            <CheckCircle2 className="h-10 w-10 text-success/70" />
            <p className="text-sm font-medium">任务已完成</p>
            <p className="text-xs">正在打开只读结果页…</p>
          </div>
        )
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          {failed ? (
            <>
              <AlertCircle className="h-10 w-10 text-destructive/60" />
              <p className="text-sm font-medium text-destructive">
                任务处理失败
              </p>
              <p className="max-w-md text-center text-xs">
                可点击右上角「重新触发」重试，或等待错误原因修复后重试。
              </p>
            </>
          ) : (
            <>
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <p className="text-sm font-medium">任务处理中...</p>
              <p className="text-xs">
                OCR 解析与结构化抽取完成后，此处将展示抽取结果页面。
              </p>
            </>
          )}
        </div>
      )}

      <Dialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        title="导出结果"
        description="选择导出格式，文件将立即下载（只读令牌，登录与否均可用）"
        className="max-w-md"
      >
        <div className="grid gap-2 sm:grid-cols-2">
          {EXPORT_FORMATS.map((item) => (
            <button
              key={item.format}
              type="button"
              disabled={Boolean(exporting)}
              onClick={() => void exportResult(item.format)}
              className="flex flex-col items-start gap-1 rounded-lg border border-border/70 p-3 text-left transition-colors hover:border-primary/40 hover:bg-muted/50 disabled:opacity-50"
            >
              <span className="flex items-center gap-1.5 text-sm font-medium">
                {exporting === item.format ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5 text-primary/70" />
                )}
                {item.title}
              </span>
              <span className="text-[11px] text-muted-foreground">{item.desc}</span>
            </button>
          ))}
        </div>
      </Dialog>
    </div>
  )
}
