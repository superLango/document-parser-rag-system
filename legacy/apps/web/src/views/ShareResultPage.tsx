import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Braces, ChevronRight, Download, FileText, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

interface SharedCategory {
  feature: string
  fields?: string[]
  records: Record<string, unknown>[]
  missing_fields: string[]
  hit_count: number
}

interface SharedBundle {
  document: { id: string; file_name: string; title: string | null; standard_no: string | null }
  schema?: {
    schema_name: string
    categories: SharedCategory[]
    summary: Record<string, unknown>
  }
}

function cellText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export default function ShareResultPage() {
  const { token } = useParams<{ token: string }>()
  const [bundle, setBundle] = useState<SharedBundle | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    if (!token) return
    let alive = true
    fetch(`/v1/share/${token}`, { headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(response.status === 401 ? '链接已失效或已过期' : `加载失败（${response.status}）`)
        }
        return response.json() as Promise<SharedBundle>
      })
      .then((payload) => {
        if (alive) setBundle(payload)
      })
      .catch((err: Error) => {
        if (alive) setError(err.message)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [token])

  async function download(format: string) {
    if (!token) return
    const response = await fetch(`/v1/share/${token}/export?format=${format}`)
    if (!response.ok) {
      setError(`导出失败（${response.status}）`)
      return
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${bundle?.document.id ?? 'result'}-${format}.${format === 'hanson' ? 'json' : format}`
    link.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background-soft">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    )
  }

  if (error || !bundle) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-2 bg-background-soft text-center">
        <p className="text-sm font-medium text-destructive">{error || '无法加载分享结果'}</p>
        <p className="text-xs text-muted-foreground">请向分享者确认链接是否仍在有效期内</p>
      </div>
    )
  }

  const categories = bundle.schema?.categories ?? []

  return (
    <div className="min-h-dvh bg-background-soft">
      <header className="border-b border-border/80 bg-card/85 px-4 py-4 backdrop-blur sm:px-8">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-widest text-primary-strong">
              只读分享
            </p>
            <h1 className="flex items-center gap-2 truncate font-display text-lg font-semibold">
              <FileText className="h-4 w-4 text-primary" />
              {bundle.document.title || bundle.document.file_name}
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {bundle.document.standard_no || '—'} · {bundle.schema?.schema_name || '产品标准抽取模板'}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(['hanson', 'json', 'csv', 'xlsx'] as const).map((format) => (
              <Button
                key={format}
                size="sm"
                variant="outline"
                onClick={() => void download(format)}
                className="gap-1.5"
              >
                <Download className="h-3.5 w-3.5" />
                {format === 'hanson' ? 'Schema JSON' : format.toUpperCase()}
              </Button>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-3 p-4 sm:p-8">
        {categories.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-sm text-muted-foreground">
              暂无结构化结果
            </CardContent>
          </Card>
        ) : (
          categories.map((category) => {
            const isOpen = expanded[category.feature] ?? true
            const headers = category.fields?.length
              ? category.fields
              : Array.from(
                  new Set(category.records.flatMap((record) => Object.keys(record))),
                )
            return (
              <Card key={category.feature} className="overflow-hidden">
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((prev) => ({ ...prev, [category.feature]: !isOpen }))
                  }
                  className="flex w-full items-center gap-3 px-4 py-3 text-left"
                >
                  <ChevronRight className={`h-4 w-4 text-primary transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{category.feature}</span>
                    <span className="block text-xs text-muted-foreground">
                      {category.records.length} 条记录
                    </span>
                  </span>
                  {category.missing_fields.length > 0 ? (
                    <Badge variant="warning" className="text-[10px]">
                      缺失 {category.missing_fields.length}
                    </Badge>
                  ) : (
                    <Badge variant="success" className="text-[10px]">完整</Badge>
                  )}
                </button>
                {isOpen ? (
                  <div className="overflow-x-auto border-t border-border/50">
                    <table className="w-full min-w-max border-collapse text-xs">
                      <thead>
                        <tr className="bg-muted/50">
                          {headers.map((header) => (
                            <th
                              key={header}
                              className="whitespace-nowrap border-b border-border/40 px-3 py-2 text-left font-semibold text-muted-foreground"
                            >
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {category.records.map((record, index) => (
                          <tr key={index}>
                            {headers.map((header) => (
                              <td key={header} className="border-b border-border/30 px-3 py-1.5">
                                {cellText(record[header]) || (
                                  <span className="text-muted-foreground/40">—</span>
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </Card>
            )
          })
        )}
        <p className="flex items-center justify-center gap-1.5 pt-4 text-xs text-muted-foreground">
          <Braces className="h-3 w-3" /> 本页为只读分享，内容随链接有效期失效
        </p>
      </main>
    </div>
  )
}
