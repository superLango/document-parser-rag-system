import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  BookMarked,
  ChevronDown,
  ChevronRight,
  FileBox,
  FolderTree,
  FileText,
  LayoutTemplate,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  Settings2,
  Trash2,
  X,
} from 'lucide-react'
import { extractionConfigApi, promptApi, type PromptTemplate, type QuerySource, type SchemaCategory, type SchemaField, type SchemaTemplate } from '@/api/modules/extractionConfig'
import { glossaryApi } from '@/api/modules/glossary'
import type { TermBase } from '@/api/types'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/PageHeader'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { useToast } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/auth'
import { useKbDetail } from './KbDetailLayout'
import KbGlobalConfig from './KbGlobalConfig'
import KbRuleGroups from './KbRuleGroups'
import KbScriptManager from './KbScriptManager'

const MANUAL_TERM_FIELDS = [
  { name: 'term_name', label: '术语名称' },
  { name: 'standard_name', label: '标准名称' },
  { name: 'definition', label: '定义' },
  { name: 'category', label: '分类' },
  { name: 'synonyms', label: '同义词' },
  { name: 'aliases', label: '别称' },
  { name: 'standard_number', label: '标准编号' },
]

const EMPTY_QUERY: QuerySource = {
  label: '', term_base_id: '', group_field: '', value_field: '',
  in_query: false, dedupe: false, query_main_limit: 30, query_refined_limit: 8,
}

interface ConfirmState {
  title: string
  description: string
  onConfirm: () => Promise<void>
}

export default function KbExtractionConfigPage() {
  const { kb } = useKbDetail()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'

  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTabState] = useState(searchParams.get('tab') || 'global')

  function handleTabChange(next: string) {
    setTabState(next)
    setSearchParams({ tab: next }, { replace: true })
  }
  const [loading, setLoading] = useState(true)
  const [templates, setTemplates] = useState<SchemaTemplate[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SchemaTemplate | null>(null)
  const [termBases, setTermBases] = useState<TermBase[]>([])
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set())
  const [expandedPool, setExpandedPool] = useState<Set<number>>(new Set())
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const [confirming, setConfirming] = useState(false)

  // 模板弹窗
  const [tplOpen, setTplOpen] = useState(false)
  const [tplForm, setTplForm] = useState({ name: '', description: '' })
  const [tplSaving, setTplSaving] = useState(false)

  // 类别弹窗
  const [catOpen, setCatOpen] = useState(false)
  const [catEdit, setCatEdit] = useState<SchemaCategory | null>(null)
  const [catForm, setCatForm] = useState({
    name: '', description: '', return_type: 'array', extraction_strategy: 'auto',
    fixed_query: '', confidence_threshold: '' as string | number, top_k: '' as string | number,
    rerank_top_k: '' as string | number, max_tokens: '' as string | number,
    name_source: 'manual', name_term_base_id: '', name_term_field: '',
    query_sources: [] as QuerySource[], is_active: true,
  })
  const [catSaving, setCatSaving] = useState(false)

  // 字段弹窗
  const [fieldOpen, setFieldOpen] = useState(false)
  const [fieldEdit, setFieldEdit] = useState<SchemaField | null>(null)
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null)
  const [fieldForm, setFieldForm] = useState({ name: '', type: 'string', description: '', example: '', required: true })
  const [fieldSaving, setFieldSaving] = useState(false)

  // Prompt
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [promptLoading, setPromptLoading] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const [promptForm, setPromptForm] = useState({
    name: '', description: '', scope: 'simple', schema_template_id: '', category_ids: [] as string[], is_active: true,
  })
  const [promptSaving, setPromptSaving] = useState(false)


  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [tplRes, tbRes] = await Promise.all([
        extractionConfigApi.listSchemaTemplates(kb.id),
        glossaryApi.list(kb.id, { page_size: 50 }),
      ])
      setTemplates(tplRes.items)
      setTermBases(tbRes.items)
      // 对齐原项目：进入页签自动选中第一个模板
      setSelectedId((prev) => prev ?? tplRes.items[0]?.id ?? null)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '加载失败'
      toast('error', '加载失败', msg)
    } finally {
      setLoading(false)
    }
  }, [kb.id, toast])

  useEffect(() => { void load() }, [load])

  const selected = useMemo(() => templates.find((t) => t.id === selectedId) ?? null, [templates, selectedId])

  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    extractionConfigApi.getSchemaTemplate(kb.id, selectedId)
      .then(setDetail)
      .catch(() => setDetail(null))
  }, [selectedId, kb.id])

  function effectiveFields(base: TermBase | undefined): Array<{ name: string; label: string }> {
    if (!base) return []
    if (base.source_type === 'manual') return MANUAL_TERM_FIELDS
    const aliases = base.column_aliases ?? {}
    return (base.columns ?? []).map((c) => ({ name: c.name, label: aliases[c.name] || c.label || c.name }))
  }

  function termBaseName(id: string | null): string {
    const b = termBases.find((x) => x.id === id)
    return b ? b.name : ''
  }

  function categoryDisplayName(cat: SchemaCategory): string {
    if (cat.name && cat.name.trim()) return cat.name
    if (cat.name_source === 'term_base') return termBaseName(cat.name_term_base_id) || '术语类别'
    return cat.name || '未命名类别'
  }

  // ---------- 模板 ----------
  function openCreateTemplate() {
    setTplForm({ name: '', description: '' })
    setTplOpen(true)
  }

  async function saveTemplate() {
    if (!tplForm.name.trim()) { toast('warning', '请填写模板名称'); return }
    setTplSaving(true)
    try {
      const created = await extractionConfigApi.createSchemaTemplate(kb.id, tplForm)
      toast('success', '模板已创建')
      setTplOpen(false)
      await load()
      setSelectedId(created.id)
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setTplSaving(false)
    }
  }

  function requestDeleteTemplate(t: SchemaTemplate) {
    setConfirmState({
      title: '删除模板',
      description: `确定删除模板「${t.name}」？其下所有类别与字段将一并删除。`,
      onConfirm: async () => {
        await extractionConfigApi.deleteSchemaTemplate(kb.id, t.id)
        if (selectedId === t.id) setSelectedId(null)
        await load()
      },
    })
  }

  // ---------- 类别 ----------
  function openCreateCategory() {
    setCatEdit(null)
    setActiveCategoryId(null)
    setCatForm({
      name: '', description: '', return_type: 'array', extraction_strategy: 'auto',
      fixed_query: '', confidence_threshold: '', top_k: '', rerank_top_k: '', max_tokens: '',
      name_source: 'manual', name_term_base_id: '', name_term_field: '',
      query_sources: [], is_active: true,
    })
    setCatOpen(true)
  }

  function openEditCategory(cat: SchemaCategory) {
    setCatEdit(cat)
    setActiveCategoryId(cat.id)
    setCatForm({
      name: cat.name, description: cat.description, return_type: cat.return_type,
      extraction_strategy: cat.extraction_strategy, fixed_query: cat.fixed_query,
      confidence_threshold: cat.confidence_threshold ?? '', top_k: cat.top_k ?? '',
      rerank_top_k: cat.rerank_top_k ?? '', max_tokens: cat.max_tokens ?? '',
      name_source: cat.name_source, name_term_base_id: cat.name_term_base_id ?? '',
      name_term_field: cat.name_term_field, query_sources: cat.query_sources.map((q) => ({ ...q })),
      is_active: cat.is_active,
    })
    setCatOpen(true)
  }

  function addQuerySource() {
    setCatForm((f) => {
      const next = [...f.query_sources, { ...EMPTY_QUERY }]
      setExpandedPool((st) => new Set(st).add(next.length - 1))
      return { ...f, query_sources: next }
    })
  }

  function toggleExpandPool(idx: number) {
    setExpandedPool((st) => {
      const n = new Set(st)
      if (n.has(idx)) n.delete(idx); else n.add(idx)
      return n
    })
  }

  function saveQuerySource(idx: number) {
    const qs = catForm.query_sources[idx]
    const tb = termBases.find((b) => b.id === qs.term_base_id)
    if (tb) {
      setCatForm((f) => ({ ...f, query_sources: f.query_sources.map((q, i) => (i === idx ? { ...q, label: tb.name } : q)) }))
    }
    setExpandedPool((st) => { const n = new Set(st); n.delete(idx); return n })
  }

  function updateQuerySource(idx: number, patch: Partial<QuerySource>) {
    setCatForm((f) => ({ ...f, query_sources: f.query_sources.map((q, i) => (i === idx ? { ...q, ...patch } : q)) }))
  }

  function removeQuerySource(idx: number) {
    setCatForm((f) => ({ ...f, query_sources: f.query_sources.filter((_, i) => i !== idx) }))
  }

  async function saveCategory() {
    if (!selected) return
    if (catForm.name_source === 'manual' && !catForm.name.trim()) {
      toast('warning', '请填写类别名称')
      return
    }
    if (catForm.name_source === 'term_base') {
      if (!catForm.name_term_base_id) { toast('warning', '请选择名称来源术语集'); return }
      if (!catForm.name_term_field) { toast('warning', '请选择名称来源字段'); return }
    }
    for (const [i, q] of catForm.query_sources.entries()) {
      if (!q.label.trim()) { toast('warning', `第 ${i + 1} 个术语集名称不能为空`); return }
      if (!q.term_base_id) { toast('warning', `第 ${i + 1} 个术语集未选择术语集`); return }
      if (!q.value_field) { toast('warning', `第 ${i + 1} 个术语集的值字段必选`); return }
    }
    const payload: Record<string, unknown> = {
      name: catForm.name, description: catForm.description, return_type: catForm.return_type,
      extraction_strategy: catForm.extraction_strategy, fixed_query: catForm.fixed_query,
      top_k: catForm.top_k === '' ? null : Number(catForm.top_k),
      rerank_top_k: catForm.rerank_top_k === '' ? null : Number(catForm.rerank_top_k),
      max_tokens: catForm.max_tokens === '' ? null : Number(catForm.max_tokens),
      name_source: catForm.name_source, name_term_base_id: catForm.name_term_base_id || null,
      name_term_field: catForm.name_term_field, query_sources: catForm.query_sources, is_active: catForm.is_active,
    }
    if (catForm.extraction_strategy === 'auto') {
      payload.confidence_threshold = catForm.confidence_threshold === '' ? null : Number(catForm.confidence_threshold)
    }
    setCatSaving(true)
    try {
      if (catEdit) {
        await extractionConfigApi.updateSchemaCategory(kb.id, selected.id, catEdit.id, payload)
      } else {
        await extractionConfigApi.createSchemaCategory(kb.id, selected.id, payload)
      }
      toast('success', catEdit ? '类别已更新' : '类别已创建')
      setCatOpen(false)
      const d = await extractionConfigApi.getSchemaTemplate(kb.id, selected.id)
      setDetail(d)
      setTemplates((prev) => prev.map((t) => (t.id === d.id ? d : t)))
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setCatSaving(false)
    }
  }

  function requestDeleteCategory(cat: SchemaCategory) {
    if (!selected) return
    setConfirmState({
      title: '删除类别',
      description: `确定删除类别「${categoryDisplayName(cat)}」？其下所有字段将一并删除。`,
      onConfirm: async () => {
        await extractionConfigApi.deleteSchemaCategory(kb.id, selected.id, cat.id)
        const d = await extractionConfigApi.getSchemaTemplate(kb.id, selected.id)
        setDetail(d)
        setTemplates((prev) => prev.map((t) => (t.id === d.id ? d : t)))
      },
    })
  }

  // ---------- 字段 ----------
  function openCreateField(catId: string) {
    setFieldEdit(null)
    setActiveCategoryId(catId)
    setFieldForm({ name: '', type: 'string', description: '', example: '', required: true })
    setFieldOpen(true)
  }

  function openEditField(catId: string, field: SchemaField) {
    setFieldEdit(field)
    setActiveCategoryId(catId)
    setFieldForm({ name: field.name, type: field.type, description: field.description, example: field.example ?? '', required: field.required })
    setFieldOpen(true)
  }

  async function saveField() {
    if (!selected || !activeCategoryId) return
    if (!fieldForm.name.trim()) { toast('warning', '请填写字段名称'); return }
    setFieldSaving(true)
    try {
      if (fieldEdit) {
        await extractionConfigApi.updateSchemaField(kb.id, selected.id, activeCategoryId, fieldEdit.id, fieldForm)
      } else {
        await extractionConfigApi.createSchemaField(kb.id, selected.id, activeCategoryId, fieldForm)
      }
      toast('success', fieldEdit ? '字段已更新' : '字段已创建')
      setFieldOpen(false)
      const d = await extractionConfigApi.getSchemaTemplate(kb.id, selected.id)
      setDetail(d)
      setTemplates((prev) => prev.map((t) => (t.id === d.id ? d : t)))
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setFieldSaving(false)
    }
  }

  function requestDeleteField(cat: SchemaCategory, field: SchemaField) {
    if (!selected) return
    setConfirmState({
      title: '删除字段',
      description: `确定删除字段「${field.name}」？`,
      onConfirm: async () => {
        await extractionConfigApi.deleteSchemaField(kb.id, selected.id, cat.id, field.id)
        const d = await extractionConfigApi.getSchemaTemplate(kb.id, selected.id)
        setDetail(d)
        setTemplates((prev) => prev.map((t) => (t.id === d.id ? d : t)))
      },
    })
  }

  async function loadPrompts() {
    setPromptLoading(true)
    try {
      const res = await promptApi.list(kb.id)
      setPrompts(res.items)
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setPromptLoading(false)
    }
  }

  useEffect(() => {
    if (tab === 'prompt') void loadPrompts()
  }, [tab, kb.id])  // eslint-disable-line react-hooks/exhaustive-deps

  function openCreatePrompt() {
    setPromptForm({ name: '', description: '', scope: 'simple', schema_template_id: '', category_ids: [], is_active: true })
    setPromptOpen(true)
  }

  function togglePromptCat(catId: string) {
    setPromptForm((f) => ({
      ...f,
      category_ids: f.category_ids.includes(catId)
        ? f.category_ids.filter((c) => c !== catId)
        : [...f.category_ids, catId],
    }))
  }

  async function savePrompt() {
    if (!promptForm.name.trim()) { toast('warning', '请填写模板名称'); return }
    if (promptForm.scope === 'schema' && !promptForm.schema_template_id) {
      toast('warning', '请选择 Schema 模板'); return
    }
    if (promptForm.scope === 'schema' && promptForm.category_ids.length === 0) {
      toast('warning', '请至少选择一个类别'); return
    }
    setPromptSaving(true)
    try {
      const created = await promptApi.create(kb.id, promptForm)
      setPromptOpen(false)
      navigate(`/kb/${kb.id}/extraction-config/prompts/${created.id}`)
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setPromptSaving(false)
    }
  }

  function requestDeletePrompt(p: PromptTemplate) {
    setConfirmState({
      title: '删除 Prompt',
      description: `确定删除 Prompt「${p.name}」？`,
      onConfirm: async () => {
        await promptApi.remove(kb.id, p.id)
        await loadPrompts()
      },
    })
  }

  function openPromptEditor(p: PromptTemplate) {
    void navigate(`/kb/${kb.id}/extraction-config/prompts/${p.id}`)
  }

  async function runConfirm() {
    if (!confirmState) return
    setConfirming(true)
    try {
      await confirmState.onConfirm()
      toast('success', '已删除')
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '删除失败')
    } finally {
      setConfirming(false)
      setConfirmState(null)
    }
  }

  function toggleCat(catId: string) {
    setExpandedCats((s) => {
      const n = new Set(s)
      if (n.has(catId)) n.delete(catId); else n.add(catId)
      return n
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="知识库"
        title="抽取配置"
        description="Schema 模板、Prompt 模板、后处理与校验规则、脚本管理"
      />

      <Tabs
        value={tab}
        onValueChange={handleTabChange}
        items={[
          { value: 'global', label: <><Settings2 className="h-4 w-4" /> 全局配置</> },
          { value: 'schema', label: <><LayoutTemplate className="h-4 w-4" /> Schema 模板</> },
          { value: 'prompt', label: <><FileText className="h-4 w-4" /> Prompt 模板</> },
          { value: 'rules', label: <><ListChecks className="h-4 w-4" /> 后处理与校验规则</> },
          { value: 'scripts', label: <><Settings2 className="h-4 w-4" /> 脚本管理</> },
        ]}
      />

      {tab === 'global' && (
        <KbGlobalConfig kbId={kb.id} canManage={canManage} />
      )}

      {tab === 'prompt' && (
        <Card>
          <CardContent className="space-y-2 p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Prompt 模板</p>
              {canManage && (
                <Button size="sm" onClick={openCreatePrompt} className="gap-1" data-testid="btn-new-prompt">
                  <Plus className="h-4 w-4" /> 新建 Prompt
                </Button>
              )}
            </div>
            {promptLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : prompts.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">暂无 Prompt 模板</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {prompts.map((p) => (
                  <Card key={p.id} className="bg-muted/20">
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-foreground">{p.name}</p>
                          <Badge variant="outline" className="text-[10px]">{p.scope === 'schema' ? 'Schema' : '简单'}</Badge>
                        </div>
                        {canManage && (
                          <div className="flex items-center gap-1">
                            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" title="编辑" onClick={() => openPromptEditor(p)} data-testid={`btn-open-prompt-${p.id}`}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive hover:text-destructive" title="删除" onClick={() => requestDeletePrompt(p)} data-testid={`btn-del-prompt-${p.id}`}>
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        )}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{p.description || '暂无描述'}</p>
                      <p className="mt-2 line-clamp-3 rounded-md bg-muted p-2 font-mono text-xs">{p.system_prompt || p.user_prompt}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {tab === 'rules' && (
        <KbRuleGroups kbId={kb.id} canManage={canManage} templates={templates} />
      )}

      {tab === 'scripts' && (
        <KbScriptManager kbId={kb.id} canManage={canManage} />
      )}

      {tab === 'schema' && (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          {/* 模板列表 */}
          <Card className="h-fit">
            <CardContent className="space-y-2 p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">Schema 模板</p>
                {canManage && (
                  <Button size="sm" onClick={openCreateTemplate} className="gap-1" data-testid="btn-new-template">
                    <Plus className="h-4 w-4" /> 新建模板
                  </Button>
                )}
              </div>
              {loading ? (
                <Skeleton className="h-24 w-full" />
              ) : templates.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-10 text-center">
                  <LayoutTemplate className="h-8 w-8 text-muted-foreground/50" />
                  <p className="text-sm font-medium">暂无模板</p>
                  <p className="text-xs text-muted-foreground">创建 Schema 模板以定义抽取结构</p>
                </div>
              ) : (
                templates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    data-testid={`tpl-item-${t.id}`}
                    onClick={() => setSelectedId(t.id)}
                    className={`w-full rounded-lg border p-3 text-left transition-all ${
                      selectedId === t.id ? 'border-primary/50 bg-secondary/40 shadow-soft' : 'border-border hover:bg-muted/50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-medium">{t.name}</p>
                      {!t.is_active && <Badge variant="outline" className="text-[10px]">停用</Badge>}
                    </div>
                    {t.description && <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{t.description}</p>}
                  </button>
                ))
              )}
            </CardContent>
          </Card>

          {/* 模板详情 */}
          <Card>
            <CardContent className="space-y-4 p-4">
              {!selected ? (
                <div className="flex flex-col items-center gap-2 py-16 text-center">
                  <LayoutTemplate className="h-8 w-8 text-muted-foreground/50" />
                  <p className="text-sm font-medium">选择左侧模板查看类别与字段</p>
                </div>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-base font-semibold">{detail?.name ?? selected.name}</h3>
                      <p className="mt-0.5 text-xs text-muted-foreground">{detail?.description || '暂无描述'}</p>
                    </div>
                    {canManage && (
                      <div className="flex items-center gap-1">
                        <Button variant="outline" size="sm" onClick={openCreateCategory} className="gap-1" data-testid="btn-new-category">
                          <Plus className="h-4 w-4" /> 新建类别
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => requestDeleteTemplate(selected)} className="text-destructive hover:text-destructive" title="删除模板">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </div>

                  {(detail?.categories ?? []).length === 0 ? (
                    <div className="flex flex-col items-center gap-2 py-12 text-center">
                      <FolderTree className="h-8 w-8 text-muted-foreground/50" />
                      <p className="text-sm font-medium">暂无类别</p>
                      <p className="text-xs text-muted-foreground">添加类别以定义抽取目标（如：室温拉伸、化学成分）</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {(detail?.categories ?? []).map((cat) => (
                        <div key={cat.id} className="overflow-hidden rounded-xl border border-border">
                          <div className="flex items-center gap-3 p-3" data-testid={`schema-cat-${cat.id}`}>
                            <button type="button" onClick={() => toggleCat(cat.id)} className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted">
                              {expandedCats.has(cat.id) ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </button>
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                              <FolderTree className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="font-medium text-foreground">{categoryDisplayName(cat)}</p>
                                <Badge variant="outline" className="text-[10px]">{cat.return_type}</Badge>
                                <Badge variant="secondary" className="text-[10px]">{cat.extraction_strategy}</Badge>
                                {cat.name_source === 'term_base' && (
                                  <Badge variant="secondary" className="bg-amber-500/10 text-amber-600 text-[10px]">使用术语库</Badge>
                                )}
                                {(cat.query_sources ?? []).some((q) => q.in_query) && (
                                  <Badge variant="secondary" className="bg-amber-500/10 text-amber-600 text-[10px]">
                                    Query术语集({(cat.query_sources ?? []).filter((q) => q.in_query).length})
                                  </Badge>
                                )}
                                {cat.top_k ? <Badge variant="secondary" className="text-[10px]">top_k={cat.top_k}</Badge> : null}
                                {!cat.is_active && <Badge variant="secondary" className="bg-danger/10 text-destructive text-[10px]">停用</Badge>}
                              </div>
                              {cat.description && <p className="mt-0.5 truncate text-xs text-muted-foreground">{cat.description}</p>}
                            </div>
                            {canManage && (
                              <div className="flex shrink-0 items-center gap-1">
                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" title="添加字段" onClick={() => openCreateField(cat.id)}>
                                  <Plus className="h-4 w-4" />
                                </Button>
                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" title="编辑" onClick={() => openEditCategory(cat)}>
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive hover:text-destructive" title="删除" onClick={() => requestDeleteCategory(cat)}>
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            )}
                          </div>
                          {expandedCats.has(cat.id) && (
                            <div className="space-y-2 p-3">
                              {(cat.query_sources?.length ?? 0) > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {cat.query_sources.map((q, qi) => (
                                    <Badge key={qi} variant="secondary" className="gap-1 text-[10px]">
                                      <BookMarked className="h-3 w-3" />
                                      {q.label || termBaseName(q.term_base_id)}
                                      {q.in_query && <span className="text-primary">参与 Query</span>}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                              {cat.fields.length === 0 ? (
                                <div className="flex flex-col items-center gap-1.5 py-6 text-center">
                                  <FileBox className="h-6 w-6 text-muted-foreground/50" />
                                  <p className="text-xs font-medium">暂无字段</p>
                                  <p className="text-[11px] text-muted-foreground">添加字段以定义抽取项</p>
                                </div>
                              ) : (
                                cat.fields.map((field) => (
                                  <div key={field.id} className="flex items-center gap-3 rounded-md bg-muted/40 p-2.5">
                                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                                      <FileBox className="h-4 w-4" />
                                    </div>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-2">
                                        <p className="text-sm font-medium text-foreground">{field.name}</p>
                                        <Badge variant="outline" className="text-[10px]">{field.type}</Badge>
                                        {field.required && <Badge variant="secondary" className="text-[10px]">必填</Badge>}
                                      </div>
                                      {field.description && <p className="mt-0.5 truncate text-xs text-muted-foreground">{field.description}</p>}
                                    </div>
                                    {canManage && (
                                      <div className="flex shrink-0 items-center gap-1">
                                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="编辑" onClick={() => openEditField(cat.id, field)}><Pencil className="h-3.5 w-3.5" /></Button>
                                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive hover:text-destructive" title="删除" onClick={() => requestDeleteField(cat, field)}><Trash2 className="h-3.5 w-3.5" /></Button>
                                      </div>
                                    )}
                                  </div>
                                ))
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* 模板弹窗 */}
      <Dialog open={tplOpen} onOpenChange={(o) => { if (!o) setTplOpen(false) }} title="新建 Schema 模板" className="max-w-xl">
        <div className="space-y-4">
          <label className="block text-xs font-medium text-muted-foreground">模板名称 *
            <Input value={tplForm.name} onChange={(e) => setTplForm({ ...tplForm, name: e.target.value })} className="mt-1 h-10" data-testid="tpl-name-input" />
          </label>
          <label className="block text-xs font-medium text-muted-foreground">描述
            <textarea value={tplForm.description} onChange={(e) => setTplForm({ ...tplForm, description: e.target.value })} rows={2} className="mt-1 min-h-[60px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-soft focus-visible:border-primary/50" />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="ghost" onClick={() => setTplOpen(false)}>取消</Button>
          <Button onClick={saveTemplate} disabled={tplSaving || !tplForm.name.trim()} className="gap-1.5" data-testid="btn-tpl-save">
            {tplSaving && <Loader2 className="h-4 w-4 animate-spin" />} 创建
          </Button>
        </div>
      </Dialog>

      {/* Prompt 弹窗 */}
      <Dialog open={promptOpen} onOpenChange={(o) => { if (!o) setPromptOpen(false) }} title="新建 Prompt" className="max-w-xl">
        <div className="space-y-4">
          <label className="block text-xs font-medium text-muted-foreground">模板名称 *
            <Input value={promptForm.name} onChange={(e) => setPromptForm({ ...promptForm, name: e.target.value })} className="mt-1 h-10" data-testid="prompt-name-input" />
          </label>
          <label className="block text-xs font-medium text-muted-foreground">描述
            <Input value={promptForm.description} onChange={(e) => setPromptForm({ ...promptForm, description: e.target.value })} className="mt-1 h-10" />
          </label>
          <label className="block text-xs font-medium text-muted-foreground">模式
            <Select value={promptForm.scope} onChange={(e) => setPromptForm({ ...promptForm, scope: e.target.value, schema_template_id: '', category_ids: [] })} className="mt-1 h-10" data-testid="prompt-scope-select">
              <option value="simple">simple（单个 user 提示词）</option>
              <option value="schema">schema（绑定 Schema，按类别拆分 user 提示词）</option>
            </Select>
          </label>
          {promptForm.scope === 'schema' && (
            <>
              <label className="block text-xs font-medium text-muted-foreground">选择 Schema 模板 *
                <Select value={promptForm.schema_template_id} onChange={(e) => {
                  const tpl = templates.find((t) => t.id === e.target.value)
                  setPromptForm({
                    ...promptForm,
                    schema_template_id: e.target.value,
                    category_ids: tpl ? tpl.categories.map((c) => c.id) : [],
                  })
                }} className="mt-1 h-10" data-testid="prompt-template-select">
                  <option value="">请选择 Schema 模板</option>
                  {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </Select>
              </label>
              {templates.find((t) => t.id === promptForm.schema_template_id)?.categories.length ? (
                <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border p-2">
                  {templates.find((t) => t.id === promptForm.schema_template_id)?.categories.map((c) => (
                    <label key={c.id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-muted">
                      <input type="checkbox" className="h-4 w-4 accent-primary" checked={promptForm.category_ids.includes(c.id)} onChange={() => togglePromptCat(c.id)} data-testid={`prompt-cat-${c.id}`} />
                      {c.name || (c.name_source === 'term_base' ? (termBases.find((b) => b.id === c.name_term_base_id)?.name ?? '术语类别') : '未命名类别')}
                      {c.name_source === 'term_base' && <Badge variant="secondary" className="text-[10px]">术语库</Badge>}
                    </label>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">该模板暂无类别</p>
              )}            </>
          )}
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={promptForm.is_active} onCheckedChange={(v) => setPromptForm({ ...promptForm, is_active: v })} /> 启用
          </label>
          <p className="text-xs text-muted-foreground">创建后进入编辑页，可配置 system / user 提示词并使用 $&#123;字段名&#125; 占位符。</p>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="ghost" onClick={() => setPromptOpen(false)}>取消</Button>
          <Button onClick={savePrompt} disabled={promptSaving || !promptForm.name.trim()} className="gap-1.5" data-testid="btn-prompt-save">
            {promptSaving && <Loader2 className="h-4 w-4 animate-spin" />} 创建
          </Button>
        </div>
      </Dialog>

      {/* 类别弹窗 */}
      <Dialog open={catOpen} onOpenChange={(o) => { if (!o) setCatOpen(false) }} title={catEdit ? '编辑类别' : '新建类别'} className="max-w-2xl">
        <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">类别名称来源</p>
            <Select value={catForm.name_source} onChange={(e) => setCatForm({ ...catForm, name_source: e.target.value })} className="h-10">
              <option value="manual">手动输入</option>
              <option value="term_base">术语集</option>
            </Select>
          </div>
          {catForm.name_source === 'manual' ? (
            <label className="block text-xs font-medium text-muted-foreground">类别名称 *
              <Input value={catForm.name} onChange={(e) => setCatForm({ ...catForm, name: e.target.value })} placeholder="如：室温拉伸" className="mt-1 h-10" data-testid="cat-name-input" />
            </label>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-xs font-medium text-muted-foreground">名称来源术语集 *
                <Select value={catForm.name_term_base_id} onChange={(e) => setCatForm({ ...catForm, name_term_base_id: e.target.value, name_term_field: '' })} className="mt-1 h-10" data-testid="cat-term-base-select">
                  <option value="">选择术语集</option>
                  {termBases.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </Select>
              </label>
              <label className="block text-xs font-medium text-muted-foreground">取值字段
                <Select value={catForm.name_term_field} onChange={(e) => setCatForm({ ...catForm, name_term_field: e.target.value })} className="mt-1 h-10" disabled={!catForm.name_term_base_id} data-testid="cat-term-field-select">
                  <option value="">选择字段</option>
                  {effectiveFields(termBases.find((b) => b.id === catForm.name_term_base_id)).map((f) => (
                    <option key={f.name} value={f.name}>{f.label}</option>
                  ))}
                </Select>
              </label>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs font-medium text-muted-foreground">返回类型
              <Select value={catForm.return_type} onChange={(e) => setCatForm({ ...catForm, return_type: e.target.value })} className="mt-1 h-10">
                <option value="array">数组</option>
                <option value="object">对象</option>
              </Select>
            </label>
            <label className="block text-xs font-medium text-muted-foreground">抽取策略
              <Select value={catForm.extraction_strategy} onChange={(e) => setCatForm({ ...catForm, extraction_strategy: e.target.value })} className="mt-1 h-10">
                <option value="auto">auto（按置信度）</option>
                <option value="always">always（强制抽取）</option>
                <option value="never">never（不抽取）</option>
              </Select>
            </label>
          </div>
          <label className="block text-xs font-medium text-muted-foreground">固定 Query 文本
            <Input value={catForm.fixed_query} onChange={(e) => setCatForm({ ...catForm, fixed_query: e.target.value })} placeholder="如：标准名称 标准编号 文件编号" className="mt-1 h-10" />
          </label>

          {/* Query 关联（挂载到 Query 的术语集） */}
          <div className="space-y-2 rounded-xl border border-border p-3">
            <p className="text-xs font-medium text-muted-foreground">Query 关联（挂载到 Query 的术语集）</p>
            {catForm.query_sources.filter((qs) => qs.in_query).length === 0 ? (
              <p className="py-3 text-center text-xs text-muted-foreground">暂无参与 Query 的术语集，在下方术语集中开启“参与 Query”后展示</p>
            ) : (
              catForm.query_sources.map((qs, idx) => (
                qs.in_query ? (
                  <div key={idx} className="rounded-lg border border-border bg-muted/30 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="text-amber-500">#</span>
                        <p className="truncate text-sm font-medium text-foreground">{qs.label || '未命名术语集'}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-3">
                        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          主查询上限
                          <Input type="number" min={1} value={qs.query_main_limit} onChange={(e) => updateQuerySource(idx, { query_main_limit: Number(e.target.value) || 1 })} className="h-7 w-14" />
                        </label>
                        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          精简上限
                          <Input type="number" min={1} value={qs.query_refined_limit} onChange={(e) => updateQuerySource(idx, { query_refined_limit: Number(e.target.value) || 1 })} className="h-7 w-14" />
                        </label>
                        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          精简
                          <Switch checked={qs.dedupe} onCheckedChange={(v) => updateQuerySource(idx, { dedupe: v })} />
                        </label>
                        <Button type="button" variant="ghost" size="sm" title="取消与 Query 的关联（术语集保留）" onClick={() => updateQuerySource(idx, { in_query: false })}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : null
              ))
            )}
          </div>

          {/* Query 术语集 */}
          <div className="space-y-2 rounded-xl border border-border p-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground">Query 术语集</p>
              <Button type="button" variant="outline" size="sm" onClick={addQuerySource} className="gap-1"><Plus className="h-3.5 w-3.5" /> 添加术语集</Button>
            </div>
            {catForm.query_sources.length === 0 && <p className="py-3 text-center text-xs text-muted-foreground">暂无术语集，添加后用于构造动态 Query</p>}
            {catForm.query_sources.map((qs, idx) => (
              !expandedPool.has(idx) ? (
                <div key={idx} className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2">
                  <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => toggleExpandPool(idx)}>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate text-sm font-medium">{qs.label || `术语集 ${idx + 1}`}</span>
                  </button>
                  <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-destructive" onClick={() => removeQuerySource(idx)}><X className="h-3.5 w-3.5" /></Button>
                </div>
              ) : (
                <div key={idx} className="rounded-lg border border-border/70 p-3">
                  <div className="flex items-center justify-between">
                    <button type="button" className="flex items-center gap-1.5 text-sm font-medium" onClick={() => toggleExpandPool(idx)}>
                      <ChevronDown className="h-4 w-4 text-muted-foreground" /> 术语集 {idx + 1}
                    </button>
                    <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-destructive" onClick={() => removeQuerySource(idx)}><X className="h-3.5 w-3.5" /></Button>
                  </div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <Input value={qs.label} onChange={(e) => updateQuerySource(idx, { label: e.target.value })} placeholder="显示名称（必填）" className="h-9" data-testid={`qs-label-${idx}`} />
                    <Select value={qs.term_base_id} onChange={(e) => updateQuerySource(idx, { term_base_id: e.target.value, group_field: '', value_field: '' })} className="h-9" data-testid={`qs-term-${idx}`}>
                      <option value="">选择术语集</option>
                      {termBases.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                    </Select>
                    <Select value={qs.group_field} onChange={(e) => updateQuerySource(idx, { group_field: e.target.value })} className="h-9" disabled={!qs.term_base_id} data-testid={`qs-group-${idx}`}>
                      <option value="">分组字段（可选）</option>
                      {effectiveFields(termBases.find((b) => b.id === qs.term_base_id)).map((f) => <option key={f.name} value={f.name}>{f.label}</option>)}
                    </Select>
                    <Select value={qs.value_field} onChange={(e) => updateQuerySource(idx, { value_field: e.target.value })} className="h-9" disabled={!qs.term_base_id} data-testid={`qs-value-${idx}`}>
                      <option value="">值字段 *</option>
                      {effectiveFields(termBases.find((b) => b.id === qs.term_base_id)).map((f) => <option key={f.name} value={f.name}>{f.label}</option>)}
                    </Select>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-1.5 text-xs"><Switch checked={qs.in_query} onCheckedChange={(v) => updateQuerySource(idx, { in_query: v })} data-testid={`qs-in-query-${idx}`} /> 参与 Query</label>
                    <label className="flex items-center gap-1.5 text-xs"><Switch checked={qs.dedupe} onCheckedChange={(v) => updateQuerySource(idx, { dedupe: v })} /> 精简</label>
                    <label className="flex items-center gap-1.5 text-xs">主查询上限 <Input type="number" min={1} value={qs.query_main_limit} onChange={(e) => updateQuerySource(idx, { query_main_limit: Number(e.target.value) || 1 })} className="h-7 w-16" /></label>
                    <label className="flex items-center gap-1.5 text-xs">精简上限 <Input type="number" min={1} value={qs.query_refined_limit} onChange={(e) => updateQuerySource(idx, { query_refined_limit: Number(e.target.value) || 1 })} className="h-7 w-16" /></label>
                  </div>
                  <div className="mt-3 flex justify-end">
                    <Button type="button" size="sm" onClick={() => saveQuerySource(idx)} data-testid={`qs-save-${idx}`}>保存</Button>
                  </div>
                </div>
              )
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {catForm.extraction_strategy === 'auto' && (
              <label className="block text-xs font-medium text-muted-foreground">置信度阈值（覆盖全局）
                <Input type="number" step="0.05" value={catForm.confidence_threshold} onChange={(e) => setCatForm({ ...catForm, confidence_threshold: e.target.value })} placeholder="留空用全局默认" className="mt-1 h-10" />
              </label>
            )}
            <label className="block text-xs font-medium text-muted-foreground">检索 top_k（覆盖全局）
              <Input type="number" value={catForm.top_k} onChange={(e) => setCatForm({ ...catForm, top_k: e.target.value })} placeholder="留空用全局默认" className="mt-1 h-10" />
            </label>
            <label className="block text-xs font-medium text-muted-foreground">重排序 top_k（覆盖全局）
              <Input type="number" value={catForm.rerank_top_k} onChange={(e) => setCatForm({ ...catForm, rerank_top_k: e.target.value })} className="mt-1 h-10" />
            </label>
            <label className="block text-xs font-medium text-muted-foreground">最大输出 token（覆盖全局）
              <Input type="number" value={catForm.max_tokens} onChange={(e) => setCatForm({ ...catForm, max_tokens: e.target.value })} className="mt-1 h-10" />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={catForm.is_active} onCheckedChange={(v) => setCatForm({ ...catForm, is_active: v })} /> 启用（参与抽取）
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="ghost" onClick={() => setCatOpen(false)}>取消</Button>
          <Button onClick={saveCategory} disabled={catSaving} className="gap-1.5" data-testid="btn-cat-save">
            {catSaving && <Loader2 className="h-4 w-4 animate-spin" />} {catEdit ? '保存' : '创建'}
          </Button>
        </div>
      </Dialog>

      {/* 字段弹窗 */}
      <Dialog open={fieldOpen} onOpenChange={(o) => { if (!o) setFieldOpen(false) }} title={fieldEdit ? '编辑字段' : '新建字段'} className="max-w-xl">
        <div className="space-y-4">
          <label className="block text-xs font-medium text-muted-foreground">字段名称 *
            <Input value={fieldForm.name} onChange={(e) => setFieldForm({ ...fieldForm, name: e.target.value })} placeholder="如：项目名称" className="mt-1 h-10" data-testid="field-name-input" />
          </label>
          <label className="block text-xs font-medium text-muted-foreground">字段类型
            <Select value={fieldForm.type} onChange={(e) => setFieldForm({ ...fieldForm, type: e.target.value })} className="mt-1 h-10">
              {['string', 'number', 'boolean', 'array'].map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
          </label>
          <label className="block text-xs font-medium text-muted-foreground">字段说明（提升抽取精度）
            <textarea value={fieldForm.description} onChange={(e) => setFieldForm({ ...fieldForm, description: e.target.value })} rows={2} className="mt-1 min-h-[60px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-soft focus-visible:border-primary/50" />
          </label>
          <label className="block text-xs font-medium text-muted-foreground">示例（提升抽取精度）
            <Input value={fieldForm.example} onChange={(e) => setFieldForm({ ...fieldForm, example: e.target.value })} placeholder="如：抗拉强度 Rm" className="mt-1 h-10" />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={fieldForm.required} onCheckedChange={(v) => setFieldForm({ ...fieldForm, required: v })} /> 必填
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="ghost" onClick={() => setFieldOpen(false)}>取消</Button>
          <Button onClick={saveField} disabled={fieldSaving || !fieldForm.name.trim()} className="gap-1.5" data-testid="btn-field-save">
            {fieldSaving && <Loader2 className="h-4 w-4 animate-spin" />} {fieldEdit ? '保存' : '创建'}
          </Button>
        </div>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={confirmState !== null} onOpenChange={(o) => { if (!o) setConfirmState(null) }} title={confirmState?.title ?? '确认删除'}>
        <p className="text-sm text-muted-foreground">{confirmState?.description}</p>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="outline" onClick={() => setConfirmState(null)}>取消</Button>
          <Button variant="destructive" onClick={runConfirm} disabled={confirming} className="gap-1.5" data-testid="btn-confirm-delete">
            {confirming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} 删除
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
