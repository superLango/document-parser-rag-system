import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  AlertCircle, ArrowLeft, CheckCircle2, Clock, FileText, Loader2, RefreshCcw,
} from 'lucide-react'
import { integrationApi, type IntegrationTaskStatus } from '@/api/modules/integration'
import { ApiError, setTokens } from '@/api/client'
import { isAuthenticated, useAuthStore } from '@/stores/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'

function statusBadge(status: string | undefined, doneLabel: string, runningLabel: string) {
  if (status === 'completed') return <Badge className="gap-1 border px-2 py-0 text-[10px] bg-success/10 text-success border-success/30"><CheckCircle2 className="h-2.5 w-2.5" /> {doneLabel}</Badge>
  if (status === 'failed') return <Badge className="gap-1 border px-2 py-0 text-[10px] bg-destructive/10 text-destructive border-destructive/30"><AlertCircle className="h-2.5 w-2.5" /> 失败</Badge>
  if (status === 'running' || status === 'processing' || status === 'queued') return <Badge className="gap-1 border px-2 py-0 text-[10px] bg-primary/10 text-primary border-primary/30"><Loader2 className="h-2.5 w-2.5 animate-spin" /> {runningLabel}</Badge>
  return <Badge variant="outline" className="gap-1 px-2 py-0 text-[10px]"><Clock className="h-2.5 w-2.5" /> 等待中</Badge>
}

export default function IntegrationTaskResultPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const { toast } = useToast()
  const [task, setTask] = useState<IntegrationTaskStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [retriggering, setRetriggering] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fetchUser = useAuthStore((s) => s.fetchUser)

  // 免登录打开结果页: 未登录时自动获取匿名会话令牌并按管理员登录(仅本任务上下文)
  useEffect(() => {
    let cancelled = false
    async function ensureSession() {
      if (!taskId || isAuthenticated()) return
      try {
        const res = await integrationApi.sessionToken(taskId)
        setTokens(res.token)
        if (!cancelled) await fetchUser()
      } catch { /* 获取失败则维持原逻辑(用户可手动登录) */ }
    }
    void ensureSession()
    return () => { cancelled = true }
  }, [taskId, fetchUser])

  const load = useCallback(async () => {
    if (!taskId) return
    try {
      const res = await integrationApi.status(taskId)
      setTask(res)
    } catch { /* 瞬时失败忽略 */ }
  }, [taskId])

  useEffect(() => {
    setLoading(true)
    void load().finally(() => setLoading(false))
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [load])

  // 未完成时轮询（2s）
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    const done = task?.extract_status === 'completed' || task?.extract_status === 'failed' || task?.ocr_status === 'failed'
    if (done || !task) return
    pollRef.current = setInterval(() => { void load() }, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [task, load])

  async function retrigger() {
    if (!taskId) return
    setRetriggering(true)
    try {
      const res = await integrationApi.retrigger(taskId)
      setTask(res)
      toast('success', '已重新触发', '任务将重新执行 OCR 解析与结构化抽取')
    } catch (err) {
      toast('error', '重触发失败', err instanceof ApiError ? err.message : '未知错误')
    } finally {
      setRetriggering(false)
    }
  }

  if (loading) {
    return <div className="flex h-screen items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
  }

  const completed = task?.extract_status === 'completed'
  const failed = task?.ocr_status === 'failed' || task?.extract_status === 'failed'
  const iframeUrl = task?.document_id && task?.kb_id ? `/extraction/${task.kb_id}/${task.document_id}` : null

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border/50 px-4 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => window.history.back()} className="gap-1.5">
            <ArrowLeft className="h-4 w-4" /> 返回
          </Button>
          <div className="h-5 w-px bg-border/60" />
          <div>
            <h1 className="flex items-center gap-2 text-sm font-medium">
              <FileText className="h-4 w-4 text-primary/70" />
              <span className="max-w-[320px] truncate">{task?.filename || '对接任务'}</span>
            </h1>
            <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">task_id：{task?.task_id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={retrigger} disabled={retriggering || !task?.document_id} className="gap-1.5">
            {retriggering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />} 重新触发
          </Button>
        </div>
      </header>

      <div className="border-b border-border/50 bg-card/50 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            OCR 解析 {statusBadge(task?.ocr_status, '完成', '解析中')}
            {task && task.ocr_progress > 0 && <span className="font-mono">{task.ocr_progress}%</span>}
          </span>
          <span className="flex items-center gap-1.5 text-muted-foreground">
            结构化抽取 {statusBadge(task?.extract_status, '完成', '抽取中')}
            {task && task.extract_progress > 0 && <span className="font-mono">{task.extract_progress}%</span>}
          </span>
          {task?.result_version != null && (
            <span className="text-muted-foreground">结果版本 v{task.result_version}</span>
          )}
          {task?.updated_at && (
            <span className="text-muted-foreground">更新时间：{formatDateTime(task.updated_at)}</span>
          )}
        </div>
        {task?.error && (
          <p className="mt-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
            失败原因：{task.error}
          </p>
        )}
      </div>

      {completed && iframeUrl ? (
        <iframe src={iframeUrl} title="结构化抽取结果" className="w-full flex-1 border-0 bg-muted/10" />
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          {failed ? (
            <>
              <AlertCircle className="h-10 w-10 text-destructive/60" />
              <p className="text-sm font-medium text-destructive">任务处理失败</p>
              <p className="max-w-md text-center text-xs">可点击右上角「重新触发」重试，或等待错误原因修复后重试。</p>
            </>
          ) : (
            <>
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <p className="text-sm font-medium">任务处理中...</p>
              <p className="text-xs">OCR 解析与结构化抽取完成后，此处将展示抽取结果页面。</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
