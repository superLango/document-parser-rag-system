import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ChevronDown,
  FileText,
  Search,
  Sparkles,
  Table2,
  X,
} from 'lucide-react'
import { documentsApi } from '@/api/modules/documents'
import { indexingApi } from '@/api/modules/indexing'
import type { SearchHit } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/PageHeader'
import { cn } from '@/lib/utils'
import { useKbDetail } from './KbDetailLayout'

const SUMMARY_LIMIT = 320

function formatScore(score: number): string {
  return score.toFixed(4)
}

function HitCard({ hit, docNames }: { hit: SearchHit; docNames: Record<string, string> }) {
  const [expanded, setExpanded] = useState(false)
  const [showParent, setShowParent] = useState(false)
  const summary = expanded ? hit.content : hit.content.slice(0, SUMMARY_LIMIT)
  const truncated = hit.content.length > SUMMARY_LIMIT

  return (
    <Card className="overflow-hidden border-border/80 shadow-soft transition-shadow hover:shadow-glow">
      <CardContent className="space-y-3 p-4 sm:p-5">
        {/* 面包屑 + 元信息 */}
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="font-mono text-[11px]">
            {hit.hierarchy_path || '文档根节点'}
          </Badge>
          {hit.has_table && (
            <Badge variant="outline" className="gap-1 text-[11px]">
              <Table2 className="h-3 w-3" /> 表格
            </Badge>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            页码 {hit.source_pages.length ? hit.source_pages.join(', ') : '—'}
          </span>
        </div>

        {hit.title && <h3 className="text-sm font-semibold text-foreground">{hit.title}</h3>}

        {/* 内容摘要/全文 */}
        <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/85">
          {summary}
          {truncated && !expanded && '…'}
        </p>
        {truncated && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-primary hover:text-primary-hover"
          >
            {expanded ? '收起' : '展开全文'}
          </button>
        )}

        {/* 溯源上下文（父块全文） */}
        {hit.parent_text && (
          <div className="rounded-xl border border-muted bg-muted/40 p-3">
            <button
              type="button"
              onClick={() => setShowParent((v) => !v)}
              className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showParent && 'rotate-180')} />
              章节上下文（{hit.parent_text.length} 字符）
            </button>
            {showParent && (
              <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
                {hit.parent_text}
              </p>
            )}
          </div>
        )}

        {/* 底部：来源文档 + 分数 */}
        <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <FileText className="h-3.5 w-3.5" />
            {docNames[hit.document_id] || '未知文档'}
          </span>
          <span className="ml-auto inline-flex items-center gap-1 font-mono">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            相关度 {formatScore(hit.score)}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

export default function KbVectorSearchPage() {
  const { kb } = useKbDetail()
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [documentId, setDocumentId] = useState<string>('all')
  const [onlyTable, setOnlyTable] = useState(false)
  const [topK, setTopK] = useState(10)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState<number | null>(null)

  const docs = useQuery({
    queryKey: ['kb-docs-select', kb.id],
    queryFn: () => documentsApi.list(kb.id, { page_size: 100 }),
    enabled: Boolean(kb.id),
    staleTime: 30_000,
  })
  const docNames = useMemo(() => {
    const map: Record<string, string> = {}
    for (const d of docs.data?.items ?? []) map[d.id] = d.filename
    return map
  }, [docs.data])

  const [results, setResults] = useState<SearchHit[]>([])

  async function runSearch(rawQuery?: string) {
    const q = (rawQuery ?? query).trim()
    if (!q) return
    setLoading(true)
    setError(null)
    const started = performance.now()
    try {
      const filters =
        documentId !== 'all' || onlyTable
          ? {
              document_id: documentId !== 'all' ? documentId : null,
              has_table: onlyTable ? true : null,
            }
          : null
      const resp = await indexingApi.search(kb.id, q, topK, filters ?? undefined)
      setResults(resp.items)
      setSubmitted(q)
      setElapsed(performance.now() - started)
    } catch (err) {
      setError(err instanceof Error ? err.message : '检索失败，请稍后重试')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="知识库"
        title="向量搜索"
        description="双向量语义检索 + 词法 BM25 混合召回（RRF 融合），支持文档/表格过滤与溯源。"
      />

      {/* 搜索区 */}
      <Card className="border-border/80 shadow-soft">
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                placeholder="输入检索内容，例如：抗拉强度 715、晶间腐蚀试验……"
                className="h-11 pl-10 pr-9"
                disabled={loading}
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('')
                    setResults([])
                    setSubmitted('')
                  }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  aria-label="清空"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <Button
              onClick={() => runSearch()}
              disabled={loading || !query.trim()}
              className="h-11 gap-2 px-6"
            >
              <Search className="h-4 w-4" />
              {loading ? '检索中…' : '检索'}
            </Button>
          </div>

          {/* 过滤与参数 */}
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
              disabled={loading}
              className="w-full sm:w-56"
            >
              <option value="all">全部文档</option>
              {(docs.data?.items ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
            </Select>

            <Select
              value={String(topK)}
              onChange={(e) => setTopK(Number(e.target.value))}
              disabled={loading}
              className="w-28"
            >
              {[5, 10, 20, 30].map((n) => (
                <option key={n} value={String(n)}>
                  返回 {n} 条
                </option>
              ))}
            </Select>

            <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={onlyTable}
                onChange={(e) => setOnlyTable(e.target.checked)}
                className="h-4 w-4 rounded border-input accent-primary"
                disabled={loading}
              />
              仅表格块
            </label>
          </div>
        </CardContent>
      </Card>

      {/* 结果区 */}
      {error && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-center gap-3 p-4 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="flex-1">{error}</span>
            <Button variant="outline" size="sm" onClick={() => runSearch()}>
              重试
            </Button>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40 w-full rounded-2xl" />
          ))}
        </div>
      )}

      {!loading && !error && submitted && results.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-16 text-center">
            <Search className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-sm font-medium">未找到相关结果</p>
            <p className="max-w-md text-xs text-muted-foreground">
              可尝试更换关键词、减少过滤条件，或确认文档已完成索引。
            </p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && results.length > 0 && (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">
            查询「{submitted}」共命中 {results.length} 条
            {elapsed !== null && ` · ${elapsed.toFixed(0)} ms`}
          </p>
          <div className="space-y-4">
            {results.map((hit) => (
              <HitCard key={hit.chunk_id} hit={hit} docNames={docNames} />
            ))}
          </div>
        </div>
      )}

      {!loading && !error && !submitted && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-secondary text-primary">
              <Sparkles className="h-7 w-7" strokeWidth={1.5} />
            </span>
            <p className="text-sm font-medium">输入关键词开始检索</p>
            <p className="max-w-md text-xs leading-5 text-muted-foreground">
              系统将同时执行语义向量检索（标题 + 内容双路）与 jieba 词法检索，并经 RRF 融合排序。
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
