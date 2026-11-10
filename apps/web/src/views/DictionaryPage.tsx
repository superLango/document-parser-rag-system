import { useMemo, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpenText, Loader2, Plus, RefreshCcw, Search } from 'lucide-react'
import {
  DICTIONARY_TYPE_MAP,
  dictionaryApi,
  type DictionaryEntry,
  type DictionaryPendingTerm,
  type DictionaryTypePath,
} from '@/api/modules/dictionary'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { useModule } from './ModuleLayout'

const TABS: { path: DictionaryTypePath; label: string }[] = [
  { path: 'categories', label: '项目大类' },
  { path: 'items', label: '检测项目' },
  { path: 'methods', label: '试验方法' },
]

const TYPE_LABELS: Record<string, string> = {
  category: '项目大类',
  item: '检测项目',
  method: '试验方法',
}

export default function DictionaryPage({
  dictionaryType = 'categories',
}: {
  dictionaryType?: DictionaryTypePath
}) {
  const { module, canManage } = useModule()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [aliasTarget, setAliasTarget] = useState<DictionaryEntry | null>(null)
  const [aliasValue, setAliasValue] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({
    business_code: '',
    business_name: '',
    family: '',
    aliases: '',
    standard_no: '',
    category_code: '',
  })
  const [busy, setBusy] = useState(false)
  const [reviewTarget, setReviewTarget] = useState<DictionaryPendingTerm | null>(null)
  const [reviewBusy, setReviewBusy] = useState(false)
  const [reviewForm, setReviewForm] = useState({
    business_name: '',
    category_code: '',
    standard_no: '',
  })

  const entryType = DICTIONARY_TYPE_MAP[dictionaryType]
  const canEdit = canManage

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['kb-dictionary', module.key, dictionaryType, search],
    queryFn: () =>
      dictionaryApi.getByType(module.key, dictionaryType, {
        q: search || undefined,
        limit: 2000,
      }),
  })
  const { data: coverage } = useQuery({
    queryKey: ['kb-dictionary-coverage', module.key],
    queryFn: () => dictionaryApi.coverage(module.key),
  })
  const { data: categories } = useQuery({
    queryKey: ['kb-dictionary-categories', module.key],
    queryFn: () => dictionaryApi.getByType(module.key, 'categories', { limit: 2000 }),
  })
  const { data: pending } = useQuery({
    queryKey: ['kb-dictionary-pending', module.key],
    queryFn: () => dictionaryApi.pending(module.key),
    enabled: entryType !== 'category',
  })

  const entries = useMemo(() => data?.entries ?? [], [data])
  const pendingItems = useMemo(
    () => (pending?.items ?? []).filter((item) => item.type === entryType),
    [pending, entryType],
  )

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['kb-dictionary'] })
    void queryClient.invalidateQueries({ queryKey: ['kb-dictionary-coverage'] })
    void queryClient.invalidateQueries({ queryKey: ['kb-dictionary-pending'] })
    void refetch()
  }

  async function addAlias() {
    if (!aliasTarget || !aliasValue.trim()) return
    setBusy(true)
    try {
      await dictionaryApi.addAlias(module.key, {
        type: aliasTarget.type,
        business_code: aliasTarget.business_code,
        alias: aliasValue.trim(),
      })
      toast('success', '别名已添加', `${aliasTarget.business_name} ← ${aliasValue.trim()}`)
      setAliasTarget(null)
      setAliasValue('')
      invalidate()
    } catch (err) {
      toast('error', '添加失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function createEntry() {
    if (!form.business_name.trim()) return
    setBusy(true)
    try {
      await dictionaryApi.createEntry(module.key, dictionaryType, {
        business_name: form.business_name.trim(),
        business_code: form.business_code.trim() || undefined,
        family: form.family.trim() || undefined,
        aliases: form.aliases
          .split(/[,，、]/)
          .map((item) => item.trim())
          .filter(Boolean),
        standard_no: form.standard_no.trim() || undefined,
        category_code: form.category_code || undefined,
      })
      toast('success', '词条已创建', form.business_name.trim())
      setCreateOpen(false)
      setForm({
        business_code: '',
        business_name: '',
        family: '',
        aliases: '',
        standard_no: '',
        category_code: '',
      })
      invalidate()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function toggleStatus(entry: DictionaryEntry) {
    setBusy(true)
    try {
      await dictionaryApi.updateEntry(module.key, dictionaryType, entry.business_code, {
        status: entry.status === 'active' ? 'inactive' : 'active',
      })
      toast('success', entry.status === 'active' ? '词条已停用' : '词条已启用', entry.business_name)
      invalidate()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  function openReview(term: DictionaryPendingTerm) {
    const categoryName = term.facets?.business_category
    const category = (categories?.entries ?? []).find(
      (entry) => entry.business_name === categoryName,
    )
    setReviewTarget(term)
    setReviewForm({
      business_name: term.raw,
      category_code: category?.business_code ?? '',
      standard_no: term.type === 'method' ? term.raw : '',
    })
  }

  async function rejectPending(term: DictionaryPendingTerm) {
    setReviewBusy(true)
    try {
      await dictionaryApi.reviewTerm(term.document_id, {
        type: term.type,
        raw: term.raw,
        action: 'reject',
      })
      toast('success', '已忽略新词', term.raw)
      invalidate()
    } catch (err) {
      toast('error', '操作失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setReviewBusy(false)
    }
  }

  async function submitReview() {
    if (!reviewTarget) return
    if (!reviewForm.business_name.trim()) return
    if (entryType === 'item' && !reviewForm.category_code) {
      toast('warning', '请选择所属项目大类')
      return
    }
    if (entryType === 'method' && !reviewForm.standard_no.trim()) {
      toast('warning', '请填写标准号')
      return
    }
    const category = (categories?.entries ?? []).find(
      (entry) => entry.business_code === reviewForm.category_code,
    )
    setReviewBusy(true)
    try {
      await dictionaryApi.reviewTerm(reviewTarget.document_id, {
        type: reviewTarget.type,
        raw: reviewTarget.raw,
        action: 'accept',
        business_name: reviewForm.business_name.trim(),
        category_code: reviewForm.category_code || undefined,
        category_name: category?.business_name,
        standard_no: reviewForm.standard_no.trim() || undefined,
      })
      toast('success', '新词已采纳', reviewForm.business_name.trim())
      setReviewTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '采纳失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setReviewBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="功能模块"
        title="业务词典"
        description={`「${module.name}」的项目大类、检测项目与试验方法分库维护，抽取时按对应词典归一化`}
        actions={
          <>
            {canEdit ? (
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" />
                新建{TYPE_LABELS[entryType]}
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              onClick={() => invalidate()}
              className="gap-1.5"
            >
              <RefreshCcw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              刷新
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap gap-1.5">
        {TABS.map((tab) => (
          <NavLink
            key={tab.path}
            to={`/standard/dictionary/${tab.path}`}
            className={({ isActive }) =>
              `rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                isActive
                  ? 'border-primary/40 bg-primary/10 text-primary'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'
              }`
            }
          >
            {tab.label}
            <span className="ml-1.5 text-xs text-muted-foreground">
              {coverage
                ? tab.path === 'categories'
                  ? coverage.counts.categories
                  : tab.path === 'items'
                    ? coverage.counts.items
                    : coverage.counts.methods
                : '—'}
            </span>
          </NavLink>
        ))}
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <form
              className="flex flex-1 gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                setSearch(keyword)
              }}
            >
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  placeholder="搜索名称或别名"
                />
              </div>
              <Button type="submit" variant="secondary">搜索</Button>
            </form>
          </div>
          {data ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="secondary">词典 {data.version}</Badge>
              <span>项目大类 {data.counts.categories}</span>
              <span>·</span>
              <span>检测项目 {data.counts.items}</span>
              <span>·</span>
              <span>试验方法 {data.counts.methods}</span>
              <span>·</span>
              <span>当前 {data.total} 条</span>
              {coverage?.versions?.[entryType] ? (
                <Badge variant="outline">{coverage.versions[entryType]}</Badge>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6"><Skeleton className="h-48 w-full rounded-xl" /></div>
          ) : entries.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <BookOpenText className="h-8 w-8 text-muted-foreground/50" />
              <p className="text-sm font-medium">没有匹配的词典条目</p>
            </div>
          ) : (
            <Table className="min-w-[840px]">
              <TableHeader>
                <TableRow>
                  <TableHead>业务名称</TableHead>
                  <TableHead>编码</TableHead>
                  <TableHead>族</TableHead>
                  {dictionaryType === 'items' ? <TableHead>所属大类</TableHead> : null}
                  {dictionaryType === 'methods' ? <TableHead>标准号</TableHead> : null}
                  <TableHead>别名</TableHead>
                  <TableHead>状态</TableHead>
                  {canEdit ? <TableHead className="w-40 text-right">操作</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.slice(0, 500).map((entry) => (
                  <TableRow key={`${entry.type}-${entry.business_code}`}>
                    <TableCell className="font-medium">{entry.business_name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {entry.business_code}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{entry.family || '-'}</TableCell>
                    {dictionaryType === 'items' ? (
                      <TableCell className="text-xs text-muted-foreground">
                        {entry.category_name || entry.category_code || '-'}
                      </TableCell>
                    ) : null}
                    {dictionaryType === 'methods' ? (
                      <TableCell className="text-xs text-muted-foreground">
                        {entry.standard_no || '-'}
                      </TableCell>
                    ) : null}
                    <TableCell className="text-xs text-muted-foreground">
                      {entry.aliases?.length ? entry.aliases.join('、') : '-'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={entry.status === 'active' ? 'success' : 'secondary'}>
                        {entry.status === 'active' ? '启用' : '停用'}
                      </Badge>
                    </TableCell>
                    {canEdit ? (
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="gap-1 text-xs"
                          onClick={() => {
                            setAliasTarget(entry)
                            setAliasValue('')
                          }}
                        >
                          <Plus className="h-3.5 w-3.5" />
                          别名
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs"
                          onClick={() => void toggleStatus(entry)}
                        >
                          {entry.status === 'active' ? '停用' : '启用'}
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {entryType === 'category' ? (
              <Badge variant="secondary">以词典为准</Badge>
            ) : (
              <Badge variant="warning">待处理新词 {pendingItems.length}</Badge>
            )}
            <span className="text-xs text-muted-foreground">
              {entryType === 'category'
                ? '项目大类以词典为准，不生成新词候选；词典之外的大类不进入抽取结果。'
                : `未命中的${TYPE_LABELS[entryType]}会在抽取详情页黄色标识；采纳后写入当前词典，重新解析生效。`}
            </span>
          </div>
          {entryType === 'category' ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              项目大类不产生新词候选
            </p>
          ) : pendingItems.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              暂无待处理新词
            </p>
          ) : (
            <div className="divide-y divide-border/50">
              {pendingItems.slice(0, 20).map((term) => (
                <div
                  key={`${term.document_id}-${term.type}-${term.raw}`}
                  className="flex flex-wrap items-center gap-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{term.raw}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {term.family || '未知族'} ·
                      <Link
                        to={`/standard/extraction/${term.document_id}`}
                        className="ml-1 text-primary hover:underline"
                      >
                        查看来源
                      </Link>
                    </p>
                  </div>
                  {canEdit ? (
                    <div className="flex gap-1">
                      <Button size="sm" variant="outline" onClick={() => openReview(term)}>
                        采纳
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={reviewBusy}
                        onClick={() => void rejectPending(term)}
                      >
                        忽略
                      </Button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(aliasTarget)}
        onOpenChange={(open) => {
          if (!open) setAliasTarget(null)
        }}
        title="添加业务别名"
      >
        <p className="-mt-2 mb-4 rounded-lg bg-muted/50 px-3 py-2 text-sm">
          {aliasTarget?.business_name}（{aliasTarget?.business_code}）
        </p>
        <div className="space-y-1.5">
          <Label htmlFor="alias-value">别名</Label>
          <Input
            id="alias-value"
            value={aliasValue}
            onChange={(event) => setAliasValue(event.target.value)}
            placeholder="原文中的写法，例如：抗拉强度 Rm"
          />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setAliasTarget(null)}>取消</Button>
          <Button disabled={!aliasValue.trim() || busy} onClick={() => void addAlias()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          if (!open) setCreateOpen(false)
        }}
        title={`新建${TYPE_LABELS[entryType]}`}
      >
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="entry-name">业务名称</Label>
            <Input
              id="entry-name"
              value={form.business_name}
              onChange={(event) => setForm({ ...form, business_name: event.target.value })}
              placeholder="例如：抗拉强度(Rm)"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="entry-code">业务编码（可空，自动生成）</Label>
            <Input
              id="entry-code"
              value={form.business_code}
              onChange={(event) => setForm({ ...form, business_code: event.target.value })}
              placeholder="例如：TENS_RT:RM"
            />
          </div>
          {dictionaryType === 'items' ? (
            <div className="space-y-1.5">
              <Label htmlFor="entry-category">所属项目大类</Label>
              <select
                id="entry-category"
                className="h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
                value={form.category_code}
                onChange={(event) => setForm({ ...form, category_code: event.target.value })}
              >
                <option value="">请选择</option>
                {(categories?.entries ?? []).map((entry) => (
                  <option key={entry.business_code} value={entry.business_code}>
                    {entry.business_name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {dictionaryType === 'methods' ? (
            <div className="space-y-1.5">
              <Label htmlFor="entry-standard">标准号（含年代号）</Label>
              <Input
                id="entry-standard"
                value={form.standard_no}
                onChange={(event) => setForm({ ...form, standard_no: event.target.value })}
                placeholder="例如：GB/T 228.1-2021"
              />
            </div>
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="entry-family">族（可空）</Label>
            <Input
              id="entry-family"
              value={form.family}
              onChange={(event) => setForm({ ...form, family: event.target.value })}
              placeholder="例如：tensile / chemical_composition"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="entry-aliases">别名（逗号分隔）</Label>
            <Input
              id="entry-aliases"
              value={form.aliases}
              onChange={(event) => setForm({ ...form, aliases: event.target.value })}
              placeholder="例如：Rm,抗拉强度"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
          <Button disabled={!form.business_name.trim() || busy} onClick={() => void createEntry()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            创建
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={Boolean(reviewTarget)}
        onOpenChange={(open) => {
          if (!open) setReviewTarget(null)
        }}
        title={`采纳新${TYPE_LABELS[entryType]}`}
      >
        <p className="-mt-2 mb-4 rounded-lg bg-muted/50 px-3 py-2 text-sm">
          原文：{reviewTarget?.raw}
        </p>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="review-name">业务名称</Label>
            <Input
              id="review-name"
              value={reviewForm.business_name}
              onChange={(event) =>
                setReviewForm({ ...reviewForm, business_name: event.target.value })
              }
            />
          </div>
          {entryType === 'item' ? (
            <div className="space-y-1.5">
              <Label htmlFor="review-category">所属项目大类</Label>
              <select
                id="review-category"
                className="h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
                value={reviewForm.category_code}
                onChange={(event) =>
                  setReviewForm({ ...reviewForm, category_code: event.target.value })
                }
              >
                <option value="">请选择</option>
                {(categories?.entries ?? []).map((entry) => (
                  <option key={entry.business_code} value={entry.business_code}>
                    {entry.business_name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {entryType === 'method' ? (
            <div className="space-y-1.5">
              <Label htmlFor="review-standard">标准号（含年代号）</Label>
              <Input
                id="review-standard"
                value={reviewForm.standard_no}
                onChange={(event) =>
                  setReviewForm({ ...reviewForm, standard_no: event.target.value })
                }
              />
            </div>
          ) : null}
          <p className="text-xs text-muted-foreground">
            采纳后写入当前{TYPE_LABELS[entryType]}词典，相关文档需要重新解析才会使用新词条。
          </p>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setReviewTarget(null)}>取消</Button>
          <Button disabled={reviewBusy} onClick={() => void submitReview()}>
            {reviewBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            采纳
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
