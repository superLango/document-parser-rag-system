import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Braces, ChevronLeft, ChevronRight, FileText, Layers, Loader2, MessageSquareText, RefreshCcw } from 'lucide-react'
import { documentsApi } from '@/api/modules/documents'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'
import { PROCESS_LABELS, TERMINAL_STATUSES, pageProgressText, progressPercentForDoc } from '@/lib/documentStatus'
import { cn } from '@/lib/utils'

interface ViewerBlock {
  type: string
  bbox: [number, number, number, number]
  order: number
  content?: string
  [key: string]: unknown
}

interface ViewerPage {
  page_index: number
  blocks: ViewerBlock[]
}

interface ViewerLayout {
  page_count: number
  pages: ViewerPage[]
  [key: string]: unknown
}

function splitMarkdownByPage(md: string): string[] {
  const parts = md.split(/<!-- page: (\d+) -->/g)
  const pages: string[] = []
  for (let i = 1; i < parts.length; i += 2) {
    pages.push(parts[i + 1] ?? '')
  }
  return pages
}

type TabKey = 'blocks' | 'md' | 'json'

const POLL_INTERVAL = 1500

export default function KbDocumentViewerPage() {
  const { kbId = '', docId = '' } = useParams()
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [page, setPage] = useState(1)
  const [activeBlock, setActiveBlock] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('blocks')
  const [pageUrl, setPageUrl] = useState<string | null>(null)
  const [originalUrl, setOriginalUrl] = useState<string | null>(null)
  const [reparsing, setReparsing] = useState(false)
  const reparseSawNonTerminal = useRef(false)
  const pageUrlRef = useRef<string | null>(null)
  const originalUrlRef = useRef<string | null>(null)

  const { data: doc } = useQuery({
    queryKey: ['doc-detail', kbId, docId],
    queryFn: () => documentsApi.get(kbId, docId),
    enabled: Boolean(kbId && docId),
  })
  const { data: layout, isLoading: layoutLoading } = useQuery({
    queryKey: ['doc-layout', kbId, docId],
    queryFn: () => documentsApi.layout(kbId, docId) as Promise<ViewerLayout>,
    enabled: Boolean(kbId && docId && doc?.status === 'completed'),
  })
  const { data: markdown } = useQuery({
    queryKey: ['doc-markdown', kbId, docId],
    queryFn: () => documentsApi.markdown(kbId, docId),
    enabled: Boolean(kbId && docId && doc?.status === 'completed'),
  })

  const completed = doc?.status === 'completed'
  const reparseable = completed || doc?.status === 'failed' || reparsing
  const pageCount = layout?.page_count ?? doc?.page_count ?? 1
  const safePage = Math.min(Math.max(page, 1), Math.max(pageCount, 1))
  const currentPage = completed ? layout?.pages?.find((p) => p.page_index === safePage) : undefined
  const blocks = currentPage?.blocks ?? []
  const mdPages = useMemo(() => (markdown ? splitMarkdownByPage(markdown) : []), [markdown])
  const currentMd = mdPages[safePage - 1] ?? ''
  const percent = progressPercentForDoc(doc?.process_status, doc?.progress_page, doc?.progress_total)
  const stageLabel = PROCESS_LABELS[doc?.process_status ?? ''] ?? '排队中'
  const pageText = pageProgressText(doc?.progress_page, doc?.progress_total)

  // 重新解析：轮询文档详情直至终态
  useEffect(() => {
    if (!reparsing) return
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ['doc-detail', kbId, docId] })
    }, POLL_INTERVAL)
    return () => window.clearInterval(timer)
  }, [reparsing, kbId, docId, queryClient])

  useEffect(() => {
    if (!reparsing || !doc) return
    if (TERMINAL_STATUSES.has(doc.status)) {
      if (!reparseSawNonTerminal.current) return
      setReparsing(false)
      void queryClient.invalidateQueries({ queryKey: ['doc-layout', kbId, docId] })
      void queryClient.invalidateQueries({ queryKey: ['doc-markdown', kbId, docId] })
      if (doc.status === 'failed') {
        toast('error', '重新解析失败', typeof doc.error === 'string' ? doc.error : '请前往任务列表查看失败原因')
      } else {
        toast('success', '重新解析完成', '已恢复版面块 / Markdown / JSON 查看')
      }
    } else {
      reparseSawNonTerminal.current = true
    }
  }, [reparsing, doc, kbId, docId, queryClient, toast])

  // 待解析/解析中：加载原始 PDF blob 供浏览器预览
  useEffect(() => {
    if (completed) return
    let cancelled = false
    documentsApi.original(kbId, docId)
      .then((url) => {
        if (cancelled) return
        if (originalUrlRef.current) URL.revokeObjectURL(originalUrlRef.current)
        originalUrlRef.current = url
        setOriginalUrl(url)
      })
      .catch(() => { if (!cancelled) setOriginalUrl(null) })
    return () => { cancelled = true }
  }, [kbId, docId, completed])

  // 完成模式：加载当前页图片
  useEffect(() => {
    if (!completed) return
    let cancelled = false
    documentsApi.page(kbId, docId, safePage)
      .then((url) => {
        if (cancelled) return
        if (pageUrlRef.current) URL.revokeObjectURL(pageUrlRef.current)
        pageUrlRef.current = url
        setPageUrl(url)
      })
      .catch(() => { if (!cancelled) setPageUrl(null) })
    return () => { cancelled = true }
  }, [kbId, docId, safePage, completed])

  useEffect(() => {
    setActiveBlock(null)
  }, [safePage])

  async function handleReparse() {
    if (reparsing) return
    reparseSawNonTerminal.current = false
    setReparsing(true)
    try {
      await documentsApi.reparse(kbId, docId)
      toast('success', '重新解析已启动', '正在重新解析，完成后自动恢复版面查看')
      void queryClient.invalidateQueries({ queryKey: ['doc-detail', kbId, docId] })
    } catch (err) {
      reparseSawNonTerminal.current = false
      setReparsing(false)
      toast('error', '重新解析失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  function prevPage() {
    if (safePage > 1) setPage(safePage - 1)
  }
  function nextPage() {
    if (safePage < pageCount) setPage(safePage + 1)
  }

  const activeBlockData = blocks.find((b) => String(b.order) === activeBlock) ?? null

  const tabs: { key: TabKey; label: string; icon: typeof Layers }[] = [
    { key: 'blocks', label: '版面块', icon: Layers },
    { key: 'md', label: 'Markdown', icon: MessageSquareText },
    { key: 'json', label: 'JSON', icon: Braces },
  ]

  return (
    <div className="flex min-h-dvh flex-col bg-background-soft">
      {/* 顶栏 */}
      <header className="sticky top-0 z-30 border-b border-border/80 bg-card/85 backdrop-blur-md">
        <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            to={`/kb/${kbId}/documents`}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-100 bg-white/80 text-primary-strong shadow-soft transition-all hover:shadow-glow"
            title="返回文档列表"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
            <FileText className="h-4 w-4" strokeWidth={1.7} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{doc?.filename ?? '文档详情'}</p>
            <p className="text-xs text-muted-foreground">
              {reparsing
                ? `重新解析中 · ${stageLabel} ${percent}%`
                : completed
                  ? `第 ${safePage} / ${pageCount} 页 · 版面块 ${blocks.length} 个`
                  : '原文档预览'}
            </p>
          </div>
          {reparseable ? (
            <Button
              variant="outline"
              size="sm"
              data-testid="viewer-reparse"
              disabled={reparsing}
              onClick={() => void handleReparse()}
            >
              {reparsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              {reparsing ? '重新解析中' : '重新解析'}
            </Button>
          ) : null}
        </div>
      </header>

      <main className="flex flex-1 flex-col gap-4 p-4 sm:p-6 lg:flex-row">
        {/* 左：原文档（完成=页面图+版面矩形；未完成=浏览器 PDF 预览） */}
        <section className="w-full lg:w-[46%]">
          <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-soft">
            <div className="border-b border-border bg-muted/40 px-4 py-2 text-sm font-medium">原文档</div>
            {completed ? (
              <>
                {/* 翻页：位于左侧源文件组件上方 */}
                <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/20 px-3 py-2" data-testid="viewer-pagination">
                  <Button variant="outline" size="sm" onClick={prevPage} disabled={safePage <= 1} data-testid="prev-page">
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                  </Button>
                  <span className="text-sm font-medium">{safePage} / {pageCount}</span>
                  <Button variant="outline" size="sm" onClick={nextPage} disabled={safePage >= pageCount} data-testid="next-page">
                    下一页
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
                <div className="relative aspect-[595/842] w-full flex-1 bg-white">
                  {pageUrl ? (
                    <>
                      <img
                        src={pageUrl}
                        alt={`第 ${safePage} 页`}
                        data-testid="viewer-page"
                        className="absolute inset-0 h-full w-full"
                      />
                      {blocks.map((b) => {
                        const [x0, y0, x1, y1] = b.bbox
                        const active = String(b.order) === activeBlock
                        return (
                          <button
                            key={String(b.order)}
                            type="button"
                            data-testid={`doc-rect-${b.order}`}
                            onClick={() => setActiveBlock(String(b.order))}
                            className={cn(
                              'absolute border-2 transition-all duration-150',
                              active
                                ? 'z-20 border-rose-500 bg-rose-400/20 shadow-[0_0_0_2px_rgba(244,63,94,0.35)]'
                                : 'z-10 border-emerald-400/70 bg-emerald-300/10 hover:border-emerald-500 hover:bg-emerald-300/20',
                            )}
                            style={{
                              left: `${x0 * 100}%`,
                              top: `${y0 * 100}%`,
                              width: `${(x1 - x0) * 100}%`,
                              height: `${(y1 - y0) * 100}%`,
                            }}
                            title={`${b.type} #${b.order}`}
                          />
                        )
                      })}
                    </>
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
                      {layoutLoading ? '页面加载中...' : '页面不可用（可能已清理）'}
                    </div>
                  )}
                </div>
              </>
            ) : originalUrl ? (
              <embed
                src={originalUrl}
                type="application/pdf"
                className="h-[calc(100vh-11rem)] w-full"
                data-testid="viewer-original"
              />
            ) : (
              <div className="flex h-[60vh] items-center justify-center text-sm text-muted-foreground">
                原文档加载中...
              </div>
            )}
          </div>
        </section>

        {/* 右：重新解析进度 / 标签页（完成模式） / 占位 */}
        {reparsing ? (
          <section
            className="flex min-w-0 flex-1 flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-emerald-200 bg-emerald-50/30 p-10 text-center"
            data-testid="viewer-progress"
          >
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm font-medium">正在重新解析</p>
            <div className="w-full max-w-sm space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{stageLabel}{pageText ? ' · ' + pageText : ''}</span>
                <span data-testid="viewer-progress-text">{percent}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted" data-testid="viewer-progress-bar">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500 transition-all duration-500"
                  style={{ width: `${percent}%` }}
                  data-testid="viewer-progress-fill"
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">解析完成后将自动恢复版面块 / Markdown / JSON 查看</p>
          </section>
        ) : completed ? (
          <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-soft lg:max-h-[calc(100dvh-8rem)]">
            <div className="flex items-center gap-1 border-b border-border bg-muted/40 px-2 py-1.5">
              {tabs.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  type="button"
                  data-testid={`tab-${key}`}
                  onClick={() => setTab(key)}
                  className={cn(
                    'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                    tab === key
                      ? 'bg-white text-primary-strong shadow-soft'
                      : 'text-muted-foreground hover:bg-muted/60',
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>

            <div className="min-h-0 flex-1 overflow-auto">
              {tab === 'blocks' ? (
                <div className="grid h-full grid-cols-2 gap-3 p-3">
                  {/* 左：版面块列表 */}
                  <div className="min-h-0 space-y-1.5 overflow-y-auto rounded-xl border border-border bg-muted/20 p-2" data-testid="blocks-container">
                    {blocks.length === 0 ? (
                      <p className="py-8 text-center text-xs text-muted-foreground">本页无版面块</p>
                    ) : (
                      blocks.map((b) => {
                        const active = String(b.order) === activeBlock
                        return (
                          <button
                            key={String(b.order)}
                            type="button"
                            data-testid={`block-${b.order}`}
                            onClick={() => setActiveBlock(String(b.order))}
                            className={cn(
                              'w-full rounded-lg border px-3 py-2 text-left transition-all',
                              active
                                ? 'border-rose-300 bg-rose-50'
                                : 'border-border bg-white/70 hover:border-emerald-300 hover:bg-emerald-50/50',
                            )}
                          >
                            <p className="text-xs font-medium">
                              <span className="text-muted-foreground">#{b.order}</span> {b.type}
                            </p>
                            <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                              [{b.bbox.map((v) => v.toFixed(2)).join(', ')}]
                            </p>
                          </button>
                        )
                      })
                    )}
                  </div>
                  {/* 右：选中块内容 */}
                  <div className="min-h-0 overflow-y-auto rounded-xl border border-border bg-white/70 p-3" data-testid="block-content">
                    {activeBlockData ? (
                      <div className="space-y-3">
                        <div className="flex items-center gap-2">
                          <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-primary">
                            #{activeBlockData.order} {activeBlockData.type}
                          </span>
                        </div>
                        <div>
                          <p className="mb-1 text-[11px] font-medium text-muted-foreground">内容</p>
                          <pre className="whitespace-pre-wrap rounded-lg bg-muted/50 p-2 font-mono text-xs leading-relaxed">
                            {activeBlockData.content || '（无文本内容）'}
                          </pre>
                        </div>
                        <div>
                          <p className="mb-1 text-[11px] font-medium text-muted-foreground">属性</p>
                          <pre className="whitespace-pre-wrap rounded-lg bg-muted/50 p-2 font-mono text-[10px] leading-relaxed">
                            {JSON.stringify(
                              {
                                type: activeBlockData.type,
                                bbox: activeBlockData.bbox,
                                confidence: activeBlockData.confidence,
                                structural: activeBlockData.structural,
                              },
                              null,
                              2,
                            )}
                          </pre>
                        </div>
                      </div>
                    ) : (
                      <p className="py-12 text-center text-xs text-muted-foreground">
                        点击左侧版面块查看该块内容
                      </p>
                    )}
                  </div>
                </div>
              ) : null}

              {tab === 'md' ? (
                <pre className="h-full whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed" data-testid="viewer-md">
                  {currentMd || '本页暂无内容'}
                </pre>
              ) : null}

              {tab === 'json' ? (
                <pre className="h-full overflow-auto p-4 font-mono text-[10px] leading-relaxed text-foreground" data-testid="viewer-json">
                  {layout ? JSON.stringify(layout, null, 2) : '加载中...'}
                </pre>
              ) : null}
            </div>
          </section>
        ) : (
          <section className="flex min-w-0 flex-1 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-emerald-200 bg-emerald-50/30 p-10 text-center">
            <FileText className="h-10 w-10 text-primary" strokeWidth={1.4} />
            <p className="text-sm font-medium">原文档预览</p>
            <p className="text-xs text-muted-foreground">
              解析完成后可查看版面块、Markdown 与版面 JSON（左侧浏览器 PDF 查看器支持原文档翻页）
            </p>
          </section>
        )}
      </main>
    </div>
  )
}
