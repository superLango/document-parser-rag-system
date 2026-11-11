import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertCircle,
  Braces,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  FileText,
  GitBranch,
  History,
  Loader2,
  CheckCircle2 as CheckCircleIcon,
  MessageSquarePlus,
  Play,
  RefreshCw,
  Share2,
  Trash2,
} from 'lucide-react'
import { http, getAccessToken } from '@/api/client'
import {
  extractionApi,
  feedbackApi,
  type ExtractionCategory,
  type ExtractionHistoryItem,
  type FeedbackDetail,
  type FeedbackItem,
} from '@/api/modules/extraction'
import { documentsApi, type CrossStandardTask } from '@/api/modules/documents'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'

interface RawDocument {
  id: string
  kb_id: string
  file_name: string
  title?: string | null
  standard_no?: string | null
  status: string
  job_id: string | null
  review_status: 'draft' | 'review' | 'confirmed'
  review_version: number
  created_at: string
  task?: {
    job_id: string
    status: string
    stage: string
    progress: number
    error: string | null
    summary?: Record<string, unknown>
  } | null
}

interface NewTerm {
  type: string
  raw: string
  status: string
  frequency?: number
}

interface NewTermStore {
  terms: NewTerm[]
}

interface SchemaPayload {
  schema_template_id: string | null
  schema_name: string
  categories: ExtractionCategory[]
  summary: Record<string, unknown>
  timing: Record<string, unknown>
}

interface ResultRecord {
  record_id: string
  source_table_id?: string | null
  grade?: string | null
  condition?: string | null
  properties: Record<string, { raw?: string | null; text?: string | null }>
}

const FEEDBACK_CATEGORIES = [
  { value: 'wrong_value', label: '数值错误' },
  { value: 'missing_value', label: '内容缺失' },
  { value: 'extra_value', label: '多余内容' },
  { value: 'wrong_unit', label: '单位错误' },
  { value: 'wrong_requirement', label: '要求/条款错误' },
  { value: 'wrong_table', label: '表格识别错误' },
  { value: 'duplicate', label: '重复记录' },
  { value: 'other', label: '其他' },
]

const FEEDBACK_STATUS: Record<string, { label: string; variant: 'secondary' | 'info' | 'success' | 'warning' | 'destructive' }> = {
  open: { label: '待处理', variant: 'secondary' },
  processing: { label: '修复中', variant: 'info' },
  fixed: { label: '待确认应用', variant: 'success' },
  unresolved: { label: '未修复（有依据）', variant: 'warning' },
  needs_more_info: { label: '无法处理', variant: 'warning' },
  rejected: { label: '未采纳', variant: 'destructive' },
}

function cellText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const EXPORT_FORMATS = [
  { format: 'csv' as const, title: 'CSV', desc: '与结果表格内容一致，可直接打开' },
  { format: 'xlsx' as const, title: 'XLSX', desc: '每个检验项目一个工作表，内容与表格一致' },
]

export default function KbExtractionDetailPage({
  standalone = false,
  documentId: documentIdProp,
  openFeedbackSignal = 0,
}: {
  standalone?: boolean
  documentId?: string
  openFeedbackSignal?: number
}) {
  const params = useParams<{ documentId?: string }>()
  const { toast } = useToast()

  const [document, setDocument] = useState<RawDocument | null>(null)
  const [schema, setSchema] = useState<SchemaPayload | null>(null)
  const [terms, setTerms] = useState<NewTerm[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [viewMode, setViewMode] = useState<'table' | 'json'>('table')
  const [tab, setTab] = useState<'results' | 'preview' | 'cross'>('results')
  const [exportOpen, setExportOpen] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [shareLink, setShareLink] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyItems, setHistoryItems] = useState<ExtractionHistoryItem[]>([])
  const [previewPages, setPreviewPages] = useState<number[]>([])
  const [previewPage, setPreviewPage] = useState(1)
  const [previewImage, setPreviewImage] = useState('')
  const [crossTasks, setCrossTasks] = useState<CrossStandardTask[]>([])
  const [crossSummary, setCrossSummary] = useState<Record<string, number>>({})
  const [feedbackEnabled, setFeedbackEnabled] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackItems, setFeedbackItems] = useState<FeedbackItem[]>([])
  const [feedbackRecords, setFeedbackRecords] = useState<ResultRecord[]>([])
  const [feedbackRecordId, setFeedbackRecordId] = useState('')
  const [feedbackProperty, setFeedbackProperty] = useState('')
  const [feedbackCategory, setFeedbackCategory] = useState('wrong_value')
  const [feedbackDescription, setFeedbackDescription] = useState('')
  const [feedbackExpected, setFeedbackExpected] = useState('')
  const [feedbackQuote, setFeedbackQuote] = useState('')
  const [feedbackReply, setFeedbackReply] = useState('')
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [feedbackDetail, setFeedbackDetail] = useState<FeedbackDetail | null>(null)
  const [feedbackDetailLoading, setFeedbackDetailLoading] = useState(false)
  const [feedbackApplying, setFeedbackApplying] = useState(false)
  const [feedbackApplied, setFeedbackApplied] = useState('')
  const [templateSignature, setTemplateSignature] = useState('')
  const [templateStatus, setTemplateStatus] = useState('')
  const [templateApproving, setTemplateApproving] = useState(false)

  const docId = params.documentId || documentIdProp

  const load = useCallback(async () => {
    if (!docId) return
    setLoading(true)
    try {
      const [doc, result, termStore, cross] = await Promise.all([
        http.get<RawDocument>(`/documents/${docId}`),
        http.get<SchemaPayload>(`/documents/${docId}/result/schema`).catch(() => null),
        http.get<NewTermStore>(`/documents/${docId}/new-terms`).catch(() => ({ terms: [] })),
        documentsApi
          .crossStandardTasks(docId)
          .catch(() => ({ tasks: [], summary: {} })),
      ])
      setDocument(doc)
      setSchema(result)
      setTerms(termStore.terms || [])
      setCrossTasks(cross.tasks || [])
      setCrossSummary(cross.summary || {})
    } catch (err) {
      toast('error', '加载失败', err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [docId, toast])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!docId) return
    let alive = true
    fetch(`/v1/documents/${docId}/preview`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { pages?: Array<{ page_no: number }> } | null) => {
        if (alive && payload?.pages) {
          setPreviewPages(payload.pages.map((page) => page.page_no))
        }
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [docId])

  useEffect(() => {
    if (!docId) return
    let alive = true
    let objectUrl = ''
    fetch(`/v1/documents/${docId}/pages/${previewPage}/image`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error('no image')
        return response.blob()
      })
      .then((blob) => {
        if (!alive) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewImage(objectUrl)
      })
      .catch(() => {
        if (alive) setPreviewImage('')
      })
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [docId, previewPage])

  // 解析中轮询
  useEffect(() => {
    if (!document) return
    if (document.status !== 'queued' && document.status !== 'running') return
    const timer = window.setInterval(() => {
      void load()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [document, load])

  const totalRecords = useMemo(
    () => (schema?.categories || []).reduce((sum, cat) => sum + (cat.records?.length || 0), 0),
    [schema],
  )
  const missingFields = useMemo(
    () => Array.from(new Set((schema?.categories || []).flatMap((cat) => cat.missing_fields || []))),
    [schema],
  )
  const pendingTerms = useMemo(
    () => terms.filter((term) => term.status === 'pending' && term.raw.trim()),
    [terms],
  )
  const parsing = document?.status === 'queued' || document?.status === 'running'

  useEffect(() => {
    let alive = true
    feedbackApi
      .features()
      .then((features) => {
        if (alive) setFeedbackEnabled(Boolean(features.selfheal))
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  const loadFeedback = useCallback(async () => {
    if (!docId || !feedbackEnabled) return
    try {
      const payload = await feedbackApi.list(docId)
      setFeedbackItems(payload.items || [])
    } catch {
      // The self-heal plane may be offline; the entry stays quiet.
    }
  }, [docId, feedbackEnabled])

  async function openFeedback() {
    setFeedbackOpen(true)
    setFeedbackReply('')
    if (!docId || !feedbackEnabled) return
    const [result] = await Promise.all([
      http
        .get<{ records: ResultRecord[] }>(`/documents/${docId}/result`)
        .catch(() => ({ records: [] })),
      loadFeedback(),
    ])
    setFeedbackRecords(result.records || [])
  }

  // 对接页顶部的「问题反馈」按钮通过信号量打开内嵌页的反馈弹窗。
  const feedbackSignalRef = useRef(0)
  useEffect(() => {
    if (!openFeedbackSignal || openFeedbackSignal === feedbackSignalRef.current) {
      return
    }
    feedbackSignalRef.current = openFeedbackSignal
    if (feedbackEnabled) {
      void openFeedback()
    } else {
      toast('error', '问题反馈未启用', '当前环境未开启自愈反馈能力')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openFeedbackSignal, feedbackEnabled])

  const selectedFeedbackRecord = feedbackRecords.find(
    (record) => record.record_id === feedbackRecordId,
  )

  async function openFeedbackDetail(feedbackId: string) {
    if (!docId) return
    if (feedbackDetail?.feedback.feedback_id === feedbackId) {
      setFeedbackDetail(null)
      return
    }
    setFeedbackDetailLoading(true)
    setFeedbackApplied('')
    setTemplateSignature('')
    setTemplateStatus('')
    try {
      setFeedbackDetail(await feedbackApi.detail(docId, feedbackId))
    } catch {
      toast('error', '读取失败', '暂时无法读取这条反馈的处理记录')
    } finally {
      setFeedbackDetailLoading(false)
    }
  }

  async function applyFeedback(feedbackId: string) {
    if (!docId || feedbackApplying) return
    setFeedbackApplying(true)
    setFeedbackApplied('')
    try {
      const outcome = await feedbackApi.apply(docId, feedbackId)
      const learning = outcome.rule_learning
      setFeedbackApplied(
        `已应用修复结果（修改 ${outcome.summary?.changed ?? 0} 处）` +
          (learning?.reason ? `\n规则学习：${learning.reason}` : ''),
      )
      setTemplateSignature(outcome.template_signature || '')
      setTemplateStatus(outcome.template_status || '')
      toast('success', '修复结果已应用', '平台结果已更新')
      void load()
      void loadFeedback()
    } catch (err) {
      const message = err instanceof Error ? err.message : '应用失败'
      setFeedbackApplied(message)
      toast('error', '应用失败', message)
    } finally {
      setFeedbackApplying(false)
    }
  }

  async function approveTemplate() {
    if (!templateSignature || templateApproving) return
    setTemplateApproving(true)
    try {
      await feedbackApi.approveTemplate(templateSignature)
      setTemplateStatus('approved')
      toast(
        'success',
        '同类型复用已启用',
        '相同表头结构的文档会自动套用该修复',
      )
    } catch (err) {
      toast(
        'error',
        '启用失败',
        err instanceof Error ? err.message : '请稍后重试',
      )
    } finally {
      setTemplateApproving(false)
    }
  }

  async function submitFeedback() {
    if (!docId || feedbackBusy) return
    if (
      !feedbackRecordId &&
      feedbackCategory !== 'other' &&
      !feedbackDescription.trim()
    ) {
      toast(
        'error',
        '请描述具体问题',
        '不选记录时，请写明元素/字段、表号或原文数值，系统会自动定位',
      )
      return
    }
    setFeedbackBusy(true)
    setFeedbackReply('')
    try {
      const created = await feedbackApi.create(docId, {
        category: feedbackCategory,
        record_id: feedbackRecordId || undefined,
        property: feedbackProperty || undefined,
        table_id: selectedFeedbackRecord?.source_table_id || undefined,
        grade: selectedFeedbackRecord?.grade || undefined,
        condition: selectedFeedbackRecord?.condition || undefined,
        description: feedbackDescription,
        expected_value: feedbackExpected || undefined,
        source_quote: feedbackQuote || undefined,
      })
      if (created.problems.length) {
        setFeedbackReply(`暂时无法处理：${created.problems.join('；')}`)
        void loadFeedback()
        return
      }
      setFeedbackReply('已收到反馈，正在按原文重新解析并核验…')
      const outcome = await feedbackApi.process(docId, created.feedback.feedback_id)
      setFeedbackReply(outcome.reply || '修复完成')
      setFeedbackDescription('')
      setFeedbackExpected('')
      setFeedbackQuote('')
      void loadFeedback()
      void load()
    } catch (err) {
      setFeedbackReply(err instanceof Error ? err.message : '提交失败')
    } finally {
      setFeedbackBusy(false)
    }
  }

  function newTermFor(text: string): NewTerm | null {
    const value = text.trim()
    if (!value) return null
    for (const term of pendingTerms) {
      const raw = term.raw.trim()
      if (value === raw || value.includes(raw)) return term
    }
    return null
  }

  async function startParse() {
    if (!docId) return
    setBusy(true)
    setBusyAction('parse')
    try {
      await http.post(
        document?.job_id
          ? `/documents/${docId}/parse?force=true`
          : `/documents/${docId}/parse`,
      )
      toast('success', '已开始解析', '解析完成后自动刷新')
      await load()
    } catch (err) {
      toast('error', '开始解析失败', err instanceof Error ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
      setBusyAction('')
    }
  }

  async function exportFile(format: 'csv' | 'xlsx') {
    if (!docId) return
    setBusy(true)
    setBusyAction(format)
    try {
      const token = getAccessToken()
      const response = await fetch(`/v1/documents/${docId}/export?format=${format}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!response.ok) throw new Error(`导出失败（${response.status}）`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = window.document.createElement('a')
      link.href = url
      link.download = `${docId}-${format}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast('error', '导出失败', err instanceof Error ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
      setBusyAction('')
    }
  }

  async function createShare() {
    if (!docId) return
    setBusy(true)
    try {
      const result = await http.post<{ token: string; expires_at: string }>(
        `/documents/${docId}/share`,
      )
      const link = `${window.location.origin}/share/${result.token}`
      setShareLink(link)
      toast('success', '分享链接已生成', `有效期至 ${new Date(result.expires_at).toLocaleString()}`)
    } catch (err) {
      toast('error', '生成失败', err instanceof Error ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function openHistory() {
    if (!docId) return
    setHistoryOpen(true)
    const result = await extractionApi.history('', docId)
    setHistoryItems(result.items)
  }

  const crossStatusLabel: Record<string, string> = {
    resolved: '已解析',
    expanded: '已展开',
    confirmed: '已确认',
    candidate: '候选',
    needs_source: '待补正文',
    not_found: '未入库',
    ignored: '已忽略',
    needed: '待处理',
  }

  async function actCross(
    task: CrossStandardTask,
    action: 'expand' | 'confirm' | 'ignore',
  ) {
    if (!docId) return
    if (action === 'confirm') {
      const requirement =
        task.expansion?.extracted?.[0]?.requirement ||
        task.merge?.requirement ||
        ''
      if (!requirement) {
        toast('error', '无法确认', '该任务还没有可合并的值，请先展开')
        return
      }
      setBusy(true)
      setBusyAction(`cross-${task.task_id}`)
      try {
        await documentsApi.crossStandardConfirm(docId, task.task_id, { requirement })
        toast('success', '已确认', '重新加载结果后生效')
        await load()
      } catch (err) {
        toast('error', '确认失败', err instanceof Error ? err.message : '请稍后重试')
      } finally {
        setBusy(false)
        setBusyAction('')
      }
      return
    }
    setBusy(true)
    setBusyAction(`cross-${task.task_id}`)
    try {
      if (action === 'expand') {
        await documentsApi.crossStandardExpand(docId, task.task_id)
        toast('success', '已展开', '已从来源标准读取缺失字段')
      } else {
        await documentsApi.crossStandardIgnore(docId, task.task_id)
        toast('success', '已忽略')
      }
      await load()
    } catch (err) {
      toast('error', '操作失败', err instanceof Error ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
      setBusyAction('')
    }
  }

  if (loading && !document) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full rounded-2xl" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
          <Skeleton className="h-[480px] w-full rounded-2xl" />
          <Skeleton className="hidden h-72 w-full rounded-2xl xl:block" />
        </div>
      </div>
    )
  }

  const statusVariant =
    document?.status === 'succeeded' || document?.status === 'review'
      ? 'success'
      : document?.status === 'failed'
        ? 'destructive'
        : parsing
          ? 'warning'
          : 'outline'
  const statusLabel =
    parsing
      ? '解析中'
      : document?.status === 'succeeded' || document?.status === 'review'
        ? '已解析'
        : document?.status === 'failed'
          ? '解析失败'
          : '待解析'
  const crossCount = crossSummary.total ?? crossTasks.length

  return (
    <div className="space-y-4">
      {/* 文档头 */}
      <div className="rounded-2xl border border-border bg-card p-4 shadow-soft sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            {!standalone ? (
              <Link
                to="/standard/extraction"
                className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-primary-strong"
              >
                <ChevronLeft className="h-3.5 w-3.5" /> 返回结构化抽取
              </Link>
            ) : null}
            <h1 className="mt-1.5 flex items-center gap-2.5 text-xl font-semibold tracking-tight">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <FileText className="h-4 w-4" />
              </span>
              <span
                className="truncate"
                title={document?.title || document?.file_name}
              >
                {document?.title || document?.file_name || '未命名文档'}
              </span>
            </h1>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-xs text-muted-foreground">
              <Badge variant={statusVariant}>{statusLabel}</Badge>
              {document?.standard_no ? (
                <span className="inline-flex items-center gap-1 font-mono">
                  {document.standard_no}
                </span>
              ) : null}
              <span className="inline-flex items-center gap-1">
                <History className="h-3 w-3" /> v{document?.review_version ?? 1}
              </span>
              {schema ? (
                <span className="inline-flex items-center gap-1">
                  <Braces className="h-3 w-3" /> {schema.schema_name}
                </span>
              ) : null}
              {schema ? (
                <span>
                  {schema.categories.length} 类别 · {totalRecords} 记录
                </span>
              ) : null}
              {missingFields.length > 0 ? (
                <span className="font-medium text-amber-700">缺失 {missingFields.length} 个字段</span>
              ) : null}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void startParse()} disabled={busy || parsing} className="gap-1.5">
              {parsing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {parsing ? '解析中…' : document?.job_id ? '重新解析' : '开始解析'}
            </Button>
            {feedbackEnabled ? (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || parsing}
                onClick={() => void openFeedback()}
                className="gap-1.5"
              >
                <MessageSquarePlus className="h-3.5 w-3.5" /> 问题反馈
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              disabled={busy || !schema}
              onClick={() => setExportOpen(true)}
              className="gap-1.5"
            >
              <Download className="h-3.5 w-3.5" /> 导出
            </Button>
            <Button size="sm" variant="outline" onClick={() => void createShare()} disabled={busy || !schema} className="gap-1.5">
              <Share2 className="h-3.5 w-3.5" /> 分享
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void openHistory()} className="gap-1.5">
              <History className="h-3.5 w-3.5" /> 历史
            </Button>
          </div>
        </div>

        {parsing ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-3.5 py-3">
            <div className="flex items-center justify-between text-xs text-sky-800">
              <span className="flex items-center gap-1.5">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                解析进行中 · {document?.task?.stage || '排队中'}
              </span>
              <span className="font-mono tabular-nums">{document?.task?.progress ?? 0}%</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sky-100">
              <div
                className="h-full rounded-full bg-sky-500 transition-all"
                style={{ width: `${document?.task?.progress ?? 0}%` }}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-sky-700">页面每 3 秒自动刷新，完成后展示结构化结果。</p>
          </div>
        ) : null}
      </div>

      {shareLink ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <span className="font-medium">分享链接（只读）</span>
          <input
            readOnly
            value={shareLink}
            onFocus={(event) => event.currentTarget.select()}
            className="min-w-0 flex-1 rounded-md border border-emerald-200 bg-white px-2 py-1 font-mono text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void navigator.clipboard.writeText(shareLink)
              toast('success', '已复制')
            }}
          >
            复制
          </Button>
        </div>
      ) : null}

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        {/* 主内容 */}
        <div className="min-w-0 space-y-4">
          <Tabs
            value={tab}
            onValueChange={(value) => setTab(value as typeof tab)}
            className="w-auto max-w-lg"
            items={[
              {
                value: 'results',
                label: (
                  <span className="inline-flex items-center gap-1.5">
                    抽取结果
                    {schema ? (
                      <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums text-muted-foreground">
                        {totalRecords}
                      </span>
                    ) : null}
                  </span>
                ),
              },
              { value: 'preview', label: '原文预览' },
              {
                value: 'cross',
                label: (
                  <span className="inline-flex items-center gap-1.5">
                    跨标准补全
                    {crossCount ? (
                      <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums text-muted-foreground">
                        {crossCount}
                      </span>
                    ) : null}
                  </span>
                ),
              },
            ]}
          />

          {tab === 'results' ? (
            <Card>
              <CardContent className="p-0">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Braces className="h-4 w-4 text-primary" />
                    抽取结果
                    {schema ? (
                      <Badge variant="secondary" className="text-[10px]">
                        {schema.categories.length} 类别 · {totalRecords} 记录
                      </Badge>
                    ) : null}
                  </div>
                  {schema ? (
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => setViewMode('table')}
                        className={`rounded-md border px-2.5 py-1 text-[11px] transition-colors ${viewMode === 'table' ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border/60 text-muted-foreground hover:text-foreground'}`}
                      >
                        表格
                      </button>
                      <button
                        type="button"
                        onClick={() => setViewMode('json')}
                        className={`rounded-md border px-2.5 py-1 text-[11px] transition-colors ${viewMode === 'json' ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border/60 text-muted-foreground hover:text-foreground'}`}
                      >
                        JSON
                      </button>
                    </div>
                  ) : null}
                </div>

                <div className="p-3 sm:p-4">
                  {!schema ? (
                    <div className="flex flex-col items-center gap-2 py-20 text-center">
                      <Braces className="h-8 w-8 text-muted-foreground/50" />
                      <p className="text-sm font-medium">暂无抽取结果</p>
                      <p className="text-xs text-muted-foreground">
                        {parsing ? '解析完成后自动展示' : '先点击「开始解析」'}
                      </p>
                    </div>
                  ) : viewMode === 'json' ? (
                    <pre className="max-h-[calc(100dvh-20rem)] overflow-auto whitespace-pre-wrap rounded-lg border border-border/50 bg-muted/40 p-4 font-mono text-xs">
                      {JSON.stringify(schema, null, 2)}
                    </pre>
                  ) : (
                    <div className="space-y-2">
                      {schema.categories.map((category, categoryIndex) => {
                        const isOpen = expanded[category.feature] ?? categoryIndex === 0
                        const categoryTerm = newTermFor(category.feature)
                        const headers = category.fields?.length
                          ? category.fields
                          : Array.from(
                              new Set(category.records.flatMap((record) => Object.keys(record))),
                            )
                        return (
                          <div key={category.feature} className="overflow-hidden rounded-lg border border-border/60">
                            <button
                              type="button"
                              onClick={() =>
                                setExpanded((prev) => ({ ...prev, [category.feature]: !isOpen }))
                              }
                              className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-muted/40"
                              title={categoryTerm ? `新词候选：${categoryTerm.raw}` : undefined}
                            >
                              <ChevronRight
                                className={`h-4 w-4 shrink-0 text-primary transition-transform ${isOpen ? 'rotate-90' : ''}`}
                              />
                              <span className="min-w-0 flex-1">
                                <span className={`block truncate text-[13px] font-semibold ${categoryTerm ? 'text-amber-700' : ''}`}>
                                  {category.feature}
                                </span>
                                <span className="block text-[11px] text-muted-foreground">
                                  {category.records?.length ?? 0} 条记录
                                </span>
                              </span>
                              {category.missing_fields?.length ? (
                                <Badge variant="warning" className="text-[10px]">
                                  缺失 {category.missing_fields.length}
                                </Badge>
                              ) : (
                                <Badge variant="success" className="text-[10px]">完整</Badge>
                              )}
                            </button>
                            {isOpen ? (
                              <div className="max-h-[520px] overflow-auto border-t border-border/50">
                                <table className="w-full min-w-max border-collapse text-xs">
                                  <thead className="sticky top-0 z-10">
                                    <tr className="bg-muted/90 backdrop-blur">
                                      {headers.map((header) => {
                                        const term = newTermFor(header)
                                        return (
                                          <th
                                            key={header}
                                            className={`whitespace-nowrap border-b border-border/40 px-2.5 py-2 text-left font-semibold ${term ? 'bg-amber-50 text-amber-800' : 'text-muted-foreground'}`}
                                            title={term ? `新词候选：${term.raw}` : undefined}
                                          >
                                            {header}
                                          </th>
                                        )
                                      })}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {category.records.map((record, index) => (
                                      <tr key={index} className="transition-colors hover:bg-primary/[0.04]">
                                        {headers.map((header) => {
                                          const text = cellText(record[header])
                                          const term = newTermFor(text)
                                          return (
                                            <td
                                              key={header}
                                              className={`border-b border-border/30 px-2.5 py-1.5 align-top ${term ? 'bg-amber-50 text-amber-900' : ''}`}
                                              title={term ? `新词候选：${term.raw}` : undefined}
                                            >
                                              {text || <span className="text-muted-foreground/40">—</span>}
                                            </td>
                                          )
                                        })}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                      <p className="flex items-center gap-1.5 pt-1 text-[11px] text-muted-foreground">
                        <RefreshCw className="h-3 w-3" />
                        黄色单元格为未入词典的新词候选，点击类别标题可折叠。
                      </p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {tab === 'preview' ? (
            <Card>
              <CardContent className="p-0">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <FileText className="h-4 w-4 text-primary" />
                    原文预览
                    <span className="text-xs font-normal text-muted-foreground">
                      {previewPage} / {previewPages.length || '—'}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => setPreviewPage((value) => Math.max(1, value - 1))}
                      disabled={previewPage <= 1}
                      aria-label="上一页"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() =>
                        setPreviewPage((value) => Math.min(previewPages.length || value, value + 1))
                      }
                      disabled={previewPage >= previewPages.length}
                      aria-label="下一页"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                    {docId ? (
                      <Link
                        to={`/standard/documents/${docId}/viewer`}
                        className="ml-2 text-xs text-primary hover:underline"
                      >
                        放大查看
                      </Link>
                    ) : null}
                  </div>
                </div>
                <div className="flex min-h-[360px] items-center justify-center bg-muted/20 p-4">
                  {previewImage ? (
                    <img
                      src={previewImage}
                      alt={`第 ${previewPage} 页`}
                      className="max-h-[min(72vh,760px)] w-full rounded-lg border border-border/50 bg-white object-contain"
                    />
                  ) : (
                    <p className="py-16 text-center text-xs text-muted-foreground">页面图片不可用</p>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {tab === 'cross' ? (
            <Card>
              <CardContent className="p-0">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <GitBranch className="h-4 w-4 text-primary" />
                    跨标准补全
                    <Badge variant="secondary" className="text-[10px]">
                      {crossCount} 个任务
                    </Badge>
                    {Number(crossSummary.expanded || 0) > 0 ? (
                      <Badge variant="success" className="text-[10px]">
                        已展开 {crossSummary.expanded}
                      </Badge>
                    ) : null}
                    {Number(crossSummary.needs_source || 0) > 0 ? (
                      <Badge variant="warning" className="text-[10px]">
                        待补正文 {crossSummary.needs_source}
                      </Badge>
                    ) : null}
                  </div>
                  <span className="text-[11px] text-muted-foreground">
                    只填空值或表引用，不覆盖已有要求
                  </span>
                </div>
                <div className="p-3 sm:p-4">
                  {crossTasks.length === 0 ? (
                    <p className="py-16 text-center text-xs text-muted-foreground">
                      未发现需要跨标准补全的缺失参数
                    </p>
                  ) : (
                    <div className="overflow-x-auto rounded-lg border border-border/60">
                      <table className="w-full min-w-max border-collapse text-xs">
                        <thead>
                          <tr className="bg-muted/50">
                            {['状态', '检验项目', '缺失字段', '要求标准', '来源 / 缺口', '提取值', '操作'].map(
                              (header) => (
                                <th
                                  key={header}
                                  className="whitespace-nowrap border-b border-border/40 px-2.5 py-2 text-left font-semibold text-muted-foreground"
                                >
                                  {header}
                                </th>
                              ),
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {crossTasks.map((task) => {
                            const extracted = task.expansion?.extracted?.[0]
                            const requirement =
                              extracted?.requirement || task.merge?.requirement || ''
                            const variant =
                              task.status === 'confirmed' || task.status === 'expanded'
                                ? 'success'
                                : task.status === 'candidate' || task.status === 'needs_source'
                                  ? 'warning'
                                  : task.status === 'not_found'
                                    ? 'destructive'
                                    : 'outline'
                            const actionKey = `cross-${task.task_id}`
                            return (
                              <tr key={task.task_id} className="transition-colors hover:bg-primary/[0.04]">
                                <td className="border-b border-border/30 px-2.5 py-1.5">
                                  <Badge variant={variant} className="text-[10px]">
                                    {crossStatusLabel[task.status] || task.status}
                                  </Badge>
                                </td>
                                <td className="border-b border-border/30 px-2.5 py-1.5">
                                  {task.inspection_item || '—'}
                                </td>
                                <td className="border-b border-border/30 px-2.5 py-1.5">
                                  {(task.missing_fields || []).join('、') || '—'}
                                </td>
                                <td className="whitespace-nowrap border-b border-border/30 px-2.5 py-1.5">
                                  {task.requirement_standard}
                                  {task.requirement_edition ? `-${task.requirement_edition}` : ''}
                                </td>
                                <td className="max-w-[280px] border-b border-border/30 px-2.5 py-1.5 text-muted-foreground">
                                  {task.resolved_source_file ||
                                    task.gap ||
                                    task.resolution_basis ||
                                    '—'}
                                </td>
                                <td className="max-w-[220px] border-b border-border/30 px-2.5 py-1.5">
                                  {requirement || '—'}
                                </td>
                                <td className="border-b border-border/30 px-2.5 py-1.5">
                                  <div className="flex gap-1">
                                    {task.status === 'resolved' && !task.expansion ? (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={busy}
                                        onClick={() => void actCross(task, 'expand')}
                                      >
                                        {busyAction === actionKey ? '处理中…' : '展开'}
                                      </Button>
                                    ) : null}
                                    {requirement &&
                                    task.status !== 'ignored' &&
                                    task.status !== 'confirmed' ? (
                                      <Button
                                        size="sm"
                                        disabled={busy}
                                        onClick={() => void actCross(task, 'confirm')}
                                      >
                                        确认
                                      </Button>
                                    ) : null}
                                    {task.status !== 'ignored' ? (
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        disabled={busy}
                                        onClick={() => void actCross(task, 'ignore')}
                                      >
                                        忽略
                                      </Button>
                                    ) : null}
                                  </div>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {standalone ? null : (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Trash2 className="h-3 w-3" /> 删除文档请到「文档解析」页面操作。
            </p>
          )}
        </div>

        {/* 侧栏：文档信息 / 缺失字段 / 新词 */}
        <aside className="space-y-3 xl:sticky xl:top-20">
          <Card>
            <CardContent className="p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                文档信息
              </p>
              <dl className="mt-3 space-y-2.5 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">状态</dt>
                  <dd><Badge variant={statusVariant}>{statusLabel}</Badge></dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">上传时间</dt>
                  <dd className="text-right">{formatDateTime(document?.created_at)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">页数</dt>
                  <dd className="tabular-nums">{previewPages.length || '—'}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">版本</dt>
                  <dd className="tabular-nums">v{document?.review_version ?? 1}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">Schema</dt>
                  <dd className="max-w-[170px] truncate text-right" title={schema?.schema_name}>
                    {schema?.schema_name || '—'}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">类别 / 记录</dt>
                  <dd className="tabular-nums">
                    {schema ? `${schema.categories.length} / ${totalRecords}` : '—'}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">跨标准任务</dt>
                  <dd className="tabular-nums">{crossCount}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          {missingFields.length > 0 ? (
            <Card className="border-amber-200/70 bg-amber-50/40">
              <CardContent className="p-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-700">
                    <AlertCircle className="h-3.5 w-3.5" /> 缺失字段
                  </p>
                  <Badge variant="warning" className="text-[10px]">{missingFields.length}</Badge>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {missingFields.map((field) => (
                    <span
                      key={field}
                      className="rounded-md border border-amber-200 bg-white/70 px-1.5 py-0.5 text-[11px] text-amber-800"
                    >
                      {field}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {pendingTerms.length > 0 ? (
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    新词候选
                  </p>
                  <Badge variant="warning" className="text-[10px]">{pendingTerms.length}</Badge>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {pendingTerms.slice(0, 8).map((term) => (
                    <span
                      key={`${term.type}-${term.raw}`}
                      className="rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800"
                      title={`${term.type} · ${term.raw}`}
                    >
                      {term.raw}
                    </span>
                  ))}
                  {pendingTerms.length > 8 ? (
                    <span className="px-1 text-[11px] text-muted-foreground">
                      +{pendingTerms.length - 8}
                    </span>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </div>

      <Dialog open={exportOpen} onOpenChange={setExportOpen} title="导出结果" description="选择导出格式，文件将立即下载" className="max-w-md">
        <div className="grid gap-2 sm:grid-cols-2">
          {EXPORT_FORMATS.map((item) => (
            <button
              key={item.format}
              type="button"
              disabled={busy}
              onClick={() => {
                setExportOpen(false)
                void exportFile(item.format)
              }}
              className="flex flex-col items-start gap-1 rounded-lg border border-border/70 p-3 text-left transition-colors hover:border-primary/40 hover:bg-muted/50 disabled:opacity-50"
            >
              <span className="text-sm font-medium">{item.title}</span>
              <span className="text-[11px] text-muted-foreground">{item.desc}</span>
            </button>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">
          大文件导出可能需要几秒，请勿重复点击。
        </p>
      </Dialog>

      <Dialog open={historyOpen} onOpenChange={(open) => { if (!open) setHistoryOpen(false) }} title="抽取历史" className="max-w-lg">
        {historyItems.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <Clock className="h-8 w-8 text-muted-foreground/50" />
            <p className="text-sm font-medium">暂无历史版本</p>
            <p className="text-xs text-muted-foreground">重新解析后会生成新版本</p>
          </div>
        ) : (
          <div className="max-h-96 space-y-2 overflow-auto">
            {historyItems.map((item) => (
              <div key={item.id} className="flex items-center justify-between rounded-lg border border-border/60 p-3">
                <div>
                  <p className="text-sm font-medium">v{item.version} · {item.schema_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {Number(item.summary?.record_count ?? 0)} 条记录 · {new Date(item.extracted_at).toLocaleString('zh-CN')}
                  </p>
                </div>
                <Badge variant="secondary" className="text-[10px]">只读</Badge>
              </div>
            ))}
          </div>
        )}
      </Dialog>

      <Dialog
        open={feedbackOpen}
        onOpenChange={(open) => {
          if (!feedbackBusy) setFeedbackOpen(open)
        }}
        title="问题反馈"
        description="描述抽取中的问题，系统会按原文重新解析并核验修复结果"
        className="max-w-xl"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setFeedbackOpen(false)}
              disabled={feedbackBusy}
            >
              关闭
            </Button>
            <Button
              onClick={() => void submitFeedback()}
              disabled={feedbackBusy}
              className="gap-1.5"
            >
              {feedbackBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <MessageSquarePlus className="h-3.5 w-3.5" />
              )}
              {feedbackBusy ? '修复中…' : '提交并修复'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>问题类型</Label>
              <Select
                value={feedbackCategory}
                onChange={(event) => setFeedbackCategory(event.target.value)}
                disabled={feedbackBusy}
              >
                {FEEDBACK_CATEGORIES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>问题记录（可选）</Label>
              <Select
                value={feedbackRecordId}
                onChange={(event) => {
                  setFeedbackRecordId(event.target.value)
                  setFeedbackProperty('')
                }}
                disabled={feedbackBusy}
              >
                <option value="">不选，由模型根据描述自动定位</option>
                {feedbackRecords.map((record) => (
                  <option key={record.record_id} value={record.record_id}>
                    {record.record_id}
                    {record.grade ? ` · ${record.grade}` : ''}
                    {record.condition ? ` · ${record.condition}` : ''}
                  </option>
                ))}
              </Select>
              <p className="text-[11px] text-muted-foreground">
                可以不选记录，直接描述问题，系统会回到原文定位并给出依据。
              </p>
            </div>
          </div>

          {selectedFeedbackRecord ? (
            <div className="space-y-1.5">
              <Label>问题字段（可选）</Label>
              <Select
                value={feedbackProperty}
                onChange={(event) => setFeedbackProperty(event.target.value)}
                disabled={feedbackBusy}
              >
                <option value="">整条记录</option>
                {Object.keys(selectedFeedbackRecord.properties).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </Select>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <Label>问题描述</Label>
            <textarea
              value={feedbackDescription}
              onChange={(event) => setFeedbackDescription(event.target.value)}
              rows={3}
              disabled={feedbackBusy}
              placeholder="直接描述问题即可，例如：室温拉伸标准要求不对、持久项目没有解析出来、标准编号不对"
              className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-soft transition-all duration-200 placeholder:text-muted-foreground/70 focus-visible:border-primary/50 focus-visible:shadow-glow disabled:opacity-50"
            />
            <p className="text-[11px] text-muted-foreground">
              系统会自己定位错误、从原文找出正解并生成修正；无法修复时会列出查过的页、表和原因。
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>期望值（可选）</Label>
              <Input
                value={feedbackExpected}
                onChange={(event) => setFeedbackExpected(event.target.value)}
                disabled={feedbackBusy}
                placeholder="如 0.015~0.060"
              />
            </div>
            <div className="space-y-1.5">
              <Label>原文引文（可选）</Label>
              <Input
                value={feedbackQuote}
                onChange={(event) => setFeedbackQuote(event.target.value)}
                disabled={feedbackBusy}
                placeholder="粘贴原文中的一句话"
              />
            </div>
          </div>

          {feedbackReply ? (
            <div className="whitespace-pre-wrap rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
              {feedbackReply}
            </div>
          ) : null}

          {feedbackItems.length ? (
            <div className="space-y-1.5">
              <Label>本文件的反馈</Label>
              <div className="max-h-56 space-y-1.5 overflow-auto">
                {feedbackItems.map((item) => {
                  const status = FEEDBACK_STATUS[item.status] || FEEDBACK_STATUS.open
                  const isOpen =
                    feedbackDetail?.feedback.feedback_id === item.feedback_id
                  const canApply =
                    isOpen && feedbackDetail?.feedback.status === 'fixed'
                  return (
                    <div
                      key={item.feedback_id}
                      className="overflow-hidden rounded-lg border border-border/60"
                    >
                      <button
                        type="button"
                        onClick={() => void openFeedbackDetail(item.feedback_id)}
                        className="flex w-full items-start justify-between gap-2 px-2.5 py-2 text-left transition-colors hover:bg-muted/40"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-xs">
                            {item.description || item.category}
                          </p>
                          <p className="truncate text-[11px] text-muted-foreground">
                            {item.target.record_id ||
                              item.target.table_id ||
                              item.target.feature ||
                              '整篇'}{' '}
                            · {formatDateTime(item.created_at)} · 点击查看处理结果
                          </p>
                        </div>
                        <Badge
                          variant={status.variant}
                          className="shrink-0 text-[10px]"
                        >
                          {status.label}
                        </Badge>
                      </button>
                      {isOpen ? (
                        <div className="space-y-1.5 border-t border-border/50 bg-muted/20 px-2.5 py-2">
                          {feedbackDetailLoading ? (
                            <p className="text-[11px] text-muted-foreground">加载中…</p>
                          ) : feedbackDetail && feedbackDetail.messages.length ? (
                            feedbackDetail.messages.map((message) => (
                              <p
                                key={message.message_id}
                                className={`whitespace-pre-wrap text-[11px] ${
                                  message.role === 'system'
                                    ? 'text-muted-foreground'
                                    : 'text-foreground'
                                }`}
                              >
                                {message.content}
                              </p>
                            ))
                          ) : (
                            <p className="text-[11px] text-muted-foreground">
                              暂无处理消息
                            </p>
                          )}
                          {canApply ? (
                            <div className="flex flex-wrap items-center gap-2 border-t border-border/40 pt-1.5">
                              <Button
                                size="sm"
                                variant="outline"
                                className="gap-1.5"
                                disabled={feedbackApplying}
                                onClick={() => void applyFeedback(item.feedback_id)}
                              >
                                {feedbackApplying ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <CheckCircleIcon className="h-3.5 w-3.5" />
                                )}
                                应用修复结果
                              </Button>
                              {feedbackApplied ? (
                                <span className="text-[11px] text-emerald-700">
                                  {feedbackApplied}
                                </span>
                              ) : null}
                              {templateSignature && templateStatus === 'pending' ? (
                                <>
                                  <span className="text-[11px] text-amber-700">
                                    同类型模板待确认
                                  </span>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="gap-1.5"
                                    disabled={templateApproving}
                                    onClick={() => void approveTemplate()}
                                  >
                                    {templateApproving ? (
                                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    ) : null}
                                    启用同类型复用
                                  </Button>
                                </>
                              ) : templateSignature && templateStatus === 'approved' ? (
                                <span className="text-[11px] text-emerald-700">
                                  同类型模板已启用
                                </span>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}
        </div>
      </Dialog>
    </div>
  )
}
