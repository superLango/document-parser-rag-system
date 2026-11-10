import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileText, Loader2 } from 'lucide-react'
import { getAccessToken } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

interface PreviewPage {
  page_no: number
  markdown?: string | null
  image?: string | null
}

export default function KbDocumentViewerPage() {
  const { docId } = useParams<{ docId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [pages, setPages] = useState<PreviewPage[]>([])
  const [fileName, setFileName] = useState('')
  const [pageNo, setPageNo] = useState(Number(searchParams.get('page') || 1))
  const [imageUrl, setImageUrl] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!docId) return
    let alive = true
    setLoading(true)
    fetch(`/v1/documents/${docId}/preview`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`加载失败（${response.status}）`)
        return response.json() as Promise<{ pages?: PreviewPage[] }>
      })
      .then((payload) => {
        if (!alive) return
        setPages(payload.pages || [])
        setError('')
      })
      .catch((err: Error) => {
        if (alive) setError(err.message)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    fetch(`/v1/documents/${docId}`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { file_name?: string } | null) => {
        if (alive && payload?.file_name) setFileName(payload.file_name)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [docId])

  useEffect(() => {
    if (!docId) return
    let objectUrl = ''
    let alive = true
    fetch(`/v1/documents/${docId}/pages/${pageNo}/image`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error('页面图片不可用')
        return response.blob()
      })
      .then((blob) => {
        if (!alive) return
        objectUrl = URL.createObjectURL(blob)
        setImageUrl(objectUrl)
      })
      .catch(() => {
        if (alive) setImageUrl('')
      })
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [docId, pageNo])

  const current = pages.find((page) => page.page_no === pageNo)

  function go(delta: number) {
    const next = Math.min(Math.max(1, pageNo + delta), pages.length || 1)
    setPageNo(next)
    const params = new URLSearchParams(searchParams)
    params.set('page', String(next))
    setSearchParams(params, { replace: true })
  }

  return (
    <div className="min-h-dvh bg-background-soft">
      <header className="sticky top-0 z-30 border-b border-border/80 bg-card/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-4 py-2.5 sm:px-6">
          <Link
            to="/standard/documents"
            className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-primary-strong"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> 返回文档解析
          </Link>
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileText className="h-4 w-4" />
          </span>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold" title={fileName || docId}>
            {fileName || docId}
          </h1>
          <div className="flex items-center gap-1">
            <Button size="icon" variant="ghost" onClick={() => go(-1)} disabled={pageNo <= 1} aria-label="上一页">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-16 rounded-md border border-border/70 px-2 py-1 text-center text-[11px] tabular-nums text-muted-foreground">
              {pageNo} / {pages.length || '—'}
            </span>
            <Button
              size="icon"
              variant="ghost"
              onClick={() => go(1)}
              disabled={pageNo >= pages.length}
              aria-label="下一页"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <Link
            to={`/standard/extraction/${docId}`}
            className="text-xs font-medium text-primary transition-colors hover:text-primary-strong"
          >
            结构化结果
          </Link>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1600px] gap-4 p-4 sm:p-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-border/60 px-4 py-2.5">
            <p className="text-xs font-medium text-muted-foreground">原文页面</p>
            <span className="text-[11px] tabular-nums text-muted-foreground">第 {pageNo} 页</span>
          </div>
          <CardContent className="flex min-h-[64vh] items-center justify-center bg-muted/20 p-3">
            {loading ? (
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            ) : error ? (
              <p className="text-sm text-destructive">{error}</p>
            ) : imageUrl ? (
              <img
                src={imageUrl}
                alt={`第 ${pageNo} 页`}
                className="max-h-[calc(100dvh-12rem)] w-auto rounded-lg border border-border/50 bg-white shadow-soft"
              />
            ) : (
              <p className="text-sm text-muted-foreground">该页暂无页面图片</p>
            )}
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-border/60 px-4 py-2.5">
            <p className="text-xs font-medium text-muted-foreground">页面文本</p>
            <span className="text-[11px] text-muted-foreground">OCR 结果</span>
          </div>
          <CardContent className="max-h-[calc(100dvh-12rem)] overflow-auto p-4">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-6 text-foreground">
              {current?.markdown || '（该页没有可显示的文本）'}
            </pre>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
