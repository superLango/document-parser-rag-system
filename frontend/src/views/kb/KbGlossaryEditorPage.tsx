import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookMarked, Check, Database as DbIcon, Globe, Hand, Loader2, Plus, RefreshCcw, Save, Search, Settings2, Trash2, X } from 'lucide-react'
import { glossaryApi } from '@/api/modules/glossary'
import { ApiError } from '@/api/client'
import type { TermItem } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/PageHeader'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { useKbDetail } from './KbDetailLayout'

const CRON_PRESETS = [
  { label: '每小时', value: '0 * * * *' },
  { label: '每天凌晨 2 点', value: '0 2 * * *' },
  { label: '每周一 2 点', value: '0 2 * * 1' },
  { label: '每月 1 号 2 点', value: '0 2 1 * *' },
]

const SOURCE_META: Record<string, { label: string; icon: React.ReactNode }> = {
  manual: { label: '手动录入', icon: <Hand className="h-3 w-3" /> },
  api: { label: '接口拉取', icon: <Globe className="h-3 w-3" /> },
  db: { label: '数据库', icon: <DbIcon className="h-3 w-3" /> },
}

interface EditableRow extends TermItem {
  _isNew?: boolean
  _isDeleted?: boolean
  _modified?: boolean
}

const PAGE_SIZE = 50

export default function KbGlossaryEditorPage() {
  const { baseId } = useParams<{ baseId: string }>()
  const navigate = useNavigate()
  const { kb } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'

  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [searchField, setSearchField] = useState('')
  const [page, setPage] = useState(1)

  const [editableRows, setEditableRows] = useState<EditableRow[]>([])
  const [infoForm, setInfoForm] = useState({ name: '', description: '' })
  // 定时同步（cron）
  const [syncEnabled, setSyncEnabled] = useState(false)
  const [syncCronDraft, setSyncCronDraft] = useState('')
  const [syncCronNext, setSyncCronNext] = useState<string | null>(null)
  const [syncCronError, setSyncCronError] = useState('')
  const [syncCronSaving, setSyncCronSaving] = useState(false)
  const [savingAll, setSavingAll] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncConfirmOpen, setSyncConfirmOpen] = useState(false)

  const [aliasOpen, setAliasOpen] = useState(false)
  const [aliasDraft, setAliasDraft] = useState<Record<string, string>>({})
  const [aliasSaving, setAliasSaving] = useState(false)

  const baseQuery = useQuery({
    queryKey: ['kb-term-base', kb.id, baseId],
    queryFn: () => glossaryApi.get(kb.id, baseId!),
    enabled: Boolean(baseId),
  })
  const base = baseQuery.data
  const isManual = base?.source_type === 'manual'

  const { data, isLoading } = useQuery({
    queryKey: ['kb-terms', kb.id, baseId, search, searchField, page],
    queryFn: () => glossaryApi.listTerms(kb.id, {
      term_base_id: baseId, page, page_size: PAGE_SIZE,
      keyword: search || undefined, search_field: searchField || undefined,
    }),
    enabled: Boolean(baseId),
  })
  const items = useMemo(() => data?.items ?? [], [data])

  const displayColumns = useMemo(() => {
    if (!base || isManual) return []
    const aliases = base.column_aliases ?? {}
    return (base.columns ?? []).map((c) => ({
      name: c.name,
      label: aliases[c.name] || c.label || c.name,
    }))
  }, [base, isManual])

  const searchFieldOptions = useMemo(() => {
    if (!base) return [{ value: '', label: '全部字段' }]
    if (isManual) {
      return [
        { value: '', label: '全部字段' },
        { value: 'term', label: '术语名称' },
        { value: 'english_term', label: '英文名称' },
        { value: 'aliases', label: '术语别称' },
        { value: 'definition', label: '术语定义' },
        { value: 'category', label: '分类' },
        { value: 'synonyms', label: '同义词' },
      ]
    }
    return [{ value: '', label: '全部字段' }, ...displayColumns.map((c) => ({ value: c.name, label: c.label }))]
  }, [base, isManual, displayColumns])

  useEffect(() => {
    setEditableRows(items.map((t) => ({ ...t, synonyms: [...(t.synonyms ?? [])], aliases: [...(t.aliases ?? [])] })))
  }, [items])

  useEffect(() => {
    if (base) {
      setInfoForm({ name: base.name, description: base.description || '' })
      setSyncEnabled(base.sync_enabled)
      setSyncCronDraft(base.sync_cron || '')
    }
  }, [base])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['kb-terms', kb.id] })
    void queryClient.invalidateQueries({ queryKey: ['kb-term-base', kb.id] })
    void queryClient.invalidateQueries({ queryKey: ['kb-term-bases', kb.id] })
  }

  function updateRow(rowId: string, patch: Partial<EditableRow>) {
    setEditableRows((prev) => prev.map((r) => (r.id === rowId ? { ...r, ...patch, _modified: true } : r)))
  }

  function addRow() {
    setEditableRows((prev) => [{
      id: `new-${Date.now()}`,
      term_base_id: baseId!,
      term_base_name: base?.name ?? '',
      term_name: '',
      standard_name: '',
      english_term: '',
      definition: '',
      category: '',
      standard_number: '',
      synonyms: [],
      aliases: [],
      extras: {},
      status: 'active',
      reviewed_by: null,
      reviewed_at: null,
      created_at: new Date().toISOString(),
      updated_at: null,
      _isNew: true,
    }, ...prev])
  }

  function toggleDeleted(rowId: string) {
    setEditableRows((prev) => prev.map((r) => (r.id === rowId ? { ...r, _isDeleted: !r._isDeleted } : r)))
  }

  function addChip(rowId: string, field: 'synonyms' | 'aliases', value: string) {
    const v = value.trim()
    if (!v) return
    setEditableRows((prev) => prev.map((r) => {
      if (r.id !== rowId) return r
      const list = [...(r[field] ?? [])]
      if (!list.includes(v)) list.push(v)
      return { ...r, [field]: list, _modified: true }
    }))
  }

  function removeChip(rowId: string, field: 'synonyms' | 'aliases', idx: number) {
    setEditableRows((prev) => prev.map((r) => {
      if (r.id !== rowId) return r
      const list = [...(r[field] ?? [])]
      list.splice(idx, 1)
      return { ...r, [field]: list, _modified: true }
    }))
  }

  async function saveAll() {
    if (!base) return
    if (!infoForm.name.trim()) {
      toast('warning', '请填写术语集名称')
      return
    }
    for (const r of editableRows) {
      if (!r._isDeleted && !r.term_name.trim()) {
        toast('warning', '存在未填写术语名称的行，请填写或删除')
        return
      }
    }
    setSavingAll(true)
    try {
      await glossaryApi.update(kb.id, base.id, { name: infoForm.name.trim(), description: infoForm.description.trim() })
      const itemsToSave = editableRows
        .filter((r) => !r._isDeleted && (r._isNew || r._modified))
        .map((r) => ({
          id: r._isNew ? undefined : r.id,
          term: r.term_name.trim(),
          english_term: r.english_term,
          aliases: r.aliases ?? [],
          definition: r.definition,
          category: r.category,
          standard_number: r.standard_number,
          synonyms: r.synonyms ?? [],
          extras: r.extras ?? {},
        }))
      const deletedIds = editableRows.filter((r) => r._isDeleted && !r._isNew).map((r) => r.id)
      if (itemsToSave.length > 0 || deletedIds.length > 0) {
        await glossaryApi.batchSaveTerms(kb.id, base.id, { items: itemsToSave, deleted_ids: deletedIds })
      }
      toast('success', '保存成功')
      invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '保存失败'
      toast('error', '保存失败', msg)
    } finally {
      setSavingAll(false)
    }
  }

  async function syncFromSource() {
    if (!base) return
    setSyncConfirmOpen(false)
    setSyncing(true)
    try {
      const r = await glossaryApi.sync(kb.id, base.id)
      toast('success', `同步完成，导入 ${r.imported} 条${r.skipped ? `，跳过 ${r.skipped} 行（未识别名称列）` : ''}`)
      invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '同步失败'
      toast('error', '同步失败', msg)
    } finally {
      setSyncing(false)
    }
  }

  async function validateCronDraft(expr: string) {
    const text = expr.trim()
    if (!text) {
      setSyncCronNext(null)
      setSyncCronError('')
      return
    }
    try {
      const r = await glossaryApi.validateCron(kb.id, text)
      setSyncCronNext(r.next_run_at)
      setSyncCronError('')
    } catch (err) {
      setSyncCronNext(null)
      setSyncCronError(err instanceof ApiError ? err.message : 'cron 表达式无效')
    }
  }

  async function saveSyncCron() {
    if (!base || !canManage) return
    const expr = syncCronDraft.trim()
    if (expr && syncCronError) {
      toast('warning', '请先修正 cron 表达式')
      return
    }
    if (syncEnabled && !expr) {
      toast('warning', '启用定时同步需填写 cron 表达式')
      return
    }
    setSyncCronSaving(true)
    try {
      await glossaryApi.update(kb.id, base.id, { sync_enabled: syncEnabled, sync_cron: expr })
      toast('success', syncEnabled ? '定时同步已保存' : '定时同步已停用')
      invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '保存失败'
      toast('error', '保存失败', msg)
    } finally {
      setSyncCronSaving(false)
    }
  }

  function openAliasPanel() {
    if (!base) return
    const aliases = base.column_aliases ?? {}
    const draft: Record<string, string> = {}
    for (const c of base.columns ?? []) draft[c.name] = aliases[c.name] || c.label || c.name
    setAliasDraft(draft)
    setAliasOpen(true)
  }

  async function saveAliases() {
    if (!base) return
    const aliasesToSave: Record<string, string> = {}
    for (const c of base.columns ?? []) {
      const edited = (aliasDraft[c.name] ?? '').trim()
      if (edited && edited !== c.name && edited !== (c.label || c.name)) aliasesToSave[c.name] = edited
    }
    setAliasSaving(true)
    try {
      await glossaryApi.update(kb.id, base.id, { column_aliases: aliasesToSave })
      toast('success', '字段名已更新')
      setAliasOpen(false)
      invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '保存失败'
      toast('error', '保存失败', msg)
    } finally {
      setAliasSaving(false)
    }
  }

  const NAME_FIELDS = new Set(['term_name', 'term', 'name', 'value', '名称', '术语名称', '词汇', '关键词'])

  function cellValue(term: TermItem, colName: string): string {
    const v = term.extras?.[colName]
    if (v == null || v === '') {
      if (NAME_FIELDS.has(colName)) return term.term_name
      return '—'
    }
    if (Array.isArray(v)) return v.join(', ')
    if (typeof v === 'object') return JSON.stringify(v)
    return String(v)
  }

  if (baseQuery.isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-sm font-medium">术语集不存在或已删除</p>
          <Link to={`/kb/${kb.id}/glossary`} className="text-sm text-primary underline-offset-4 hover:underline">返回术语集列表</Link>
        </CardContent>
      </Card>
    )
  }

  const meta = base ? SOURCE_META[base.source_type] ?? SOURCE_META.manual : null

  return (
    <div>
      <PageHeader
        title={`编辑术语集 · ${base?.name || ''}`}
        description={`知识库：${kb.name}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => navigate(`/kb/${kb.id}/glossary`)} className="gap-1.5">
              <ArrowLeft className="h-4 w-4" /> 返回列表
            </Button>
            {canManage && !isManual && (
              <Button variant="outline" onClick={() => setSyncConfirmOpen(true)} disabled={syncing} className="gap-1.5">
                <RefreshCcw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
                {syncing ? '同步中...' : '从数据源同步'}
              </Button>
            )}
            {canManage && isManual && (
              <Button onClick={saveAll} disabled={savingAll} className="gap-1.5" data-testid="btn-save-all">
                <Save className="h-4 w-4" /> 保存全部
                {savingAll && <Loader2 className="h-4 w-4 animate-spin" />}
              </Button>
            )}
          </div>
        }
      />

      {/* 术语集信息（对齐工整：名称与词条数同排等高，描述整行） */}
      <Card className="mb-4">
        <CardContent className="space-y-4 p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <BookMarked className="h-4 w-4 text-primary" />
            术语集信息
            {base && meta && (
              <Badge variant="outline" className="gap-1 text-[11px]">{meta.icon} {meta.label}</Badge>
            )}
          </div>
          <div className="grid items-end gap-4 md:grid-cols-2">
            <label className="block text-xs font-medium text-muted-foreground">术语集名称 *
              <Input value={infoForm.name} onChange={(e) => setInfoForm({ ...infoForm, name: e.target.value })} disabled={!isManual || !canManage} className="mt-1 h-9" data-testid="info-name-input" />
            </label>
            <div className="flex items-end gap-3">
              <div className="flex h-9 flex-1 items-center rounded-md border bg-muted/30 px-3 text-sm text-muted-foreground">
                {data?.total ?? 0} 条术语
              </div>
              {base?.last_synced_at && (
                <div className="flex h-9 shrink-0 items-center rounded-md border bg-muted/30 px-3 text-xs text-muted-foreground">
                  上次同步：{formatDateTime(base.last_synced_at)}
                </div>
              )}
            </div>
          </div>
          <label className="block text-xs font-medium text-muted-foreground">描述
            <textarea value={infoForm.description} onChange={(e) => setInfoForm({ ...infoForm, description: e.target.value })} disabled={!isManual || !canManage} rows={2} placeholder="描述该术语集的适用范围与用途" className="mt-1 min-h-[60px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-soft focus-visible:border-primary/50 focus-visible:shadow-glow disabled:opacity-60" data-testid="info-desc-input" />
          </label>

          {/* 定时同步（cron，仅外部数据源） */}
          {!isManual && (
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">定时同步（cron）</p>
                {base && base.sync_status && (
                  <Badge variant={base.sync_status === 'failed' ? 'destructive' : 'secondary'} className="text-[10px]">
                    {base.sync_status === 'failed' ? '上次失败' : base.sync_status === 'success' ? '同步成功' : '未同步'}
                  </Badge>
                )}
              </div>
              <p className="mb-2 text-[11px] leading-tight text-muted-foreground/80">
                按 cron 表达式定时从数据源同步词条（清空重导）；保存后由后台每分钟扫描触发，无需重启服务。
              </p>
              <label className="mb-3 flex items-center justify-between gap-2 rounded-lg bg-card/60 px-2.5 py-2 text-sm">
                <span>
                  <span className="font-medium text-foreground">启用定时同步</span>
                  <span className="block text-[11px] leading-tight text-muted-foreground/80">开启后按下方表达式自动同步；关闭后不再自动同步</span>
                </span>
                <Switch checked={syncEnabled} onCheckedChange={setSyncEnabled} disabled={!canManage} />
              </label>
              <div className="grid gap-2 sm:grid-cols-[190px_1fr]">
                <Select value="" onChange={(e) => { const v = e.target.value; if (v) { setSyncCronDraft(v); void validateCronDraft(v) } }} disabled={!canManage} className="h-9">
                  <option value="">常用预设…</option>
                  {CRON_PRESETS.map((c) => <option key={c.value} value={c.value}>{c.label}（{c.value}）</option>)}
                </Select>
                <Input
                  value={syncCronDraft}
                  onChange={(e) => { setSyncCronDraft(e.target.value); void validateCronDraft(e.target.value) }}
                  placeholder="如 0 2 * * *（分 时 日 月 周）"
                  disabled={!canManage}
                  className="h-9 font-mono"
                  data-testid="sync-cron-input"
                />
              </div>
              {syncCronError ? (
                <p className="mt-1.5 text-xs text-destructive">cron 表达式无效：{syncCronError}</p>
              ) : syncCronNext ? (
                <p className="mt-1.5 text-xs text-success">下次执行：{formatDateTime(syncCronNext)}</p>
              ) : null}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={saveSyncCron} disabled={!canManage || syncCronSaving} className="gap-1.5" data-testid="btn-save-sync-cron">
                  {syncCronSaving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} 保存定时同步
                </Button>
                {base?.last_synced_at && (
                  <span className="text-xs text-muted-foreground">上次同步：{formatDateTime(base.last_synced_at)}</span>
                )}
                {base?.sync_next_run_at && (
                  <span className="text-xs text-muted-foreground">下次执行：{formatDateTime(base.sync_next_run_at)}</span>
                )}
              </div>
              {base?.sync_last_error && (
                <p className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
                  上次同步失败：{base.sync_last_error}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 搜索与添加 */}
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-3 p-3">
          {canManage && isManual && (
            <Button size="sm" onClick={addRow} className="gap-1" data-testid="btn-add-row">
              <Plus className="h-4 w-4" /> 添加一行
            </Button>
          )}
          {!isManual && canManage && (
            <span className="shrink-0 text-xs text-muted-foreground">该术语集数据来源于外部数据源，如需修改请在数据源处更新后点击同步</span>
          )}
          <div className="w-[150px] shrink-0">
            <Select value={searchField} onChange={(e) => { setSearchField(e.target.value); setPage(1) }} className="h-9 text-sm" data-testid="search-field-select">
              {searchFieldOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          </div>
          <div className="relative min-w-[200px] flex-1">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { setSearch(keyword.trim()); setPage(1) } }}
              placeholder={searchField ? `搜索${searchFieldOptions.find((o) => o.value === searchField)?.label || ''}` : '搜索全部字段'}
              className="pl-8"
              data-testid="term-search"
            />
          </div>
          <Button variant="outline" size="sm" onClick={() => { setSearch(keyword.trim()); setPage(1) }} className="gap-1">
            <Search className="h-4 w-4" /> 搜索
          </Button>
          {canManage && !isManual && (
            <Button variant="outline" size="sm" onClick={openAliasPanel} className="gap-1" data-testid="btn-field-config">
              <Settings2 className="h-4 w-4" /> 修改字段
            </Button>
          )}
        </CardContent>
      </Card>

      {/* 术语表格 */}
      <Card>
        <div className="overflow-x-auto">
          <Table className={isManual ? 'min-w-[1100px]' : 'min-w-[1000px]'}>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                {isManual ? (
                  <>
                    <TableHead className="min-w-[140px]">术语名称</TableHead>
                    <TableHead className="min-w-[120px]">英文名称</TableHead>
                    <TableHead className="min-w-[160px]">术语别称</TableHead>
                    <TableHead className="min-w-[200px]">术语定义</TableHead>
                    <TableHead className="min-w-[100px]">分类</TableHead>
                    <TableHead className="min-w-[160px]">同义词</TableHead>
                  </>
                ) : (
                  <>
                    {displayColumns.map((col) => <TableHead key={col.name} className="min-w-[120px]">{col.label}</TableHead>)}
                  </>
                )}
                {canManage && isManual && <TableHead className="w-16">操作</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow><TableCell colSpan={9}><Skeleton className="h-40 w-full" /></TableCell></TableRow>
              ) : editableRows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-12 text-center">
                    <BookMarked className="mx-auto mb-2 h-8 w-8 opacity-50" />
                    <p>暂无数据</p>
                    {canManage && isManual && <p className="mt-1 text-xs text-muted-foreground">点击“添加一行”开始创建术语</p>}
                    {canManage && !isManual && <p className="mt-1 text-xs text-muted-foreground">点击“从数据源同步”获取最新数据</p>}
                  </TableCell>
                </TableRow>
              ) : (
                editableRows.map((t, idx) => (
                  <TableRow
                    key={t.id}
                    data-testid={`term-row-${t.id}`}
                    className={t._isDeleted ? 'bg-muted/30 opacity-50' : t._isNew ? 'bg-success/5' : t._modified ? 'bg-warning/5' : ''}
                  >
                    <TableCell className="align-top">
                      <div className="flex flex-col gap-1">
                        <span className="text-xs text-muted-foreground">{(page - 1) * PAGE_SIZE + idx + 1}</span>
                        {t._isNew && <Badge variant="secondary" className="text-[10px]">新增</Badge>}
                        {t._modified && !t._isNew && <Badge variant="outline" className="text-[10px]">已修改</Badge>}
                      </div>
                    </TableCell>
                    {isManual ? (
                      <>
                        <TableCell className="align-top">
                          {canManage && !t._isDeleted ? (
                            <Input value={t.term_name} onChange={(e) => updateRow(t.id, { term_name: e.target.value })} placeholder="术语名称" size={undefined} className="h-8" data-testid={`edit-term-${t.id}`} />
                          ) : <span className="text-sm">{t.term_name}</span>}
                        </TableCell>
                        <TableCell className="align-top">
                          {canManage && !t._isDeleted ? (
                            <Input value={t.english_term} onChange={(e) => updateRow(t.id, { english_term: e.target.value })} placeholder="English" className="h-8" />
                          ) : <span className="text-sm">{t.english_term}</span>}
                        </TableCell>
                        <TableCell className="align-top">
                          {canManage && !t._isDeleted ? (
                            <div className="space-y-1">
                              <div className="flex flex-wrap gap-1">
                                {(t.aliases ?? []).map((a, ai) => (
                                  <Badge key={ai} variant="secondary" className="cursor-pointer gap-1 text-xs" onClick={() => removeChip(t.id, 'aliases', ai)}>
                                    {a}<X className="h-3 w-3" />
                                  </Badge>
                                ))}
                              </div>
                              <Input placeholder="添加别称后回车" className="h-7 text-xs" onKeyDown={(e) => { if (e.key === 'Enter') { addChip(t.id, 'aliases', e.currentTarget.value); e.currentTarget.value = '' } }} />
                            </div>
                          ) : (
                            <div className="flex flex-wrap gap-1">{(t.aliases ?? []).map((a, ai) => <Badge key={ai} variant="secondary" className="text-xs">{a}</Badge>)}</div>
                          )}
                        </TableCell>
                        <TableCell className="align-top">
                          {canManage && !t._isDeleted ? (
                            <textarea value={t.definition} onChange={(e) => updateRow(t.id, { definition: e.target.value })} placeholder="术语定义" rows={1} className="min-h-[32px] w-full resize-y rounded-md border border-input bg-card px-2 py-1 text-xs shadow-soft focus-visible:border-primary/50" />
                          ) : <span className="text-sm">{t.definition}</span>}
                        </TableCell>
                        <TableCell className="align-top">
                          {canManage && !t._isDeleted ? (
                            <Input value={t.category} onChange={(e) => updateRow(t.id, { category: e.target.value })} placeholder="分类" className="h-8" />
                          ) : <span className="text-sm">{t.category}</span>}
                        </TableCell>
                        <TableCell className="align-top">
                          {canManage && !t._isDeleted ? (
                            <div className="space-y-1">
                              <div className="flex flex-wrap gap-1">
                                {(t.synonyms ?? []).map((s, si) => (
                                  <Badge key={si} variant="secondary" className="cursor-pointer gap-1 text-xs" onClick={() => removeChip(t.id, 'synonyms', si)}>
                                    {s}<X className="h-3 w-3" />
                                  </Badge>
                                ))}
                              </div>
                              <Input placeholder="添加同义词后回车" className="h-7 text-xs" onKeyDown={(e) => { if (e.key === 'Enter') { addChip(t.id, 'synonyms', e.currentTarget.value); e.currentTarget.value = '' } }} />
                            </div>
                          ) : (
                            <div className="flex flex-wrap gap-1">{(t.synonyms ?? []).map((s, si) => <Badge key={si} variant="secondary" className="text-xs">{s}</Badge>)}</div>
                          )}
                        </TableCell>
                      </>
                    ) : (
                      <>
                        {displayColumns.map((col) => (
                          <TableCell key={col.name} className="align-top text-sm">{cellValue(t, col.name)}</TableCell>
                        ))}
                      </>
                    )}
                    {canManage && isManual && (
                      <TableCell className="align-top">
                        <Button variant="ghost" size="sm" className={t._isDeleted ? 'h-8 px-2 text-xs text-success' : 'h-8 w-8 p-0'} onClick={() => toggleDeleted(t.id)} title={t._isDeleted ? '恢复' : '删除'} data-testid={`btn-toggle-delete-${t.id}`}>
                          {t._isDeleted ? '恢复' : <Trash2 className="h-4 w-4 text-destructive" />}
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        {data && data.total > PAGE_SIZE && (
          <div className="flex justify-center border-t p-3">
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
          </div>
        )}
      </Card>

      {/* manual 底部保存 */}
      {canManage && isManual && (
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => navigate(`/kb/${kb.id}/glossary`)}>取消</Button>
          <Button onClick={saveAll} disabled={savingAll} className="gap-1.5">
            {savingAll && <Loader2 className="h-4 w-4 animate-spin" />} 保存全部修改
          </Button>
        </div>
      )}

      {/* 同步确认（自建弹框） */}
      <Dialog
        open={syncConfirmOpen}
        onOpenChange={(open) => { if (!open) setSyncConfirmOpen(false) }}
        title="同步术语集"
        description={`将从数据源重新同步「${base?.name ?? ''}」，现有数据将被覆盖，是否继续？`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setSyncConfirmOpen(false)}>取消</Button>
          <Button onClick={syncFromSource} disabled={syncing} className="gap-1.5" data-testid="btn-sync-confirm">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />} 确认同步
          </Button>
        </div>
      </Dialog>

      {/* 修改字段：右侧滑出面板（复刻原项目） */}
      {aliasOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-foreground/30" onClick={() => setAliasOpen(false)} />
          <div className="relative flex h-full w-full max-w-md flex-col border-l bg-background shadow-xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div>
                <h3 className="text-base font-semibold">修改字段名称</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">修改显示名称，原始字段名保持不变以确保同步正确</p>
              </div>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => setAliasOpen(false)}><X className="h-4 w-4" /></Button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <div className="grid grid-cols-[1fr_1fr_auto] gap-3 border-b pb-2 text-xs font-medium text-muted-foreground">
                <span>新表头名称</span>
                <span>原始字段名</span>
                <span className="w-8" />
              </div>
              {base?.columns?.length ? (
                base.columns.map((col) => (
                  <div key={col.name} className="grid grid-cols-[1fr_1fr_auto] items-center gap-3">
                    <Input value={aliasDraft[col.name] ?? ''} onChange={(e) => setAliasDraft({ ...aliasDraft, [col.name]: e.target.value })} placeholder="输入显示名称" className="h-8 text-sm" data-testid={`alias-input-${col.name}`} />
                    <div className="flex h-8 items-center truncate rounded-md border bg-muted/50 px-2 font-mono text-xs text-muted-foreground" title={col.name}>{col.name}</div>
                    <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-muted-foreground" title="重置为原始名称" onClick={() => setAliasDraft({ ...aliasDraft, [col.name]: col.name })}><X className="h-3 w-3" /></Button>
                  </div>
                ))
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">暂无字段</p>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t px-5 py-4">
              <Button variant="outline" onClick={() => setAliasOpen(false)}>取消</Button>
              <Button onClick={saveAliases} disabled={aliasSaving} className="gap-1.5" data-testid="btn-alias-save">
                <Check className="h-4 w-4" /> 保存
                {aliasSaving && <Loader2 className="h-4 w-4 animate-spin" />}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )

}
