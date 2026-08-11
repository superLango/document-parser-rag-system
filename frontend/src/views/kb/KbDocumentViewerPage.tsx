import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Braces, ChevronLeft, ChevronRight, FileText, Layers, MessageSquareText } from 'lucide-react'
import { documentsApi } from '@/api/modules/documents'
import { Button } from '@/components/ui/button'
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

export default function KbDocumentViewerPage() {
  const { kbId = '', docId = '' } = useParams()
  const [page, setPage] = useState(1)
  const [activeBlock, setActiveBlock] = useState<string | null>(null)
  const [pageUrl, setPageUrl] = useState<string | null>(null)
  const pageUrlRef = useRef<string | null>(null)

  const { data: doc } = useQuery({
    queryKey: ['doc-detail', kbId, docId],
    queryFn: () => documentsApi.get(kbId, docId),
    enabled: Boolean(kbId && docId),
  })
  const { data: layout, isLoading: layoutLoading } = useQuery({
    queryKey: ['doc-layout', kbId, docId],
    queryFn: () => documentsApi.layout(kbId, docId) as Promise<ViewerLayout>,
    enabled: Boolean(kbId && docId),
  })
  const { data: markdown } = useQuery({
    queryKey: ['doc-markdown', kbId, docId],
    queryFn: () => documentsApi.markdown(kbId, docId),
    enabled: Boolean(kbId && docId),
  })

  const pageCount = layout?.page_count ?? doc?.page_count ?? 1
  const safePage = Math.min(Math.max(page, 1), Math.max(pageCount, 1))
  const currentPage = layout?.pages?.find((p) => p.page_index === safePage)
  const blocks = currentPage?.blocks ?? []
  const mdPages = useMemo(() => (markdown ? splitMarkdownByPage(markdown) : []), [markdown])
  const currentMd = mdPages[safePage - 1] ?? ''

  useEffect(() => {
    let cancelled = false
    documentsApi.page(kbId, docId, safePage)
      .then((url) => {
        if (cancelled) return
        if (pageUrlRef.current) URL.revokeObjectURL(pageUrlRef.current)
        pageUrlRef.current = url
        setPageUrl(url)
      })
      .catch(() => {
        if (!cancelled) setPageUrl(null)
      })
    return () => { cancelled = true }
  }, [kbId, docId, safePage])

  useEffect(() => {
    setActiveBlock(null)
  }, [safePage])

  function prevPage() {
    if (safePage > 1) setPage(safePage - 1)
  }
  function nextPage() {
    if (safePage < pageCount) setPage(safePage + 1)
  }


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
              第 {safePage} / {pageCount} 页 · 版面块 {blocks.length} 个
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={prevPage} disabled={safePage <= 1}>
              <ChevronLeft className="h-4 w-4" />
              上一页
            </Button>
            <span className="min-w-16 text-center text-sm font-medium">{safePage} / {pageCount}</span>
            <Button variant="outline" size="sm" onClick={nextPage} disabled={safePage >= pageCount}>
              下一页
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      {/* 主体：左文档 + 右三栏 */}
      <main className="flex flex-1 flex-col gap-4 p-4 sm:p-6 lg:flex-row">
        {/* 左：原文档 + 版面矩形 */}
        <section className="w-full lg:w-[42%]">
          <div className="overflow-hidden rounded-2xl border border-border bg-white shadow-soft">
            <div className="border-b border-border bg-muted/40 px-4 py-2 text-sm font-medium">原文档</div>
            <div className="relative aspect-[595/842] w-full bg-white">
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
          </div>
        </section>

        {/* 右：三栏 */}
        <section className="grid min-w-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-3">
          {/* 版面块 */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
            <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm font-medium">
              <Layers className="h-4 w-4 text-primary" />
              版面块
            </div>
            <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3" data-testid="blocks-container">
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
          </div>

          {/* Markdown（按页） */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
            <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm font-medium">
              <MessageSquareText className="h-4 w-4 text-primary" />
              Markdown
            </div>
            <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed" data-testid="viewer-md">
              {currentMd || '本页暂无内容'}
            </pre>
          </div>

          {/* 原始版面 JSON */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
            <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm font-medium">
              <Braces className="h-4 w-4 text-primary" />
              版面 JSON
            </div>
            <pre className="min-h-0 flex-1 overflow-auto p-4 font-mono text-[10px] leading-relaxed text-foreground" data-testid="viewer-json">
              {layout ? JSON.stringify(layout, null, 2) : '加载中...'}
            </pre>
          </div>
        </section>
      </main>
    </div>
  )
}
