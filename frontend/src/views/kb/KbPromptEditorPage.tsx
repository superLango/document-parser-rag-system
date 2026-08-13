import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, BookMarked, Braces, ChevronRight, FileText, Info, Loader2, Play, Save } from 'lucide-react'
import { extractionConfigApi, promptApi, type PromptTemplate } from '@/api/modules/extractionConfig'
import { glossaryApi } from '@/api/modules/glossary'
import type { TermBase, TermItem } from '@/api/types'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import TestPanel, { type PromptTestResult } from '@/components/kb/TestPanel'
import { useToast } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/auth'
import { useKbDetail } from './KbDetailLayout'

const SYSTEM_PARAMS = [
  { label: 'feature（类别名）', placeholder: '${feature}' },
  { label: 'feature_descript（类别描述）', placeholder: '${feature_descript}' },
  { label: 'schema（当前类别组装后的 Schema）', placeholder: '${schema}' },
  { label: 'context（文档上下文）', placeholder: '${context}' },
  { label: 'return_type（返回类型）', placeholder: '${return_type}' },
  { label: 'prev_brands（前批牌号）', placeholder: '${prev_brands}' },
]

interface EditorField { id: string; name: string; type: string; description: string; example: string | null; required: boolean }
interface TermRef { label: string; term_base_id: string; group_field: string; value_field: string }
interface EditorCategory {
  id: string
  name: string
  name_source?: string
  name_term_base_id?: string | null
  name_term_field?: string | null
  description: string
  return_type: string
  query_sources: TermRef[]
  user_prompt: string
  fields: EditorField[]
}

function manualTermValue(t: TermItem, field: string): unknown {
  const map: Record<string, unknown> = {
    term_name: t.term_name,
    standard_name: t.standard_name,
    english_term: t.english_term,
    definition: t.definition,
    category: t.category,
    synonyms: t.synonyms,
    aliases: t.aliases,
    standard_number: t.standard_number,
  }
  return map[field] ?? t.extras?.[field]
}

function readTermValue(t: TermItem, base: TermBase, field: string): unknown {
  const manual = base.source_type === 'manual' ? manualTermValue(t, field) : undefined
  if (manual != null) return manual
  return t.extras?.[field] ?? t.extras?.[field.toLowerCase()] ?? manualTermValue(t, field)
}

function extractFieldValues(rows: TermItem[], base: TermBase, field: string, filter?: { groupField: string; groupValue: string }): string[] {
  const values: string[] = []
  for (const t of rows) {
    if (filter) {
      const gv = readTermValue(t, base, filter.groupField)
      if (gv == null || String(gv) !== filter.groupValue) continue
    }
    const v = readTermValue(t, base, field)
    if (Array.isArray(v)) values.push(...v.map(String))
    else if (v != null && String(v).trim() !== '') values.push(String(v))
  }
  return [...new Set(values)]
}

export default function KbPromptEditorPage() {
  const { promptId } = useParams<{ promptId: string }>()
  const { kb } = useKbDetail()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'

  const [loading, setLoading] = useState(true)
  const [prompt, setPrompt] = useState<PromptTemplate | null>(null)
  const [isActive, setIsActive] = useState(true)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [simpleUserPrompt, setSimpleUserPrompt] = useState('')
  const [termBases, setTermBases] = useState<TermBase[]>([])
  const [categories, setCategories] = useState<EditorCategory[]>([])
  const [activeCatId, setActiveCatId] = useState('')
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<PromptTestResult | null>(null)
  const [testCatName, setTestCatName] = useState('')
  const cacheRef = useRef<Map<string, Map<string, string[]>>>(new Map())

  const scope = prompt?.scope ?? 'simple'
  const activeCat = useMemo(() => categories.find((c) => c.id === activeCatId) ?? null, [categories, activeCatId])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const p = await promptApi.get(kb.id, promptId!)
      setPrompt(p)
      setIsActive(p.is_active)
      setSystemPrompt(p.system_prompt || '')
      setSimpleUserPrompt(p.user_prompt || '')
      try {
        const tbRes = await glossaryApi.list(kb.id, { page_size: 50 })
        setTermBases(tbRes.items)
      } catch { setTermBases([]) }
      if (p.scope === 'schema' && p.schema_template_id) {
        const catMap = new Map(p.categories.map((c) => [c.category_id, c.user_prompt || '']))
        try {
          const tpl = await extractionConfigApi.getSchemaTemplate(kb.id, p.schema_template_id)
          const cats = (tpl.categories ?? []).map((c) => ({
            id: c.id,
            name: c.name,
            name_source: c.name_source,
            name_term_base_id: c.name_term_base_id,
            name_term_field: c.name_term_field,
            description: c.description || '',
            return_type: c.return_type || 'array',
            query_sources: (c.query_sources ?? []).map((q) => ({ ...q })),
            user_prompt: catMap.get(c.id) || '',
            fields: c.fields ?? [],
          }))
          setCategories(cats)
          if (cats.length > 0) setActiveCatId(cats[0].id)
        } catch {
          // 模板详情加载失败时降级为 prompt 返回的类别（无字段），对齐原项目
          const cats = (p.categories || []).map((c) => ({
            id: c.category_id,
            name: c.category_name || '',
            description: '',
            return_type: 'array',
            query_sources: [],
            user_prompt: c.user_prompt || '',
            fields: [],
          }))
          setCategories(cats)
          if (cats.length > 0) setActiveCatId(cats[0].id)
        }
      }
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [kb.id, promptId, toast])

  useEffect(() => { void load() }, [load])

  const activeTermRefs = useMemo(() => {
    const cat = activeCat
    if (!cat) return []
    const seen = new Set<string>()
    const refs: TermRef[] = []
    if (cat.name_source === 'term_base' && cat.name_term_base_id) {
      const tb = termBases.find((b) => b.id === cat.name_term_base_id)
      seen.add(cat.name_term_base_id)
      refs.push({ label: tb ? tb.name : '术语类别', term_base_id: cat.name_term_base_id, group_field: '', value_field: cat.name_term_field || '' })
    }
    for (const q of cat.query_sources || []) {
      if (!q.term_base_id || seen.has(q.term_base_id)) continue
      seen.add(q.term_base_id)
      const tb = termBases.find((b) => b.id === q.term_base_id)
      refs.push({ label: q.label || (tb ? tb.name : '术语集'), term_base_id: q.term_base_id, group_field: q.group_field, value_field: q.value_field })
    }
    return refs
  }, [activeCat, termBases])

  function insertInto(el: HTMLTextAreaElement | null, text: string, setter: (v: string) => void, current: string) {
    if (!el) { setter(current + text); return }
    const start = el.selectionStart ?? 0
    const end = el.selectionEnd ?? 0
    const next = current.slice(0, start) + text + current.slice(end)
    setter(next)
    requestAnimationFrame(() => {
      if (el) {
        el.focus()
        const pos = start + text.length
        el.setSelectionRange(pos, pos)
      }
    })
  }

  function insertPlaceholder(placeholder: string) {
    if (scope === 'simple') {
      const el = document.getElementById('user-prompt-simple') as HTMLTextAreaElement | null
      insertInto(el, placeholder, setSimpleUserPrompt, simpleUserPrompt)
      return
    }
    const cat = activeCat
    if (!cat) return
    const el = document.getElementById(`user-prompt-${cat.id}`) as HTMLTextAreaElement | null
    insertInto(el, placeholder, (v) => updateCatPrompt(cat.id, v), cat.user_prompt)
  }

  function updateCatPrompt(catId: string, v: string) {
    setCategories((prev) => prev.map((c) => (c.id === catId ? { ...c, user_prompt: v } : c)))
  }

  function buildSchemaPreview(cat: EditorCategory): string {
    const properties: Record<string, Record<string, unknown>> = {}
    for (const f of cat.fields) {
      const prop: Record<string, unknown> = { type: f.type }
      if (f.required) prop.required = true
      if (f.description) prop.description = f.description
      if (f.example) prop.example = f.example
      properties[f.name] = prop
    }
    return JSON.stringify({ type: cat.return_type || 'array', properties }, null, 2)
  }

  function buildTermRefMap(cat: EditorCategory | null): Map<string, { baseId: string; groupField?: string }> {
    const m = new Map<string, { baseId: string; groupField?: string }>()
    for (const b of termBases) m.set(b.name, { baseId: b.id })
    if (cat) {
      for (const qs of cat.query_sources) {
        if (qs.label) m.set(qs.label, { baseId: qs.term_base_id, groupField: qs.group_field || undefined })
      }
    }
    return m
  }

  async function loadAllTermBaseRows(baseId: string): Promise<TermItem[]> {
    const rows: TermItem[] = []
    let page = 1
    let total = -1
    while (total === -1 || rows.length < total) {
      const res = await glossaryApi.listTerms(kb.id, { term_base_id: baseId, page, page_size: 100 })
      rows.push(...(res.items ?? []))
      total = res.total ?? rows.length
      if (!res.items || res.items.length === 0) break
      page += 1
    }
    return rows
  }

  async function ensureFieldValue(baseId: string, base: TermBase, field: string, filter?: { groupField: string; groupValue: string }) {
    const cache = cacheRef.current
    if (!cache.has(baseId)) cache.set(baseId, new Map())
    const fieldCache = cache.get(baseId)!
    const keys = [field, field.toLowerCase()]
    if (keys.some((k) => fieldCache.has(k))) return
    const rows = await loadAllTermBaseRows(baseId)
    for (const k of keys) fieldCache.set(k, extractFieldValues(rows, base, k, filter))
  }

  async function termBaseFirstValue(cat: EditorCategory): Promise<string> {
    if (!cat || cat.name_source !== 'term_base' || !cat.name_term_base_id || !cat.name_term_field) return ''
    const base = termBases.find((b) => b.id === cat.name_term_base_id)
    if (!base) return ''
    await ensureFieldValue(cat.name_term_base_id, base, cat.name_term_field)
    const first = cacheRef.current.get(cat.name_term_base_id)?.get(cat.name_term_field) ?? cacheRef.current.get(cat.name_term_base_id)?.get(cat.name_term_field.toLowerCase())
    return first?.[0] || ''
  }

  async function ensureTermBaseValues(text: string, cat: EditorCategory | null, groupValue = '') {
    const refMap = buildTermRefMap(cat)
    const jobs: { base: TermBase; field: string; filter?: { groupField: string; groupValue: string } }[] = []
    const seen = new Set<string>()
    const re = /\$\{([^{}]+)\}/g
    let m: RegExpExecArray | null
    while ((m = re.exec(text))) {
      const key = String(m[1]).trim()
      if (!key.includes('.')) continue
      const [label, field] = key.split('.', 2)
      const ref = refMap.get(label)
      if (!ref) continue
      const base = termBases.find((b) => b.id === ref.baseId)
      if (!base) continue
      const jobKey = `${ref.baseId}:${field}:${ref.groupField || ''}:${groupValue}`
      if (seen.has(jobKey)) continue
      seen.add(jobKey)
      jobs.push({ base, field, filter: ref.groupField && groupValue ? { groupField: ref.groupField, groupValue } : undefined })
    }
    for (const job of jobs) {
      try { await ensureFieldValue(job.base.id, job.base, job.field, job.filter) } catch { /* 保留占位符 */ }
    }
  }

  function renderUserPrompt(text: string, cat: EditorCategory | null, groupValue = ''): string {
    if (!text) return text
    const fieldMap = new Map((cat?.fields || []).map((f) => [f.name, f]))
    const refMap = buildTermRefMap(cat)
    return text.replace(/\$\{([^{}]+)\}/g, (full, raw) => {
      const key = String(raw).trim()
      if (key.includes('.')) {
        const [fname, attr] = key.split('.', 2)
        const ref = refMap.get(fname)
        if (ref) {
          const fieldCache = cacheRef.current.get(ref.baseId)
          const values = fieldCache ? fieldCache.get(attr) || fieldCache.get(attr.toLowerCase()) : undefined
          if (values && values.length > 0) return `[${values.join(', ')}]`
          return full
        }
        const f = fieldMap.get(fname)
        if (f) {
          if (attr === '类型') return f.type
          if (attr === '必填') return f.required ? '是' : '否'
          if (attr === '描述') return f.description
          if (attr === '示例') return f.example || ''
          if (attr === '枚举' || attr === '术语集') return ''
        }
        return full
      }
      if (fieldMap.has(key)) return key
      if (key === 'feature') return cat ? groupValue || categoryDisplayName(cat) : ''
      if (key === 'feature_descript') return cat?.description || ''
      if (key === 'schema') return cat ? buildSchemaPreview(cat) : ''
      if (key === 'return_type') return cat?.return_type || 'array'
      return full
    })
  }

  function categoryDisplayName(cat: EditorCategory | null): string {
    if (!cat) return ''
    if (cat.name && cat.name.trim()) return cat.name
    if (cat.name_source === 'term_base') {
      const tb = termBases.find((b) => b.id === cat.name_term_base_id)
      return tb ? tb.name : '术语类别'
    }
    return cat.name || '未命名类别'
  }

  async function runTest() {
    const cat = scope === 'schema' ? activeCat : null
    const userText = scope === 'simple' ? simpleUserPrompt : cat?.user_prompt || ''
    const groupValue = scope === 'schema' && cat ? await termBaseFirstValue(cat) : ''
    await ensureTermBaseValues(userText, cat, groupValue)
    setTestCatName(scope === 'schema' && cat ? groupValue || categoryDisplayName(cat) : '')
    setTestResult({ system: systemPrompt, user: renderUserPrompt(userText, cat, groupValue) })
  }

  async function save() {
    if (!prompt) return
    setSaving(true)
    try {
      if (scope === 'simple') {
        await promptApi.save(kb.id, prompt.id, { system_prompt: systemPrompt, user_prompt: simpleUserPrompt, is_active: isActive })
      } else {
        await promptApi.save(kb.id, prompt.id, {
          system_prompt: systemPrompt,
          categories: categories.map((c) => ({ category_id: c.id, user_prompt: c.user_prompt })),
          is_active: isActive,
        })
      }
      toast('success', `Prompt 已保存，${prompt.name}`)
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="space-y-4 p-4 lg:p-6"><Skeleton className="h-24 w-full rounded-2xl" /><Skeleton className="h-64 w-full rounded-2xl" /></div>
  if (!prompt) return <Card><CardContent className="py-16 text-center text-sm text-muted-foreground">Prompt 不存在</CardContent></Card>

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={prompt.name || 'Prompt 模板'}
        description={prompt.description || '配置抽取提示词'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => navigate(`/kb/${kb.id}/extraction-config?tab=prompt`)} className="gap-1.5">
              <ArrowLeft className="h-4 w-4" /> 返回
            </Button>
            {canManage && (
              <Button onClick={save} disabled={saving} className="gap-1.5" data-testid="btn-prompt-editor-save">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存
              </Button>
            )}
          </div>
        }
      />

      {/* 顶部信息 */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-center gap-2">
            <Badge variant="outline">{scope === 'schema' ? 'Schema 模式' : '简单模式'}</Badge>
            <Badge variant={isActive ? 'default' : 'secondary'}>{isActive ? '启用' : '停用'}</Badge>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={isActive} onCheckedChange={setIsActive} disabled={!canManage} /> 启用
          </label>
        </CardContent>
      </Card>

      {/* System */}
      <Card>
        <CardContent className="space-y-2 p-4">
          <p className="flex items-center gap-2 text-sm font-medium">
            <BookMarked className="h-4 w-4 text-primary" /> System 系统提示词
          </p>
          <textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} rows={8} spellCheck={false} disabled={!canManage}
            className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-sm shadow-soft focus-visible:border-primary/50 disabled:opacity-60" data-testid="system-prompt-input" />
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5" /> System 提示词为全局角色设定，不使用 ${'{...}'} 占位符
          </p>
        </CardContent>
      </Card>

      {scope === 'simple' ? (
        <Card>
          <CardContent className="grid items-start gap-4 p-4 lg:grid-cols-2">
            <div className="space-y-3">
              <p className="flex items-center gap-2 text-sm font-medium">
                <FileText className="h-4 w-4 text-primary" /> User 提示词
              </p>
              <textarea id="user-prompt-simple" value={simpleUserPrompt} onChange={(e) => setSimpleUserPrompt(e.target.value)} rows={14} spellCheck={false} disabled={!canManage}
                className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-sm shadow-soft focus-visible:border-primary/50 disabled:opacity-60" data-testid="user-prompt-input" />
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <Info className="h-3.5 w-3.5" /> 可用占位符：${'{feature}'}、${'{feature_descript}'}、${'{schema}'}、${'{context}'}、${'{return_type}'}、${'{prev_brands}'}
              </p>
              <div className="flex justify-end">
                <Button variant="outline" size="sm" onClick={runTest} className="gap-1"><Play className="h-4 w-4" /> 测试组装</Button>
              </div>
            </div>
            <TestPanel result={testResult} catName={testCatName} />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-4">
            <p className="flex items-center gap-2 text-sm font-medium">
              <FileText className="h-4 w-4 text-primary" /> 按类别配置 User 提示词
            </p>
            {categories.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <FileText className="h-8 w-8 text-muted-foreground/50" />
                <p className="text-sm font-medium">暂无类别</p>
                <p className="text-xs text-muted-foreground">该 Schema 模板下没有选中类别</p>
              </div>
            ) : (
              <div className="mt-3 grid gap-4 lg:grid-cols-4">
                {/* 类别列表 */}
                <div className="space-y-1 rounded-lg border p-2">
                  <p className="px-1 pb-1 text-xs font-medium text-muted-foreground">类别</p>
                  {categories.map((cat) => (
                    <button key={cat.id} type="button" onClick={() => setActiveCatId(cat.id)} data-testid={`editor-cat-${cat.id}`}
                      className={`flex w-full items-center justify-between gap-1 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${activeCatId === cat.id ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-muted'}`}>
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-1">{categoryDisplayName(cat)}</span>
                        {cat.name_source === 'term_base' && <span className="block text-[10px] text-amber-600">使用术语库</span>}
                      </span>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-60" />
                    </button>
                  ))}
                </div>

                {/* 可用参数 */}
                <div className="rounded-lg border p-2">
                  <p className="flex items-center gap-1 px-1 pb-1 text-xs font-medium text-muted-foreground">
                    <Braces className="h-3.5 w-3.5" /> 可用参数
                  </p>
                  <div className="max-h-[520px] space-y-3 overflow-y-auto">
                    <div className="space-y-1">
                      <p className="px-1 text-[10px] font-medium text-muted-foreground">系统参数</p>
                      {SYSTEM_PARAMS.map((p) => (
                        <button key={p.placeholder} type="button" disabled={!canManage} onClick={() => insertPlaceholder(p.placeholder)} data-testid={`system-token-${p.placeholder.replace(/[${}]/g, '')}`}
                          className="flex w-full items-center justify-between gap-1 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-muted">
                          <span className="min-w-0 flex-1">
                            <span className="line-clamp-1 text-foreground">{p.label}</span>
                            <span className="block font-mono text-[10px] text-primary">{p.placeholder}</span>
                          </span>
                          <Badge variant="outline" className="shrink-0 text-[9px]">系统</Badge>
                        </button>
                      ))}
                    </div>
                    {activeCat && activeCat.fields.length > 0 && (
                      <div className="space-y-1">
                        <p className="px-1 text-[10px] font-medium text-muted-foreground">字段</p>
                        {activeCat.fields.map((f) => (
                          <button key={f.id} type="button" disabled={!canManage} onClick={() => insertPlaceholder(`$${'{' + f.name + '}'}`)} data-testid={`field-token-${f.name}`}
                            className="flex w-full items-center justify-between gap-1 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-muted">
                            <span className="line-clamp-1 font-mono text-primary">{'$' + '{' + f.name + '}'}</span>
                            <Badge variant="outline" className="shrink-0 text-[9px]">{f.type}</Badge>
                          </button>
                        ))}
                      </div>
                    )}
                    {activeTermRefs.length > 0 && (
                      <div className="space-y-1">
                        <p className="px-1 text-[10px] font-medium text-muted-foreground">术语集 / Query</p>
                        {activeTermRefs.map((ref) => (
                          <div key={ref.term_base_id} className="space-y-1 rounded-md bg-muted/40 p-1.5">
                            <button type="button" disabled={!canManage} onClick={() => insertPlaceholder(`$${'{' + ref.label + '}'}`)}
                              className="flex w-full items-center justify-between gap-1 rounded px-1.5 py-1 text-left text-xs transition-colors hover:bg-muted">
                              <span className="line-clamp-1 font-mono text-primary">{'$' + '{' + ref.label + '}'}</span>
                              <Badge variant="outline" className="shrink-0 text-[9px]">术语集</Badge>
                            </button>
                            {ref.value_field && (
                              <div className="flex flex-wrap gap-1 px-1">
                                {ref.group_field && (
                                  <button type="button" disabled={!canManage} onClick={() => insertPlaceholder(`$${'{' + ref.label + '.' + ref.group_field + '}'}`)}
                                    className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted disabled:opacity-60">{ref.group_field}</button>
                                )}
                                <button type="button" disabled={!canManage} onClick={() => insertPlaceholder(`$${'{' + ref.label + '.' + ref.value_field + '}'}`)}
                                  className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted disabled:opacity-60">{ref.value_field}</button>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* 当前类别 user 提示词 */}
                <div className="flex flex-col gap-2">
                  {activeCat && (
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{categoryDisplayName(activeCat)} - User 提示词</span>
                      <Badge variant="outline" className="text-[10px]">{activeCat.fields.length} 个字段</Badge>
                    </div>
                  )}
                  {activeCat && (
                    <textarea id={`user-prompt-${activeCat.id}`} value={activeCat.user_prompt} onChange={(e) => updateCatPrompt(activeCat.id, e.target.value)} rows={16} spellCheck={false} disabled={!canManage}
                      className="flex-1 rounded-md border border-input bg-card px-3 py-2 font-mono text-sm shadow-soft focus-visible:border-primary/50 disabled:opacity-60" data-testid="schema-user-input" />
                  )}
                  <div className="flex justify-end">
                    <Button variant="outline" size="sm" onClick={runTest} className="gap-1"><Play className="h-4 w-4" /> 测试组装</Button>
                  </div>
                </div>

                {/* 测试效果 */}
                <TestPanel result={testResult} catName={testCatName} />
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
