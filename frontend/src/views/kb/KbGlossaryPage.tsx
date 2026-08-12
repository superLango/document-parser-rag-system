import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookMarked,
  CheckCircle2,
  Database as DbIcon,
  Eye,
  Globe,
  Hand,
  Loader2,
  Plus,
  RefreshCw,
  RefreshCcw,
  Trash2,
  X,
} from 'lucide-react'
import { glossaryApi } from '@/api/modules/glossary'
import { ApiError } from '@/api/client'
import type { TermBase } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/PageHeader'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/auth'
import { useKbDetail } from './KbDetailLayout'

const SOURCE_META: Record<string, { label: string; icon: React.ReactNode; badge: string; desc: string }> = {
  manual: { label: '手动录入', icon: <Hand className="h-5 w-5" />, badge: 'bg-secondary text-primary-strong', desc: '手动添加和管理术语' },
  api: { label: '接口拉取', icon: <Globe className="h-5 w-5" />, badge: 'bg-sky-50 text-sky-600', desc: '通过HTTP API拉取数据' },
  db: { label: '数据库', icon: <DbIcon className="h-5 w-5" />, badge: 'bg-violet-50 text-violet-600', desc: '直连MySQL数据库' },
}

interface ApiParamDraft { key: string; value: string; in_location: 'path' | 'query' | 'header'; enabled: boolean }
const EMPTY_API = {
  url: '', method: 'GET' as 'GET' | 'POST', json_path: '', headersText: '', password: '',
  params: [] as ApiParamDraft[], body: '', timeout: '30',
}
const EMPTY_DB = { host: '', port: '3306', user: '', password: '', database: '', charset: 'utf8mb4', mode: 'table' as 'table' | 'sql', table: '', sql_query: '' }

export default function KbGlossaryPage() {
  const { kb } = useKbDetail()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'

  const [createOpen, setCreateOpen] = useState(false)
  const [sourceType, setSourceType] = useState<'manual' | 'api' | 'db'>('manual')
  const [submitting, setSubmitting] = useState(false)
  const [syncIds, setSyncIds] = useState<Record<string, boolean>>({})
  const [syncTarget, setSyncTarget] = useState<TermBase | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<TermBase | null>(null)
  const [deleting, setDeleting] = useState(false)

  // manual 表单
  const [manual, setManual] = useState({ name: '', description: '' })
  // api 表单
  const [apiForm, setApiForm] = useState({ ...EMPTY_API })
  const [apiTesting, setApiTesting] = useState(false)
  const [apiTest, setApiTest] = useState<{ ok: boolean; total?: number; error?: string } | null>(null)
  // db 表单
  const [dbForm, setDbForm] = useState({ ...EMPTY_DB })
  const [dbTesting, setDbTesting] = useState(false)
  const [dbPreviewing, setDbPreviewing] = useState(false)
  const [dbTables, setDbTables] = useState<string[]>([])
  const [dbTest, setDbTest] = useState<{ ok: boolean; error?: string } | null>(null)
  const [preview, setPreview] = useState<{ rows: Array<Record<string, unknown>>; columns: Array<{ name: string; type: string; label: string }> } | null>(null)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['kb-term-bases', kb.id],
    queryFn: () => glossaryApi.list(kb.id, { page_size: 50 }),
  })
  const list = useMemo(() => data?.items ?? [], [data])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['kb-term-bases', kb.id] })
    void queryClient.invalidateQueries({ queryKey: ['kb-term-base', kb.id] })
    void queryClient.invalidateQueries({ queryKey: ['kb-terms', kb.id] })
    void queryClient.invalidateQueries({ queryKey: ['kb-term-categories', kb.id] })
  }

  function openCreate() {
    setCreateOpen(true)
    setSourceType('manual')
    setManual({ name: '', description: '' })
    setApiForm({ ...EMPTY_API })
    setApiTest(null)
    setDbForm({ ...EMPTY_DB })
    setDbTables([])
    setDbTest(null)
    setPreview(null)
  }

  function buildApiConfig(): Record<string, unknown> {
    const headers: Record<string, string> = {}
    if (apiForm.headersText.trim()) {
      for (const line of apiForm.headersText.split('\n')) {
        const idx = line.indexOf(':')
        if (idx > 0) headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
      }
    }
    const cfg: Record<string, unknown> = {
      url: apiForm.url,
      method: apiForm.method,
      json_path: apiForm.json_path,
      headers,
      params: apiForm.params
        .filter((p) => p.enabled && p.key.trim())
        .map((p) => ({ key: p.key.trim(), value: p.value, in_location: p.in_location, enabled: true })),
      body: apiForm.body,
      timeout: Number(apiForm.timeout) || 30,
    }
    if (apiForm.password) cfg.password = apiForm.password
    return cfg
  }

  function addApiParam(loc: 'path' | 'query' | 'header') {
    setApiForm({ ...apiForm, params: [...apiForm.params, { key: '', value: '', in_location: loc, enabled: true }] })
  }

  function removeApiParam(idx: number) {
    setApiForm({ ...apiForm, params: apiForm.params.filter((_, i) => i !== idx) })
  }

  async function runApiTest() {
    setApiTesting(true)
    setApiTest(null)
    try {
      const cfg = buildApiConfig()
      const r = await glossaryApi.testApi(kb.id, cfg)
      setApiTest({ ok: true, total: r.total })
      setPreview({ rows: r.rows, columns: r.columns })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '测试失败'
      setApiTest({ ok: false, error: msg })
      toast('error', 'API 连接失败', msg)
    } finally {
      setApiTesting(false)
    }
  }

  async function runDbConnect() {
    setDbTesting(true)
    setDbTest(null)
    const cfg: Record<string, unknown> = {
      host: dbForm.host, port: Number(dbForm.port || 3306),
      user: dbForm.user, password: dbForm.password, database: dbForm.database,
    }
    try {
      await glossaryApi.testDb(kb.id, cfg)
      setDbTest({ ok: true })
      const tables = await glossaryApi.dbTables(kb.id, cfg)
      setDbTables(tables.tables)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '连接失败'
      setDbTest({ ok: false, error: msg })
      toast('error', '数据库连接失败', msg)
    } finally {
      setDbTesting(false)
    }
  }

  async function runDbPreview() {
    const cfg: Record<string, unknown> = {
      host: dbForm.host, port: Number(dbForm.port || 3306),
      user: dbForm.user, password: dbForm.password, database: dbForm.database,
      charset: dbForm.charset, mode: dbForm.mode, table: dbForm.table, sql_query: dbForm.sql_query,
    }
    setDbPreviewing(true)
    try {
      const r = await glossaryApi.previewSql(kb.id, cfg)
      setPreview({ rows: r.rows, columns: r.columns })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '预览失败'
      toast('error', '预览失败', msg)
    } finally {
      setDbPreviewing(false)
    }
  }

  async function submitCreate() {
    setSubmitting(true)
    try {
      let payload: Parameters<typeof glossaryApi.create>[1]
      if (sourceType === 'manual') {
        payload = { name: manual.name, description: manual.description, source_type: 'manual' }
      } else if (sourceType === 'api') {
        const cfg = buildApiConfig()
        payload = {
          name: manual.name || apiForm.url.split('/').pop() || 'API术语集',
          description: manual.description,
          source_type: 'api',
          source_config: cfg,
          columns: preview?.columns ?? [],
        }
      } else {
        const cfg: Record<string, unknown> = {
          host: dbForm.host, port: Number(dbForm.port || 3306),
          user: dbForm.user, password: dbForm.password, database: dbForm.database,
          charset: dbForm.charset, mode: dbForm.mode, table: dbForm.table, sql_query: dbForm.sql_query,
        }
        payload = {
          name: manual.name || dbForm.database || '数据库术语集',
          description: manual.description,
          source_type: 'db',
          source_config: cfg,
          columns: preview?.columns ?? [],
        }
      }
      const created = await glossaryApi.create(kb.id, payload)
      setCreateOpen(false)
      invalidate()
      if (sourceType === 'manual') {
        toast('success', '术语集已创建')
        navigate(`/kb/${kb.id}/glossary/${created.id}`)
      } else {
        toast('info', '术语集已创建，正在同步数据…')
        try {
          const syncResult = await glossaryApi.sync(kb.id, created.id)
          toast('success', `数据同步完成，导入 ${syncResult.imported} 条${syncResult.skipped ? `，跳过 ${syncResult.skipped} 行（未识别名称列）` : ''}`)
        } catch (err) {
          const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '同步失败'
          toast('error', '术语集已创建，数据同步失败', `${msg}，可在详情页手动同步`)
        } finally {
          invalidate()
          navigate(`/kb/${kb.id}/glossary/${created.id}`)
        }
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '创建失败'
      toast('error', '创建失败', msg)
    } finally {
      setSubmitting(false)
    }
  }

  async function runSync(base: TermBase) {
    setSyncTarget(null)
    setSyncIds((p) => ({ ...p, [base.id]: true }))
    try {
      const r = await glossaryApi.sync(kb.id, base.id)
      toast('success', `同步完成：导入 ${r.imported} 条${r.skipped ? `，跳过 ${r.skipped} 行（未识别名称列）` : ''}`)
      invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '同步失败'
      toast('error', '同步失败', msg)
    } finally {
      setSyncIds((p) => ({ ...p, [base.id]: false }))
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await glossaryApi.remove(kb.id, deleteTarget.id)
      toast('success', '术语集已删除')
      setDeleteTarget(null)
      invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '删除失败'
      toast('error', '删除失败', msg)
    } finally {
      setDeleting(false)
    }
  }

  function openEditor(base: TermBase) {
    void navigate(`/kb/${kb.id}/glossary/${base.id}`)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="知识库"
        title="专业术语集"
        description="管理专业术语集合，支持手动录入、接口拉取、数据库直连三种方式构建术语集"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void refetch()} disabled={isFetching} className="gap-1.5">
              <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} /> 刷新
            </Button>
            {canManage && (
              <Button onClick={openCreate} className="gap-1.5">
                <Plus className="h-4 w-4" /> 新建术语集
              </Button>
            )}
          </div>
        }
      />

      {/* 卡片网格 */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-44 rounded-2xl" />)}
        </div>
      ) : list.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-secondary text-primary">
              <BookMarked className="h-7 w-7" strokeWidth={1.5} />
            </span>
            <p className="text-sm font-medium">暂无术语集</p>
            <p className="max-w-md text-xs leading-5 text-muted-foreground">术语集用于管理专业术语、同义词和标准化名称，可用于结构化抽取时的术语识别与归一化</p>
            {canManage && <Button size="sm" onClick={openCreate} className="mt-2"><Plus className="mr-1.5 h-4 w-4" /> 新建术语集</Button>}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((base) => {
            const meta = SOURCE_META[base.source_type] ?? SOURCE_META.manual
            return (
              <Card
                key={base.id}
                className="group relative flex cursor-pointer flex-col overflow-hidden border-border/80 shadow-soft transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-glow"
                onClick={() => openEditor(base)}
                data-testid={`term-base-card-${base.id}`}
              >
                <CardContent className="flex flex-1 flex-col gap-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold transition-colors group-hover:text-primary-strong">{base.name}</h3>
                      <Badge className={`mt-1.5 gap-1 text-[11px] ${meta.badge}`}>{meta.icon} {meta.label}</Badge>
                    </div>
                  </div>
                  <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">{base.description || '暂无描述'}</p>

                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-primary/60" />{base.term_count} 条术语</span>
                    {base.last_synced_at && (
                      <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />上次同步：{new Date(base.last_synced_at).toLocaleDateString()}</span>
                    )}
                  </div>

                  {/* 原项目交互：hover 显示查看/同步/删除 */}
                  <div className="mt-auto flex items-center gap-1 border-t border-border/60 pt-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 px-3 text-xs opacity-100 transition-all duration-200 md:opacity-0 md:translate-y-1 md:group-hover:translate-y-0 md:group-hover:opacity-100"
                      onClick={(e) => { e.stopPropagation(); openEditor(base) }}
                    >
                      <Eye className="mr-1 h-3.5 w-3.5" /> 查看
                    </Button>
                    {canManage && base.source_type !== 'manual' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-3 text-xs opacity-100 transition-all duration-200 md:opacity-0 md:translate-y-1 md:group-hover:translate-y-0 md:group-hover:opacity-100"
                        disabled={syncIds[base.id]}
                        onClick={(e) => { e.stopPropagation(); setSyncTarget(base) }}
                      >
                        {syncIds[base.id] ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="mr-1 h-3.5 w-3.5" />} 同步
                      </Button>
                    )}
                    {canManage && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="ml-auto h-8 px-3 text-xs text-destructive opacity-100 transition-all duration-200 hover:text-destructive md:opacity-0 md:translate-y-1 md:group-hover:translate-y-0 md:group-hover:opacity-100"
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget(base) }}
                      >
                        <Trash2 className="mr-1 h-3.5 w-3.5" /> 删除
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* 新建术语集（单弹窗，对齐原项目） */}
      <Dialog
        open={createOpen}
        onOpenChange={(open) => { if (!open) setCreateOpen(false) }}
        title="新建术语集"
        className="max-w-3xl"
      >
        <div className="max-h-[72vh] space-y-6 overflow-y-auto pr-1">
          {/* 基本信息 */}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-muted-foreground">术语集名称 *
              <Input value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} placeholder="例如：检测项目库、材料牌号库" className="mt-1 h-10" />
            </label>
            <label className="text-xs font-medium text-muted-foreground">描述
              <Input value={manual.description} onChange={(e) => setManual({ ...manual, description: e.target.value })} placeholder="描述这个术语集的用途和内容范围" className="mt-1 h-10" />
            </label>
          </div>

          {/* 数据源类型 */}
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">数据源类型 *</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {(['manual', 'api', 'db'] as const).map((t) => {
                const m = SOURCE_META[t]
                const active = sourceType === t
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => { setSourceType(t); setPreview(null); setApiTest(null); setDbTest(null) }}
                    className={`relative flex flex-col items-center gap-2 rounded-xl border-2 p-4 text-left transition-all ${
                      active ? 'border-primary/50 bg-secondary/40 shadow-glow' : 'border-border bg-background-soft hover:border-primary/30'
                    }`}
                  >
                    <span className={`inline-flex h-10 w-10 items-center justify-center rounded-xl ${m.badge}`}>{m.icon}</span>
                    <p className="text-sm font-semibold">{m.label}</p>
                    <p className="text-center text-xs text-muted-foreground">{m.desc}</p>
                    {active && <CheckCircle2 className="absolute right-2 top-2 h-4 w-4 text-primary" />}
                  </button>
                )
              })}
            </div>
          </div>

          {/* manual 提示 */}
          {sourceType === 'manual' && (
            <p className="rounded-xl bg-secondary/50 p-3 text-xs text-muted-foreground">
              创建后将直接进入术语集内部，您可以手动添加和管理术语条目。
            </p>
          )}

          {/* API 配置 */}
          {sourceType === 'api' && (
            <div className="space-y-3 rounded-xl border border-border bg-background-soft p-4">
              <div className="grid gap-3 sm:grid-cols-[1fr_130px]">
                <label className="text-xs font-medium text-muted-foreground">接口地址 *
                  <Input value={apiForm.url} onChange={(e) => setApiForm({ ...apiForm, url: e.target.value })} placeholder="https://api.example.com/terms（内网请填实际 IP，不支持 localhost）" className="mt-1 h-10" />
                </label>
                <label className="text-xs font-medium text-muted-foreground">请求方法
                  <Select value={apiForm.method} onChange={(e) => setApiForm({ ...apiForm, method: e.target.value as 'GET' | 'POST' })} className="mt-1 h-10">
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                  </Select>
                </label>
              </div>
              <label className="block text-xs font-medium text-muted-foreground">数据路径（可选，如 data.list）
                <Input value={apiForm.json_path} onChange={(e) => setApiForm({ ...apiForm, json_path: e.target.value })} className="mt-1 h-10" />
              </label>

              {/* 请求参数 */}
              <div className="space-y-2 rounded-xl border border-border bg-card p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">请求参数</p>
                  <div className="flex flex-wrap gap-1">
                    <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={() => addApiParam('path')}>+ 路径参数</Button>
                    <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={() => addApiParam('query')}>+ Query 参数</Button>
                    <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={() => addApiParam('header')}>+ 请求头</Button>
                  </div>
                </div>
                {apiForm.params.length === 0 ? (
                  <p className="text-xs text-muted-foreground">未配置参数</p>
                ) : (
                  <div className="space-y-2">
                    {apiForm.params.map((p, idx) => (
                      <div key={idx} className="flex items-center gap-2">
                        <input type="checkbox" checked={p.enabled} onChange={(e) => setApiForm({ ...apiForm, params: apiForm.params.map((x, i) => (i === idx ? { ...x, enabled: e.target.checked } : x)) })} className="h-4 w-4 shrink-0 accent-primary" />
                        <Badge className="w-14 shrink-0 justify-center text-[10px]">{p.in_location}</Badge>
                        <Input value={p.key} onChange={(e) => setApiForm({ ...apiForm, params: apiForm.params.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)) })} placeholder="参数名" className="h-9 flex-1" />
                        <Input value={p.value} onChange={(e) => setApiForm({ ...apiForm, params: apiForm.params.map((x, i) => (i === idx ? { ...x, value: e.target.value } : x)) })} placeholder="参数值" className="h-9 flex-1" />
                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => removeApiParam(idx)} aria-label="删除参数"><X className="h-4 w-4" /></Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {apiForm.method === 'POST' && (
                <label className="block text-xs font-medium text-muted-foreground">请求体 (JSON)
                  <textarea value={apiForm.body} onChange={(e) => setApiForm({ ...apiForm, body: e.target.value })} placeholder='{"key": "value"}' className="mt-1 min-h-[72px] w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-soft focus-visible:border-primary/50 focus-visible:shadow-glow" />
                </label>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-xs font-medium text-muted-foreground">请求头（每行 key: value）
                  <Input value={apiForm.headersText} onChange={(e) => setApiForm({ ...apiForm, headersText: e.target.value })} placeholder="Authorization: Bearer xxx" className="mt-1 h-10 font-mono text-xs" />
                </label>
                <label className="block text-xs font-medium text-muted-foreground">超时（秒）
                  <Input type="number" min={1} max={120} value={apiForm.timeout} onChange={(e) => setApiForm({ ...apiForm, timeout: e.target.value })} className="mt-1 h-10" />
                </label>
              </div>

              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" onClick={runApiTest} disabled={apiTesting || !apiForm.url.trim()} className="gap-1.5">
                  {apiTesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Globe className="h-3.5 w-3.5" />} 测试接口
                </Button>
                {apiTest?.ok && (
                  <span className="flex items-center gap-1.5 text-xs text-success"><CheckCircle2 className="h-3.5 w-3.5" /> 测试成功（{apiTest.total} 条数据）</span>
                )}
                {apiTest && !apiTest.ok && (
                  <span className="flex items-center gap-1.5 text-xs text-destructive"><X className="h-3.5 w-3.5" /> {apiTest.error}</span>
                )}
              </div>
            </div>
          )}

          {/* DB 配置 */}
          {sourceType === 'db' && (
            <div className="space-y-3 rounded-xl border border-border bg-background-soft p-4">
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="text-xs font-medium text-muted-foreground">主机地址 *
                  <Input value={dbForm.host} onChange={(e) => setDbForm({ ...dbForm, host: e.target.value })} placeholder="10.0.0.12" className="mt-1 h-10" disabled={dbTest?.ok} />
                </label>
                <label className="text-xs font-medium text-muted-foreground">端口
                  <Input value={dbForm.port} onChange={(e) => setDbForm({ ...dbForm, port: e.target.value })} className="mt-1 h-10" disabled={dbTest?.ok} />
                </label>
                <label className="text-xs font-medium text-muted-foreground">数据库名 *
                  <Input value={dbForm.database} onChange={(e) => setDbForm({ ...dbForm, database: e.target.value })} className="mt-1 h-10" disabled={dbTest?.ok} />
                </label>
                <label className="text-xs font-medium text-muted-foreground">用户名 *
                  <Input value={dbForm.user} onChange={(e) => setDbForm({ ...dbForm, user: e.target.value })} className="mt-1 h-10" disabled={dbTest?.ok} />
                </label>
                <label className="text-xs font-medium text-muted-foreground">密码
                  <Input type="password" value={dbForm.password} onChange={(e) => setDbForm({ ...dbForm, password: e.target.value })} className="mt-1 h-10" disabled={dbTest?.ok} />
                </label>
                <label className="text-xs font-medium text-muted-foreground">字符集
                  <Input value={dbForm.charset} onChange={(e) => setDbForm({ ...dbForm, charset: e.target.value })} placeholder="utf8mb4" className="mt-1 h-10" disabled={dbTest?.ok} />
                </label>
              </div>

              <div className="flex items-center gap-3">
                {!dbTest?.ok ? (
                  <Button variant="outline" size="sm" onClick={runDbConnect} disabled={dbTesting || !dbForm.host.trim()} className="gap-1.5">
                    {dbTesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <DbIcon className="h-3.5 w-3.5" />} 测试连接
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => { setDbTest(null); setDbTables([]); setPreview(null) }}>重新连接</Button>
                )}
                {dbTest?.ok && <span className="flex items-center gap-1.5 text-xs text-success"><CheckCircle2 className="h-3.5 w-3.5" /> 连接成功</span>}
                {dbTest && !dbTest.ok && <span className="flex items-center gap-1.5 text-xs text-destructive"><X className="h-3.5 w-3.5" /> {dbTest.error}</span>}
              </div>

              {dbTest?.ok && (
                <div className="space-y-3">
                  {/* 选择表格 / SQL查询（对齐原项目 Tabs） */}
                  <div className="flex w-full items-center gap-1 rounded-lg bg-muted/50 p-1">
                    <button
                      type="button"
                      onClick={() => setDbForm({ ...dbForm, mode: 'table' })}
                      className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-all ${dbForm.mode === 'table' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                    >选择表格</button>
                    <button
                      type="button"
                      onClick={() => setDbForm({ ...dbForm, mode: 'sql' })}
                      className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-all ${dbForm.mode === 'sql' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                    >SQL查询</button>
                  </div>
                  {dbForm.mode === 'table' && (
                    <label className="block text-xs font-medium text-muted-foreground">选择数据表
                      <Select value={dbForm.table} onChange={(e) => setDbForm({ ...dbForm, table: e.target.value })} className="mt-1 h-10">
                        <option value="">选择表</option>
                        {dbTables.map((t) => <option key={t} value={t}>{t}</option>)}
                      </Select>
                    </label>
                  )}
                  {dbForm.mode === 'sql' && (
                    <label className="block text-xs font-medium text-muted-foreground">SQL查询语句
                      <textarea value={dbForm.sql_query} onChange={(e) => setDbForm({ ...dbForm, sql_query: e.target.value })} placeholder="SELECT * FROM my_table WHERE ..." className="mt-1 min-h-[72px] w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-soft focus-visible:border-primary/50 focus-visible:shadow-glow" />
                    </label>
                  )}
                  <Button variant="outline" size="sm" onClick={runDbPreview} disabled={dbPreviewing || (dbForm.mode === 'table' ? !dbForm.table : !dbForm.sql_query.trim())} className="gap-1.5">
                    {dbPreviewing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />} 预览数据
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* 预览 */}
          {preview && (
            <div className="rounded-xl border border-border bg-background-soft p-3">
              <p className="text-xs font-medium text-muted-foreground">数据预览（前 {Math.min(preview.rows.length, 5)} 条）</p>
              <div className="mt-2 overflow-x-auto text-xs">
                <table className="w-full border-collapse">
                  <thead>
                    <tr>{preview.columns.map((c) => <th key={c.name} className="border border-border bg-muted px-2 py-1 text-left">{c.label}</th>)}</tr>
                  </thead>
                  <tbody>
                    {preview.rows.slice(0, 5).map((r, i) => (
                      <tr key={i}>{preview.columns.map((c) => <td key={c.name} className="border border-border px-2 py-1">{String(r[c.name] ?? '')}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="mt-5 flex items-center justify-end gap-3 border-t border-border/60 pt-4">
          {sourceType !== 'manual' && !preview && (
            <p className="mr-auto text-xs text-muted-foreground">请先完成数据源测试/预览，获取列结构和数据</p>
          )}
          <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
          <Button
            onClick={submitCreate}
            disabled={submitting || !manual.name.trim() || (sourceType !== 'manual' && !preview)}
            className="gap-2"
            data-testid="btn-create-submit"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {sourceType === 'manual' ? '创建术语集' : '创建并导入数据'}
          </Button>
        </div>
      </Dialog>

      {/* 同步确认 */}
      <Dialog
        open={syncTarget !== null}
        onOpenChange={(open) => { if (!open) setSyncTarget(null) }}
        title="同步术语集"
        description={`将从数据源重新同步「${syncTarget?.name}」，现有数据将被覆盖，是否继续？`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setSyncTarget(null)}>取消</Button>
          <Button onClick={() => syncTarget && void runSync(syncTarget)} disabled={syncTarget ? Boolean(syncIds[syncTarget.id]) : false} className="gap-1.5">
            {syncTarget && syncIds[syncTarget.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />} 确认同步
          </Button>
        </div>
      </Dialog>

      {/* 删除确认 */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="删除术语集"
        description={`确定删除术语集「${deleteTarget?.name}」？该术语集下的 ${deleteTarget?.term_count ?? 0} 条数据也将被删除，此操作不可恢复。`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
          <Button variant="destructive" onClick={confirmDelete} disabled={deleting} className="gap-1.5">
            {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} 删除
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
