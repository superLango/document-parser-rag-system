import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Braces, CheckCircle2, ChevronRight, Clock, Database, FileText, History, Loader2, Plus, Save, Sparkles, Table, Trash2, Zap } from 'lucide-react'
import { extractionApi, type ExtractionCategory, type ExtractionHistoryItem, type ExtractionResultData } from '@/api/modules/extraction'
import { extractionConfigApi, type SchemaTemplate } from '@/api/modules/extractionConfig'
import { ApiError, getAccessToken } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/auth'
import { useKbDetail } from './KbDetailLayout'

const STEPS = [
  { id: 1, label: '初始化', icon: Sparkles },
  { id: 2, label: '解析文档', icon: FileText },
  { id: 3, label: '抽取字段', icon: Database },
  { id: 4, label: '完成', icon: CheckCircle2 },
]

function cellValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function headersOf(cat: ExtractionCategory): string[] {
  const keys: string[] = []
  for (const rec of cat.records || []) {
    for (const k of Object.keys(rec)) {
      if (!keys.includes(k)) keys.push(k)
    }
  }
  return keys
}

export default function KbExtractionDetailPage() {
  const { documentId } = useParams<{ documentId: string }>()
  const { kb } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'
  const navigate = useNavigate()
  const { toast } = useToast()

  const [loading, setLoading] = useState(true)
  const [filename, setFilename] = useState('')
  const [schemas, setSchemas] = useState<SchemaTemplate[]>([])
  const [selectedSchemaId, setSelectedSchemaId] = useState('')
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle')
  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')
  const [result, setResult] = useState<ExtractionResultData | null>(null)
  const [viewMode, setViewMode] = useState<'table' | 'json'>('table')
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set())
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyItems, setHistoryItems] = useState<ExtractionHistoryItem[]>([])
  const [viewingHistory, setViewingHistory] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 结果人工编辑（draft）
  const draftRef = useRef<ExtractionCategory[] | null>(null)
  const [draftCategories, setDraftCategories] = useState<ExtractionCategory[] | null>(null)
  const [savingResult, setSavingResult] = useState(false)
  const [deleteCatTarget, setDeleteCatTarget] = useState<number | null>(null)

  const currentStep = progress >= 100 ? 4 : progress >= 60 ? 3 : progress >= 40 ? 2 : progress >= 10 ? 1 : 1

  const loadResult = useCallback(async () => {
    if (!documentId) return
    try {
      const res = await extractionApi.result(kb.id, documentId)
      setResult(res)
      if (res) {
        setProgress(res.progress ?? 100)
        setStatus((res.status === 'failed' ? 'failed' : res.status === 'completed' ? 'completed' : status) as typeof status)
      }
    } catch { /* 轮询瞬时失败忽略 */ }
  }, [kb.id, documentId, status])

  const poll = useCallback(() => {
    if (!documentId) return
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const s = await extractionApi.status(kb.id, documentId)
        setProgress(s.progress ?? 0)
        if (s.status === 'completed') {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setStatus('completed')
          setProgressMessage('抽取完成，加载结果...')
          await loadResult()
          localStorage.removeItem(`extract_task_${kb.id}_${documentId}`)
        } else if (s.status === 'failed') {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setStatus('failed')
          setProgress(100)
          setProgressMessage(s.error?.message ? `抽取失败：${s.error.message}` : '抽取失败')
          await loadResult()
          localStorage.removeItem(`extract_task_${kb.id}_${documentId}`)
        } else {
          setStatus('running')
          setProgressMessage('抽取进行中...')
        }
      } catch { /* 忽略瞬时失败 */ }
    }, 2000)
  }, [kb.id, documentId, loadResult])

  useEffect(() => {
    async function init() {
      setLoading(true)
      try {
        const [docRes, tplRes] = await Promise.all([
          extractionApi.getDocument(kb.id, documentId!),
          extractionConfigApi.listSchemaTemplates(kb.id),
        ])
        setFilename(docRes.filename)
        setSchemas(tplRes.items)
        if (tplRes.items.length > 0) setSelectedSchemaId(tplRes.items[0].id)
        const saved = localStorage.getItem(`extract_task_${kb.id}_${documentId}`)
        if (saved) {
          const s = await extractionApi.status(kb.id, documentId!)
          if (s.status === 'running' || s.task_status === 'running' || s.task_status === 'queued') {
            setStatus('running')
            setProgress(s.progress ?? 0)
            poll()
          } else {
            localStorage.removeItem(`extract_task_${kb.id}_${documentId}`)
            await loadResult()
          }
        } else {
          await loadResult()
        }
      } catch {
        toast('error', '加载失败', '无法加载抽取详情')
      } finally {
        setLoading(false)
      }
      // 原文档预览
      try {
        const token = getAccessToken()
        const resp = await fetch(`/api/v1/kb/${kb.id}/documents/${documentId}/original`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (resp.ok) {
          const blob = await resp.blob()
          setPdfUrl(URL.createObjectURL(blob))
        }
      } catch { /* 不支持预览时忽略 */ }
    }
    void init()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kb.id, documentId])

  async function start() {
    if (!selectedSchemaId) { toast('warning', '请选择 Schema'); return }
    if (pollRef.current) clearInterval(pollRef.current)
    setStatus('running')
    setProgress(0)
    setProgressMessage('正在提交抽取任务...')
    setResult(null)
    setViewingHistory(false)
    try {
      const res = await extractionApi.start(kb.id, documentId!)
      localStorage.setItem(`extract_task_${kb.id}_${documentId}`, res.task_id)
      setProgressMessage('抽取任务已提交，正在后台执行...')
      poll()
    } catch (err) {
      setStatus('failed')
      setProgressMessage('提交失败，请稍后重试')
      toast('error', '提交失败', '无法提交抽取任务')
    }
  }

  async function openHistory() {
    setHistoryOpen(true)
    setHistoryLoading(true)
    try {
      const res = await extractionApi.history(kb.id, documentId!)
      setHistoryItems(res.items)
    } catch {
      setHistoryItems([])
    } finally {
      setHistoryLoading(false)
    }
  }

  function viewHistoryItem(item: ExtractionHistoryItem) {
    setViewingHistory(true)
    setResult({
      schema_template_id: item.schema_template_id,
      schema_name: item.schema_name,
      status: 'completed',
      progress: 100,
      categories: item.categories,
      summary: item.summary,
      timing: item.timing,
      version: item.version,
      error: null,
      updated_at: item.extracted_at,
    })
    setStatus('completed')
    setHistoryOpen(false)
  }

  async function removeResult() {
    setDeleteOpen(false)
    setDeleting(true)
    try {
      await extractionApi.remove(kb.id, documentId!)
      setResult(null)
      setStatus('idle')
      setProgress(0)
      setProgressMessage('')
      setViewingHistory(false)
      toast('success', '已删除', '抽取结果与历史已删除')
    } catch {
      toast('error', '删除失败', '请稍后重试')
    } finally {
      setDeleting(false)
    }
  }

  function getDraft(): ExtractionCategory[] {
    if (!draftRef.current && result) {
      draftRef.current = JSON.parse(JSON.stringify(result.categories || []))
      setDraftCategories(draftRef.current)
    }
    return draftRef.current ?? []
  }

  function commitDraft(next: ExtractionCategory[]) {
    draftRef.current = next
    setDraftCategories(next)
  }

  function updateCell(catIdx: number, rowIdx: number, field: string, value: string) {
    commitDraft(getDraft().map((c, i) => (i === catIdx ? { ...c, records: (c.records || []).map((r, ri) => (ri === rowIdx ? { ...r, [field]: value } : r)) } : c)))
  }

  function addRecord(catIdx: number) {
    const cat = getDraft()[catIdx]
    const fields = headersOf(cat)
    const blank: Record<string, unknown> = {}
    for (const f of fields) blank[f] = ''
    commitDraft(getDraft().map((c, i) => (i === catIdx ? { ...c, records: [...(c.records || []), blank] } : c)))
  }

  function deleteRecord(catIdx: number, rowIdx: number) {
    commitDraft(getDraft().map((c, i) => (i === catIdx ? { ...c, records: (c.records || []).filter((_, ri) => ri !== rowIdx) } : c)))
  }

  function deleteCategory(catIdx: number) {
    commitDraft(getDraft().filter((_, i) => i !== catIdx))
    setDeleteCatTarget(null)
  }

  function cancelDraft() {
    draftRef.current = null
    setDraftCategories(null)
  }

  async function saveDraft() {
    if (!draftRef.current) return
    setSavingResult(true)
    try {
      await extractionApi.updateResult(kb.id, documentId!, draftRef.current)
      toast('success', '保存成功', '抽取结果已更新（版本 +1）')
      cancelDraft()
      await loadResult()
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSavingResult(false)
    }
  }

  const dirty = draftCategories != null && JSON.stringify(draftCategories) !== JSON.stringify(result?.categories ?? [])
  const displayCategories = draftCategories ?? result?.categories ?? []

  async function exportCsv() {
    try {
      await extractionApi.exportCsv(kb.id, documentId!)
    } catch (err) {
      toast('error', '导出失败', err instanceof Error ? err.message : '导出失败')
    }
  }

  const missingFields = Array.from(new Set((result?.categories || []).flatMap((c) => c.missing_fields || [])))
  const totalRecords = (result?.categories || []).reduce((sum, c) => sum + (c.records || []).length, 0)
  const recall = (result?.summary?.recall ?? null) as { mode?: string; participated?: number; kept?: number; skipped_count?: number; score_bands?: Record<string, number> } | null
  const skipped = (result?.summary?.skipped ?? []) as { feature: string; reason: string; score?: number | null }[]

  if (loading) {
    return <div className="flex h-screen items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border/50 px-4 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(`/kb/${kb.id}/extraction`)} className="gap-1.5">
            <ArrowLeft className="h-4 w-4" /> 返回列表
          </Button>
          <div className="h-5 w-px bg-border/60" />
          <div>
            <h1 className="flex items-center gap-2 text-sm font-medium">
              <FileText className="h-4 w-4 text-primary/70" />
              <span className="max-w-[300px] truncate">{filename || '加载中...'}</span>
            </h1>
            <div className="mt-0.5 flex items-center gap-2">
              <Badge variant="secondary" className="gap-1 border px-2 py-0 text-[10px] bg-success/10 text-success border-success/30">
                <CheckCircle2 className="h-2.5 w-2.5" /> 已解析
              </Badge>
              {viewingHistory && (
                <Badge variant="outline" className="gap-1 text-[10px] text-info border-info/30 bg-info/5">
                  <History className="h-2.5 w-2.5" /> 历史版本
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {result && status === 'completed' && (
            <Button variant="outline" size="sm" onClick={exportCsv} className="gap-1.5">导出 CSV</Button>
          )}
          {canManage && result && status === 'completed' && (
            <Button variant="outline" size="sm" onClick={() => setDeleteOpen(true)} className="gap-1.5 text-destructive hover:text-destructive">
              <Trash2 className="h-3.5 w-3.5" /> 删除结果
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={openHistory} disabled={status === 'running'} className="gap-1.5">
            <History className="h-3.5 w-3.5" /> 历史记录
          </Button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* 左：原文档预览 */}
        <div className="flex w-1/2 flex-col border-r border-border/50">
          <div className="border-b border-border/50 bg-muted/40 px-4 py-2.5">
            <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <FileText className="h-3.5 w-3.5" /> 原始文档预览
            </span>
          </div>
          <div className="flex-1 overflow-auto bg-muted/10">
            {pdfUrl ? (
              <object data={pdfUrl} type="application/pdf" className="h-full w-full">
                <p className="py-16 text-center text-sm text-muted-foreground">当前浏览器无法预览 PDF</p>
              </object>
            ) : (
              <div className="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
                <FileText className="h-10 w-10 opacity-50" />
                <p className="text-sm">该文件类型暂不支持在线预览</p>
              </div>
            )}
          </div>
        </div>

        {/* 右：Schema + 进度 + 结果 */}
        <div className="flex w-1/2 flex-col overflow-hidden">
          <div className="border-b border-border/50 bg-card/50 p-4">
            <p className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Braces className="h-4 w-4 text-primary" /> 选择抽取 Schema
            </p>
            {schemas.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                暂无可用 Schema，请先创建抽取 Schema
              </p>
            ) : (
              <div className="mb-4 grid grid-cols-2 gap-3">
                {schemas.map((schema) => (
                  <div
                    key={schema.id}
                    onClick={() => { if (status !== 'running') setSelectedSchemaId(schema.id) }}
                    className={`relative cursor-pointer rounded-xl border-2 p-3.5 transition-all ${selectedSchemaId === schema.id ? 'border-primary bg-primary/5' : 'border-border/60 hover:border-primary/40'}`}
                  >
                    <div className="flex items-center gap-2">
                      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${selectedSchemaId === schema.id ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'}`}>
                        <Braces className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{schema.name}</p>
                        <p className="text-xs text-muted-foreground">{schema.categories?.length ?? 0} 类别</p>
                      </div>
                    </div>
                    {selectedSchemaId === schema.id && <CheckCircle2 className="absolute right-2 top-2 h-4 w-4 text-primary" />}
                  </div>
                ))}
              </div>
            )}
            <Button
              className="w-full gap-2"
              disabled={!selectedSchemaId || status === 'running' || !canManage}
              onClick={start}
            >
              {status === 'running' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              {status === 'running' ? '抽取中...' : status === 'completed' || status === 'failed' ? '重新抽取' : '开始抽取'}
            </Button>
          </div>

          <div className="flex-1 space-y-4 overflow-auto p-4">
            {status !== 'idle' && (
              <div className="rounded-xl border border-border/60 bg-card p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${status === 'running' ? 'bg-primary/15 text-primary animate-pulse' : status === 'completed' ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger'}`}>
                      {status === 'running' ? <Loader2 className="h-4 w-4 animate-spin" /> : status === 'completed' ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                    </div>
                    <div>
                      <p className="text-sm font-medium">{progressMessage || (status === 'completed' ? '抽取完成' : status === 'failed' ? '抽取失败' : '抽取进行中...')}</p>
                      {result?.schema_name && <p className="text-xs text-muted-foreground">{result.schema_name} · {result.categories.length} 个类别</p>}
                    </div>
                  </div>
                  <span className={`rounded-lg px-2 py-1 text-sm font-semibold ${status === 'running' ? 'bg-primary/10 text-primary' : status === 'completed' ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                    {progress}%
                  </span>
                </div>
                <div className="mb-4 h-2 overflow-hidden rounded-full bg-muted/80">
                  <div className={`h-full rounded-full transition-all duration-500 ${status === 'failed' ? 'bg-gradient-to-r from-danger to-danger/70' : 'bg-gradient-to-r from-primary to-primary/80'}`} style={{ width: `${progress}%` }} />
                </div>
                <div className="flex items-center">
                  {STEPS.map((step) => (
                    <div key={step.id} className="flex flex-1 flex-col items-center gap-1.5">
                      <div className={`flex h-7 w-7 items-center justify-center rounded-full border-2 ${currentStep >= step.id ? 'border-primary bg-primary text-primary-foreground' : 'border-muted bg-muted/50 text-muted-foreground'}`}>
                        {currentStep > step.id ? <CheckCircle2 className="h-3.5 w-3.5" /> : <step.icon className="h-3.5 w-3.5" />}
                      </div>
                      <span className={`text-[10px] ${currentStep >= step.id ? 'text-foreground' : 'text-muted-foreground'}`}>{step.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <Card>
              <CardContent className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/15 text-primary"><Braces className="h-3.5 w-3.5" /></div>
                    抽取结果
                    {(result?.categories.length ?? 0) > 0 && (
                      <Badge variant="secondary" className="gap-1 text-[10px] bg-primary/10 text-primary border-primary/20">
                        <Database className="h-3 w-3" /> {result!.categories.length} 类别 · {totalRecords} 记录
                      </Badge>
                    )}
                  </div>
                  {(result?.categories.length ?? 0) > 0 && (
                    <div className="flex gap-1">
                      <button onClick={() => setViewMode('table')} className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] ${viewMode === 'table' ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border/60 text-muted-foreground'}`}>
                        <Table className="h-3.5 w-3.5" /> 表格视图
                      </button>
                      <button onClick={() => setViewMode('json')} className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] ${viewMode === 'json' ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border/60 text-muted-foreground'}`}>
                        <Braces className="h-3.5 w-3.5" /> JSON 视图
                      </button>
                    </div>
                  )}
                </div>

                {!result && status === 'idle' && (
                  <div className="flex flex-col items-center gap-2 py-12 text-center">
                    <Braces className="h-8 w-8 text-muted-foreground/50" />
                    <p className="text-sm font-medium">暂无抽取结果</p>
                    <p className="text-xs text-muted-foreground">选择 Schema 后点击「开始抽取」</p>
                  </div>
                )}
                {status === 'running' && !result && (
                  <div className="flex flex-col items-center gap-3 py-12 text-muted-foreground">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    <p className="text-sm font-medium">正在抽取，请稍候...</p>
                    <p className="text-xs">AI 正在分析文档并提取结构化数据</p>
                  </div>
                )}
                {recall && (
                  <div className="mb-3 rounded-xl border border-primary/15 bg-primary/5 p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-semibold text-primary-strong">召回统计</span>
                      <Badge variant="secondary" className="text-[10px] bg-primary/10 text-primary border-primary/20">{recall.mode === 'strict' ? '严格' : recall.mode === 'off' ? '关闭' : '宽松'}</Badge>
                      <span className="text-muted-foreground">参与 {recall.participated ?? 0} · 保留 {recall.kept ?? 0} · 剔除 {recall.skipped_count ?? 0}</span>
                    </div>
                    {recall.score_bands && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(recall.score_bands).map(([k, v]) => (
                          <Badge key={k} variant="outline" className="text-[10px]">{k}: {v}</Badge>
                        ))}
                      </div>
                    )}
                    {skipped.length > 0 && (
                      <div className="mt-2 space-y-1 border-t border-primary/10 pt-2">
                        {skipped.map((s, i) => (
                          <p key={i} className="text-[11px] leading-snug text-muted-foreground">· {s.feature}：{s.reason}{s.score != null ? `（score=${Number(s.score).toFixed(3)}）` : ''}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {result && viewMode === 'table' && displayCategories.length > 0 && (
                  <div className="space-y-2">
                    {displayCategories.map((cat, catIdx) => {
                      const headers = headersOf(cat)
                      const expanded = expandedCats.has(cat.feature)
                      return (
                        <div key={cat.feature} className="overflow-hidden rounded-xl border border-border/60">
                          <div className="flex items-center gap-3 px-3.5 py-3">
                            <button
                              onClick={() => setExpandedCats((st) => { const n = new Set(st); if (n.has(cat.feature)) n.delete(cat.feature); else n.add(cat.feature); return n })}
                              className="flex min-w-0 flex-1 items-center gap-3 text-left"
                            >
                              <ChevronRight className={`h-4 w-4 text-primary transition-transform ${expanded ? 'rotate-90' : ''}`} />
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-sm font-semibold">{cat.feature}</p>
                                <p className="text-xs text-muted-foreground">{(cat.records || []).length} 条记录</p>
                              </div>
                              <div className="flex items-center gap-1.5">
                                {cat.hit_score != null && <Badge variant="outline" className="text-[10px]">{cat.hit_score.toFixed(3)}</Badge>}
                                {cat.retried && (
                                  <Badge variant="outline" className="text-[10px] text-warning border-warning/30 bg-warning/5" title={cat.retry?.records != null ? `重排重试后出 ${cat.retry.records} 条` : '重排重试后仍无记录'}>
                                    <Sparkles className="mr-1 h-2.5 w-2.5" /> 重排重试
                                  </Badge>
                                )}
                                <Badge variant="secondary" className="text-[10px]">{headers.length} 字段</Badge>
                              </div>
                            </button>
                            {canManage && (
                              <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive hover:text-destructive" title="删除该类型" onClick={() => setDeleteCatTarget(catIdx)}>
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                          {expanded && (
                            <div className="border-t border-border/50">
                              {canManage && (
                                <div className="flex justify-end bg-muted/20 px-3 py-1.5">
                                  <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]" onClick={() => addRecord(catIdx)}>
                                    <Plus className="h-3 w-3" /> 新增记录
                                  </Button>
                                </div>
                              )}
                              <div className="overflow-x-auto">
                                <table className="w-full min-w-max border-collapse text-xs">
                                  <thead>
                                    <tr className="bg-muted/50">
                                      {headers.map((h) => <th key={h} className="whitespace-nowrap border-b border-border/40 px-3 py-2 text-left font-semibold text-muted-foreground">{h}</th>)}
                                      {canManage && <th className="w-10 border-b border-border/40 px-2 py-2" />}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {(cat.records || []).map((rec, ri) => (
                                      <tr key={ri} className="hover:bg-primary/[0.03]">
                                        {headers.map((h) => (
                                          <td key={h} className="border-b border-border/30 px-1 py-0.5 align-top">
                                            {canManage ? (
                                              <input
                                                value={cellValue(rec[h])}
                                                onChange={(e) => updateCell(catIdx, ri, h, e.target.value)}
                                                className="w-full min-w-[90px] rounded border border-transparent bg-transparent px-1.5 py-1.5 outline-none transition-colors hover:border-border/60 focus:border-primary/50 focus:bg-card"
                                              />
                                            ) : (
                                              <span className="block px-1.5 py-1.5">{cellValue(rec[h])}</span>
                                            )}
                                          </td>
                                        ))}
                                        {canManage && (
                                          <td className="border-b border-border/30 px-1 py-1 text-center">
                                            <button
                                              className="rounded p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                                              title="删除该记录"
                                              onClick={() => deleteRecord(catIdx, ri)}
                                            >
                                              <Trash2 className="h-3.5 w-3.5" />
                                            </button>
                                          </td>
                                        )}
                                      </tr>
                                    ))}
                                    {(cat.records || []).length === 0 && (
                                      <tr>
                                        <td className="px-3 py-6 text-center text-muted-foreground" colSpan={headers.length + (canManage ? 1 : 0)}>
                                          {canManage ? '该类别暂无记录，可点击上方「新增记录」添加' : '该类别无记录'}
                                        </td>
                                      </tr>
                                    )}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
                {result && viewMode === 'json' && (result.categories?.length ?? 0) > 0 && (
                  <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-xl border border-border/50 bg-muted/40 p-4 font-mono text-xs">{JSON.stringify(draftCategories ?? result, null, 2)}</pre>
                )}
                {result && status === 'failed' && (
                  <div className="rounded-xl border border-warning/30 bg-warning/5 p-3.5">
                    <p className="flex items-center gap-2 text-xs font-semibold text-warning"><AlertCircle className="h-3.5 w-3.5" /> 抽取失败：{result.error?.message || '未知错误'}</p>
                    <p className="mt-1 text-xs text-muted-foreground">可点击上方「重新抽取」再次尝试。</p>
                  </div>
                )}
                {missingFields.length > 0 && (
                  <div className="mt-4 rounded-xl border border-warning/30 bg-warning/5 p-3.5">
                    <p className="mb-2 flex items-center gap-2 text-xs font-semibold text-warning">
                      <AlertCircle className="h-3.5 w-3.5" /> 缺失字段提示（{missingFields.length}）
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {missingFields.map((f) => <Badge key={f} variant="outline" className="text-[10px] text-warning border-warning/30">{f}</Badge>)}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      {/* 右下角保存（人工编辑结果后） */}
      {dirty && canManage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-xl border border-border/60 bg-card p-2 shadow-lg">
          <Button onClick={saveDraft} disabled={savingResult} className="gap-1.5" data-testid="btn-save-result">
            {savingResult ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {savingResult ? '保存中...' : '保存修改'}
          </Button>
          <Button variant="ghost" size="sm" onClick={cancelDraft}>取消</Button>
        </div>
      )}

      {/* 删除类型确认 */}
      <Dialog open={deleteCatTarget != null} onOpenChange={(o) => { if (!o) setDeleteCatTarget(null) }} title="删除类型" className="max-w-md">
        <p className="text-sm text-muted-foreground">
          确定删除类型「{deleteCatTarget != null ? displayCategories[deleteCatTarget]?.feature : ''}」及其全部记录吗？保存后生效。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleteCatTarget(null)}>取消</Button>
          <Button variant="destructive" onClick={() => { if (deleteCatTarget != null) deleteCategory(deleteCatTarget) }} className="gap-1.5">
            <Trash2 className="h-3.5 w-3.5" /> 删除
          </Button>
        </div>
      </Dialog>

      <Dialog open={historyOpen} onOpenChange={(o) => { if (!o) setHistoryOpen(false) }} title="抽取历史记录" className="max-w-2xl">
        {historyLoading ? (
          <div className="space-y-3"><Skeleton className="h-16 w-full rounded-xl" /><Skeleton className="h-16 w-full rounded-xl" /></div>
        ) : historyItems.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <Clock className="h-8 w-8 text-muted-foreground/50" />
            <p className="text-sm font-medium">暂无抽取记录</p>
            <p className="text-xs text-muted-foreground">该文档尚未进行过抽取</p>
          </div>
        ) : (
          <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
            {historyItems.map((item) => (
              <div key={item.id} onClick={() => viewHistoryItem(item)} className="flex cursor-pointer items-center justify-between rounded-xl border p-3.5 transition-all hover:-translate-y-0.5 hover:shadow-md">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary"><Braces className="h-4 w-4" /></div>
                  <div>
                    <p className="text-sm font-medium">{item.schema_name || '未知 Schema'}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{item.categories.length} 个类别 · 点击查看此版本结果</p>
                  </div>
                </div>
                <span className="flex items-center gap-1 text-xs text-muted-foreground"><Clock className="h-3 w-3" /> {new Date(item.extracted_at).toLocaleString('zh-CN')}</span>
              </div>
            ))}
          </div>
        )}
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={(o) => { if (!o) setDeleteOpen(false) }} title="删除抽取结果" description="将删除最新结果与全部历史版本，不可恢复。确认继续？">
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button>
          <Button variant="destructive" onClick={removeResult} disabled={deleting} className="gap-1.5">
            {deleting && <Loader2 className="h-4 w-4 animate-spin" />} 删除
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
