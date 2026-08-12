import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Braces, ChevronRight, Loader2, Play, Save } from 'lucide-react'
import { extractionConfigApi, promptApi, type PromptTemplate, type SchemaCategory } from '@/api/modules/extractionConfig'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'
import { useKbDetail } from './KbDetailLayout'

const SYSTEM_PARAMS = [
  { label: 'feature（类别名）', placeholder: '${feature}' },
  { label: 'feature_descript（类别描述）', placeholder: '${feature_descript}' },
  { label: 'schema（当前类别 Schema）', placeholder: '${schema}' },
  { label: 'context（文档上下文）', placeholder: '${context}' },
  { label: 'return_type（返回类型）', placeholder: '${return_type}' },
  { label: 'prev_brands（前批牌号）', placeholder: '${prev_brands}' },
]

export default function KbPromptEditorPage() {
  const { promptId } = useParams<{ promptId: string }>()
  const { kb } = useKbDetail()
  const navigate = useNavigate()
  const { toast } = useToast()

  const [loading, setLoading] = useState(true)
  const [prompt, setPrompt] = useState<PromptTemplate | null>(null)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [userPrompt, setUserPrompt] = useState('')
  const [schemaCats, setSchemaCats] = useState<SchemaCategory[]>([])
  const [activeCatId, setActiveCatId] = useState<string>('')
  const [catPrompts, setCatPrompts] = useState<Record<string, string>>({})
  const [isActive, setIsActive] = useState(true)
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const [insertTarget, setInsertTarget] = useState<'system' | 'user'>('user')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const p = await promptApi.get(kb.id, promptId!)
      setPrompt(p)
      setIsActive(p.is_active)
      if (p.scope === 'simple') {
        setSystemPrompt(p.system_prompt)
        setUserPrompt(p.user_prompt)
      } else {
        setSystemPrompt(p.system_prompt)
        const byCat: Record<string, string> = {}
        for (const c of p.categories) byCat[c.category_id] = c.user_prompt
        setCatPrompts(byCat)
        if (p.schema_template_id) {
          const detail = await extractionConfigApi.getSchemaTemplate(kb.id, p.schema_template_id)
          setSchemaCats(detail.categories)
          if (detail.categories.length > 0) setActiveCatId(detail.categories[0].id)
        }
      }
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [kb.id, promptId, toast])

  useEffect(() => { void load() }, [load])

  const activeCat = useMemo(() => schemaCats.find((c) => c.id === activeCatId) ?? null, [schemaCats, activeCatId])
  const currentUserPrompt = useMemo(() => {
    if (prompt?.scope === 'simple') return userPrompt
    return catPrompts[activeCatId] ?? ''
  }, [prompt, userPrompt, catPrompts, activeCatId])

  function insertToken(token: string, into: 'system' | 'user') {
    const target = into === 'system' ? systemPrompt : (prompt?.scope === 'schema' ? catPrompts[activeCatId] ?? '' : userPrompt)
    const next = `${target}${token}`
    if (into === 'system') setSystemPrompt(next)
    else if (prompt?.scope === 'schema') setCatPrompts((m) => ({ ...m, [activeCatId]: next }))
    else setUserPrompt(next)
  }

  function renderPreview(): string {
    const text = insertTarget === 'system' ? systemPrompt : currentUserPrompt
    let out = text
    for (const f of activeCat?.fields ?? []) {
      out = out.replaceAll(`$${`{${f.name}}`}`, f.example || `[${f.name}]`)
    }
    for (const s of SYSTEM_PARAMS) {
      out = out.replaceAll(s.placeholder, `[${s.label}]`)
    }
    return out
  }

  async function save() {
    if (!prompt) return
    setSaving(true)
    try {
      if (prompt.scope === 'simple') {
        await promptApi.save(kb.id, prompt.id, { system_prompt: systemPrompt, user_prompt: userPrompt, is_active: isActive })
      } else {
        await promptApi.save(kb.id, prompt.id, {
          system_prompt: systemPrompt,
          categories: schemaCats.map((c) => ({ category_id: c.id, user_prompt: catPrompts[c.id] ?? '' })),
          is_active: isActive,
        })
      }
      toast('success', 'Prompt 已保存')
      navigate(`/kb/${kb.id}/extraction-config?tab=prompt`)
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="space-y-4"><Skeleton className="h-24 w-full rounded-2xl" /><Skeleton className="h-64 w-full rounded-2xl" /></div>
  if (!prompt) return <Card><CardContent className="py-16 text-center text-sm text-muted-foreground">Prompt 不存在</CardContent></Card>

  return (
    <div className="space-y-5">
      <PageHeader
        title={`编辑 Prompt · ${prompt.name}`}
        description={prompt.scope === 'schema' ? 'schema 模式：按类别拆分 user 提示词' : 'simple 模式：单个 user 提示词'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => navigate(`/kb/${kb.id}/extraction-config?tab=prompt`)} className="gap-1.5">
              <ArrowLeft className="h-4 w-4" /> 返回列表
            </Button>
            <Button onClick={save} disabled={saving} className="gap-1.5" data-testid="btn-prompt-editor-save">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存
            </Button>
          </div>
        }
      />

      {/* 插入目标切换 + 渲染预览 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-3">
          <span className="text-xs font-medium text-muted-foreground">插入到</span>
          <button
            type="button"
            onClick={() => setInsertTarget('system')}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${insertTarget === 'system' ? 'bg-primary-strong text-white' : 'bg-muted text-muted-foreground'}`}
          >System 提示词</button>
          <button
            type="button"
            onClick={() => setInsertTarget('user')}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${insertTarget === 'user' ? 'bg-primary-strong text-white' : 'bg-muted text-muted-foreground'}`}
          >User 提示词</button>
          <Button variant="outline" size="sm" onClick={() => setPreview(renderPreview())} className="ml-auto gap-1.5" data-testid="btn-prompt-preview">
            <Play className="h-3.5 w-3.5" /> 渲染预览
          </Button>
          <label className="flex items-center gap-1.5 text-xs"><Switch checked={isActive} onCheckedChange={setIsActive} /> 启用</label>
        </CardContent>
      </Card>

      {preview !== null && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">渲染预览（占位符替换，非 LLM 调用）</p>
              <Button variant="ghost" size="sm" onClick={() => setPreview(null)}>关闭</Button>
            </div>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-xs" data-testid="prompt-preview-content">{preview}</pre>
          </CardContent>
        </Card>
      )}

      {/* System 提示词 */}
      <Card>
        <CardContent className="space-y-2 p-4">
          <p className="text-sm font-medium">System 提示词</p>
          <textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} rows={5} className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-soft focus-visible:border-primary/50" data-testid="system-prompt-input" />
        </CardContent>
      </Card>

      {prompt.scope === 'simple' ? (
        <Card>
          <CardContent className="space-y-2 p-4">
            <p className="text-sm font-medium">User 提示词</p>
            <textarea value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} rows={8} className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-soft focus-visible:border-primary/50" data-testid="user-prompt-input" />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[220px_1fr_260px]">
          {/* 左：类别列表 */}
          <Card className="h-fit">
            <CardContent className="space-y-1 p-3">
              <p className="mb-2 text-xs font-medium text-muted-foreground">类别</p>
              {schemaCats.length === 0 ? (
                <p className="py-6 text-center text-xs text-muted-foreground">绑定模板暂无类别</p>
              ) : (
                schemaCats.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setActiveCatId(c.id)}
                    data-testid={`editor-cat-${c.id}`}
                    className={`flex w-full items-center gap-1.5 rounded-lg px-2 py-2 text-left text-sm transition-all ${activeCatId === c.id ? 'bg-secondary font-medium' : 'hover:bg-muted'}`}
                  >
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{c.name || '未命名类别'}</span>
                  </button>
                ))
              )}
            </CardContent>
          </Card>

          {/* 中：当前类别 user 提示词 */}
          <Card>
            <CardContent className="space-y-2 p-4">
              <p className="text-sm font-medium">User 提示词 · {activeCat?.name || '未命名类别'}</p>
              <textarea
                value={currentUserPrompt}
                onChange={(e) => setCatPrompts((m) => ({ ...m, [activeCatId]: e.target.value }))}
                rows={14}
                className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-soft focus-visible:border-primary/50"
                data-testid="schema-user-input"
              />
            </CardContent>
          </Card>

          {/* 右：字段与系统参数 */}
          <Card className="h-fit">
            <CardContent className="space-y-4 p-3">
              <div>
                <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-muted-foreground"><Braces className="h-3.5 w-3.5" /> 当前类别字段</p>
                <div className="max-h-48 space-y-1 overflow-y-auto">
                  {(activeCat?.fields ?? []).map((f) => (
                    <button key={f.id} type="button" onClick={() => insertToken(`$${`{${f.name}}`}`, insertTarget)} data-testid={`field-token-${f.name}`}
                      className="flex w-full items-center justify-between rounded-md border border-border/70 px-2 py-1.5 text-left text-xs hover:border-primary/40 hover:bg-muted/50">
                      <span className="font-mono">${'{'}{f.name}{'}'}</span>
                      <Badge variant="outline" className="text-[10px]">{f.type}</Badge>
                    </button>
                  ))}
                  {(activeCat?.fields ?? []).length === 0 && <p className="text-xs text-muted-foreground">暂无字段</p>}
                </div>
              </div>
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">系统参数</p>
                <div className="space-y-1">
                  {SYSTEM_PARAMS.map((s) => (
                    <button key={s.placeholder} type="button" onClick={() => insertToken(s.placeholder, 'system')} data-testid={`system-token-${s.placeholder.replace(/[${}]/g, '')}`}
                      className="block w-full truncate rounded-md border border-border/70 px-2 py-1.5 text-left font-mono text-[11px] hover:border-primary/40 hover:bg-muted/50">
                      {s.placeholder}
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
