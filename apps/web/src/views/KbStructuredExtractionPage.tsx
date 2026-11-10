import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Braces, Calendar, CheckCircle2, Clock, FileText, History, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import { extractionApi, type ExtractableDocument, type ExtractionHistoryItem } from '@/api/modules/extraction'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { useModule } from './ModuleLayout'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return value
  }
}

export default function KbStructuredExtractionPage() {
  const { module, canManage } = useModule()
  const navigate = useNavigate()
  const { toast } = useToast()

  const [loading, setLoading] = useState(true)
  const [documents, setDocuments] = useState<ExtractableDocument[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyItems, setHistoryItems] = useState<ExtractionHistoryItem[]>([])
  const [selectedDoc, setSelectedDoc] = useState<ExtractableDocument | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await extractionApi.listDocuments(module.key)
      setDocuments(res.items)
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [module.key, toast])

  useEffect(() => { void load() }, [load])

  async function openHistory(doc: ExtractableDocument) {
    setSelectedDoc(doc)
    setHistoryOpen(true)
    setHistoryLoading(true)
    setHistoryItems([])
    try {
      const res = await extractionApi.history(module.key, doc.id)
      setHistoryItems(res.items)
    } catch (err) {
      toast('error', '加载历史失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setHistoryLoading(false)
    }
  }

  function goDetail(doc: ExtractableDocument) {
    navigate(`/standard/extraction/${doc.id}`)
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="功能模块"
        title="结构化抽取"
        description="选择已解析文档，生成字段级结构化结果并导出"
        actions={
          <>
            <Badge variant="secondary" className="gap-1.5 border border-primary/20 bg-primary/5 text-primary">
              <ShieldCheck className="h-3.5 w-3.5" /> 按模块隔离
            </Badge>
            <Button variant="outline" size="sm" onClick={load} className="gap-1.5">
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> 刷新
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="p-0">
          <div className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Braces className="h-4 w-4 text-primary" />
              可抽取文档
              {!loading ? (
                <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums text-muted-foreground">
                  {documents.length}
                </span>
              ) : null}
            </div>
            <span className="text-[11px] text-muted-foreground">仅显示已完成解析的文档</span>
          </div>
          {loading ? (
            <div className="divide-y divide-border/50">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-4 p-4">
                  <Skeleton className="h-11 w-11 rounded-xl" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-3 w-1/4" />
                  </div>
                  <Skeleton className="h-9 w-20" />
                  <Skeleton className="h-9 w-24" />
                </div>
              ))}
            </div>
          ) : documents.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-20 text-center">
              <FileText className="h-8 w-8 text-muted-foreground/50" />
              <p className="text-sm font-medium">无可抽取文档</p>
              <p className="text-xs text-muted-foreground">请先上传文档并完成 OCR 解析与索引</p>
            </div>
          ) : (
            <div className="divide-y divide-border/50">
              {documents.map((doc) => (
                <div key={doc.id} className="group flex items-center gap-4 p-4 transition-colors hover:bg-muted/40">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium" title={doc.filename}>{doc.filename}</p>
                      <Badge variant="secondary" className="gap-1 border px-2 py-0.5 text-[10px] bg-success/10 text-success border-success/30">
                        <CheckCircle2 className="h-3 w-3" /> 已解析
                      </Badge>

                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      <span>{formatSize(doc.file_size)}</span>
                      <span className="opacity-40">·</span>
                      <span>{doc.page_count} 页</span>
                      {doc.latest_schema_name && (
                        <span className="inline-flex items-center gap-1">
                          <Braces className="h-3 w-3" /> {doc.latest_schema_name}
                        </span>
                      )}
                      {doc.history_count > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <History className="h-3 w-3" /> {doc.history_count} 个历史版本
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="hidden shrink-0 items-center gap-1.5 text-xs text-muted-foreground sm:flex">
                    <Calendar className="h-3 w-3" />
                    <span>{formatDate(doc.updated_at)}</span>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Button variant="ghost" size="sm" disabled={doc.history_count === 0} onClick={() => openHistory(doc)} className="gap-1.5">
                      <History className="h-3.5 w-3.5" /> 历史
                    </Button>
                    {canManage && (
                      <Button size="sm" onClick={() => goDetail(doc)} className="gap-1.5" data-testid={`btn-extract-${doc.id}`}>
                        <Play className="h-3.5 w-3.5" /> 抽取
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={historyOpen} onOpenChange={(o) => { if (!o) setHistoryOpen(false) }} title="抽取历史" className="max-w-lg">
        {selectedDoc && (
          <p className="-mt-2 mb-4 flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm">
            <FileText className="h-4 w-4 text-primary/70" />
            <span className="truncate font-medium">{selectedDoc.filename}</span>
          </p>
        )}
        {historyLoading ? (
          <div className="space-y-3"><Skeleton className="h-16 w-full rounded-lg" /><Skeleton className="h-16 w-full rounded-lg" /></div>
        ) : historyItems.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <Clock className="h-8 w-8 text-muted-foreground/50" />
            <p className="text-sm font-medium">暂无抽取记录</p>
            <p className="text-xs text-muted-foreground">该文档尚未进行过抽取</p>
          </div>
        ) : (
          <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
            {historyItems.map((item, idx) => (
              <div key={idx} className="flex items-center justify-between rounded-xl border border-border/60 p-3.5">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
                    <Braces className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">{item.schema_name || '未知 Schema'}</p>
                    <p className="text-xs text-muted-foreground">{formatDate(item.extracted_at)}</p>
                  </div>
                </div>
                <Badge className="gap-1 border-0 bg-primary text-primary-foreground">最新</Badge>
              </div>
            ))}
          </div>
        )}
      </Dialog>
    </div>
  )
}
