import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Cpu, Loader2, Save, Search, Wand2 } from 'lucide-react'
import { globalConfigApi, type GlobalConfigContent, type GlobalEngineConfig } from '@/api/modules/extractionConfig'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'

interface Props {
  kbId: string
  canManage: boolean
}

function SectionCard(props: {
  title: string
  subtitle: string
  icon: ReactNode
  tone: string
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={props.onToggle}
        className={`flex w-full items-center gap-3 border-b px-5 py-3.5 text-left transition-colors hover:bg-muted/40 ${props.tone}`}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-background/70 shadow-sm">
          {props.icon}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">{props.title}</p>
          <p className="truncate text-xs text-muted-foreground">{props.subtitle}</p>
        </div>
        {props.open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
      </button>
      {props.open && <CardContent className="space-y-5 p-5">{props.children}</CardContent>}
    </Card>
  )
}

function Field(props: {
  label: string
  hint?: string
  type?: 'number' | 'text'
  value: number | string
  disabled?: boolean
  step?: number | string
  min?: number
  testid?: string
  onChange: (v: number | string) => void
}) {
  return (
    <div className="space-y-1.5 rounded-lg bg-muted/30 p-3">
      <label className="text-xs font-medium text-muted-foreground">{props.label}</label>
      <Input
        type={props.type ?? 'number'}
        value={props.value}
        disabled={props.disabled}
        step={props.step}
        min={props.min}
        onChange={(e) => props.onChange(props.type === 'text' ? e.target.value : Number(e.target.value))}
        className="mt-1 h-9"
        data-testid={props.testid}
      />
      {props.hint && <p className="text-[11px] leading-tight text-muted-foreground/80">{props.hint}</p>}
    </div>
  )
}

function ToggleField(props: { label: string; hint?: string; value: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg bg-muted/30 px-3 py-3 text-sm">
      <span>
        <span className="font-medium text-foreground">{props.label}</span>
        {props.hint && <span className="block text-[11px] leading-tight text-muted-foreground/80">{props.hint}</span>}
      </span>
      <Switch checked={props.value} disabled={props.disabled} onCheckedChange={props.onChange} />
    </label>
  )
}

export default function KbGlobalConfig({ kbId, canManage }: Props) {
  const { toast } = useToast()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [cfg, setCfg] = useState<GlobalConfigContent | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({ retrieval: true, llm: false, kb_tool: true })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await globalConfigApi.get(kbId)
      setEnabled(res.enabled)
      setCfg(res.content)
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [kbId, toast])

  useEffect(() => { void load() }, [load])

  function patch<K extends keyof GlobalConfigContent>(block: K, patchData: Partial<GlobalConfigContent[K]>) {
    setCfg((prev) => (prev ? { ...prev, [block]: { ...prev[block], ...patchData } } : prev))
  }

  function patchNested<K extends keyof GlobalConfigContent>(
    block: K,
    key: string,
    value: unknown,
    sub?: string,
  ) {
    setCfg((prev) => {
      if (!prev) return prev
      const blockObj = prev[block] as unknown as Record<string, unknown>
      const target = sub ? (blockObj[key] as Record<string, unknown> ?? {}) : blockObj
      if (sub) {
        return { ...prev, [block]: { ...blockObj, [key]: { ...target, [sub]: value } } }
      }
      return { ...prev, [block]: { ...blockObj, [key]: value } }
    })
  }

  function patchEngine(engine: 'BaseExtract' | 'LangExtract', key: string, value: unknown, sub?: string) {
    setCfg((prev) => {
      if (!prev) return prev
      const eng = prev.llm.engines[engine] as GlobalEngineConfig & Record<string, unknown>
      if (sub) {
        const subObj = (eng[key] as Record<string, unknown>) ?? {}
        return {
          ...prev,
          llm: { ...prev.llm, engines: { ...prev.llm.engines, [engine]: { ...eng, [key]: { ...subObj, [sub]: value } } } },
        }
      }
      return {
        ...prev,
        llm: { ...prev.llm, engines: { ...prev.llm.engines, [engine]: { ...eng, [key]: value } } },
      }
    })
  }

  async function save() {
    if (!cfg) return
    setSaving(true)
    try {
      const res = await globalConfigApi.save(kbId, { enabled, content: cfg })
      setEnabled(res.enabled)
      setCfg(res.content)
      toast('success', '全局配置已保存')
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="space-y-3"><div className="h-24 animate-pulse rounded-xl bg-muted" /><div className="h-64 animate-pulse rounded-xl bg-muted" /></div>
  }
  if (!cfg) {
    return <p className="py-10 text-center text-sm text-muted-foreground">全局配置加载失败</p>
  }

  const eng = cfg.llm.engines[cfg.llm.engine]
  const toggle = (key: string) => setOpen((st) => ({ ...st, [key]: !st[key] }))
  const num = (v: unknown, fallback: number) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">结构化抽取全局参数，所有抽取任务默认使用以下参数；类别级配置可单独覆盖。</p>
        {canManage && (
          <Button size="sm" onClick={save} disabled={saving} className="gap-1.5" data-testid="btn-save-global">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存全局配置
          </Button>
        )}
      </div>

      <div className="flex items-center gap-2">
        <ToggleField label="启用全局配置" hint="关闭后使用内置默认参数" value={enabled} disabled={!canManage} onChange={setEnabled} />
      </div>

      <SectionCard
        title="检索召回与上下文"
        subtitle="retrieval - 文档检索、类别召回与抽取上下文组装"
        icon={<Search className="h-4 w-4 text-blue-500" />}
        tone="bg-gradient-to-r from-blue-500/10 to-blue-500/5"
        open={open.retrieval}
        onToggle={() => toggle('retrieval')}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="召回 top_k" hint="单类别最终召回的最大块数" value={cfg.retrieval.top_k} disabled={!canManage} testid="global-retrieval-top-k" onChange={(v) => patch('retrieval', { top_k: num(v, 10) })} />
          <Field label="候选放大倍数" hint="每路召回候选数 = top_k × 倍数" value={cfg.retrieval.candidate_mult} disabled={!canManage} onChange={(v) => patch('retrieval', { candidate_mult: num(v, 2) })} />
          <Field label="默认置信度阈值" hint="类别命中判定阈值，类别级可覆盖" type="number" step={0.05} min={0} value={cfg.retrieval.default_confidence_threshold} disabled={!canManage} onChange={(v) => patch('retrieval', { default_confidence_threshold: num(v, 0.35) })} />
          <Field label="标题路权重" hint="title 向量融合权重" type="number" step={0.05} min={0} value={cfg.retrieval.weights.title} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'weights', { ...cfg.retrieval.weights, title: num(v, 0.2) })} />
          <Field label="正文路权重" hint="content 向量融合权重" type="number" step={0.05} min={0} value={cfg.retrieval.weights.content} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'weights', { ...cfg.retrieval.weights, content: num(v, 0.8) })} />
          <Field label="上下文 top_k" hint="抽取上下文按块数截断上限" value={cfg.retrieval.context_top_k} disabled={!canManage} onChange={(v) => patch('retrieval', { context_top_k: num(v, 20) })} />
          <Field label="上下文最大 token" value={cfg.retrieval.context_max_tokens} disabled={!canManage} onChange={(v) => patch('retrieval', { context_max_tokens: num(v, 28000) })} />
          <Field label="字符/token 估算系数" type="number" step={0.1} min={0.1} value={cfg.retrieval.context.chars_per_token} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'context', { ...cfg.retrieval.context, chars_per_token: num(v, 1.5) })} />
          <Field label="上下文尾部最小保留字符" value={cfg.retrieval.context.min_keep_chars} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'context', { ...cfg.retrieval.context, min_keep_chars: num(v, 200) })} />
          <Field label="截断标记文本" type="text" value={cfg.retrieval.context.truncate_marker} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'context', { ...cfg.retrieval.context, truncate_marker: String(v) })} />
        </div>

        <div className="space-y-3 rounded-xl border border-blue-200/50 bg-blue-50/40 p-4 dark:bg-blue-950/20">
          <p className="text-sm font-semibold text-blue-700">Phase 2 类别召回</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="融合 top_k" value={cfg.retrieval.phase2.top_k} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'phase2', { ...cfg.retrieval.phase2, top_k: num(v, 5) })} />
            <Field label="每维 top_k" value={cfg.retrieval.phase2.per_dim_top_k} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'phase2', { ...cfg.retrieval.phase2, per_dim_top_k: num(v, 10) })} />
          </div>
        </div>

        <div className="space-y-3 rounded-xl border border-blue-200/50 bg-blue-50/40 p-4 dark:bg-blue-950/20">
          <p className="text-sm font-semibold text-blue-700">五维 Query 编码</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="content 最大字符" value={cfg.retrieval.query_embed.content_max_chars} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, content_max_chars: num(v, 2000) })} />
            <Field label="feature 重复次数" value={cfg.retrieval.query_embed.feature_repeat} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, feature_repeat: num(v, 2) })} />
            <Field label="嵌入 max_length" value={cfg.retrieval.query_embed.embed_max_length} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, embed_max_length: num(v, 2048) })} />
            <Field label="type 维固定查询文本" type="text" value={cfg.retrieval.query_embed.type_query} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, type_query: String(v) })} />
            <Field label="语义去重阈值" type="number" step={0.01} min={0} value={cfg.retrieval.query_embed.dedupe_similarity_threshold} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, dedupe_similarity_threshold: num(v, 0.85) })} />
          </div>
        </div>

        <div className="space-y-3 rounded-xl border border-cyan-200/50 bg-cyan-50/40 p-4 dark:bg-cyan-950/20">
          <p className="text-sm font-semibold text-cyan-700">混合检索（dense + BM25 · RRF）</p>
          <ToggleField label="启用混合检索" value={cfg.retrieval.hybrid.enabled} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, enabled: v })} />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="RRF 常数 rrf_k" value={cfg.retrieval.hybrid.rrf_k} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, rrf_k: num(v, 60) })} />
            <Field label="稠密权重" type="number" step={0.1} min={0} value={cfg.retrieval.hybrid.dense_weight} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, dense_weight: num(v, 1) })} />
            <Field label="词法权重" type="number" step={0.1} min={0} value={cfg.retrieval.hybrid.keyword_weight} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, keyword_weight: num(v, 1.2) })} />
            <Field label="词法兜底命中数" value={cfg.retrieval.hybrid.keyword_min_hits} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, keyword_min_hits: num(v, 1) })} />
          </div>
        </div>

        <div className="space-y-3 rounded-xl border border-violet-200/50 bg-violet-50/40 p-4 dark:bg-violet-950/20">
          <p className="text-sm font-semibold text-violet-700">重排序（reranker · 预留）</p>
          <ToggleField label="启用重排序" hint="当前仅预留接口，接入重排模型后生效" value={cfg.retrieval.reranker.enabled} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'reranker', { ...cfg.retrieval.reranker, enabled: v })} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="重排模型" type="text" value={cfg.retrieval.reranker.model} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'reranker', { ...cfg.retrieval.reranker, model: String(v) })} />
            <Field label="重排后 top_n" value={cfg.retrieval.reranker.top_n} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'reranker', { ...cfg.retrieval.reranker, top_n: num(v, 15) })} />
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="LLM 抽取参数"
        subtitle="llm - 大语言模型抽取引擎与调用参数"
        icon={<Cpu className="h-4 w-4 text-purple-500" />}
        tone="bg-gradient-to-r from-purple-500/10 to-purple-500/5"
        open={open.llm}
        onToggle={() => toggle('llm')}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1.5 rounded-lg bg-muted/30 p-3">
            <label className="text-xs font-medium text-muted-foreground">抽取引擎</label>
            <Select
              value={cfg.llm.engine}
              disabled={!canManage}
              onChange={(e) => patch('llm', { engine: e.target.value as 'BaseExtract' | 'LangExtract' })}
              className="mt-1 h-9"
              data-testid="global-llm-engine"
            >
              <option value="BaseExtract">BaseExtract（直抽）</option>
              <option value="LangExtract">LangExtract（结构化强约束）</option>
            </Select>
          </div>
          <Field label="温度 temperature" type="number" step={0.1} min={0} value={eng.temperature} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'temperature', num(v, 0))} />
          <Field label="top_p" type="number" step={0.01} min={0} value={eng.top_p} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'top_p', num(v, 0.1))} />
          <Field label="top_k" value={eng.top_k} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'top_k', num(v, 20))} />
          <Field label="max_tokens" value={eng.max_tokens} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'max_tokens', num(v, 32768))} />
          <Field label="超时 timeout（秒）" value={eng.timeout} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'timeout', num(v, 300))} />
        </div>
        <ToggleField label="启用思考 enable_thinking" hint="关闭以适配 vLLM 结构化输出" value={eng.enable_thinking} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'enable_thinking', v)} />

        <div className="space-y-3 rounded-xl border border-purple-200/50 bg-purple-50/40 p-4 dark:bg-purple-950/20">
          <p className="text-sm font-semibold text-purple-700">并发配置（{cfg.llm.engine}）</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="总并发上限" value={eng.concurrency.max_concurrency} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'concurrency', { ...eng.concurrency, max_concurrency: num(v, 24) })} />
            <Field label="类别间并发" value={eng.concurrency.cross_category} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'concurrency', { ...eng.concurrency, cross_category: num(v, 24) })} />
            <Field label="类别内并发" value={eng.concurrency.within_category} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'concurrency', { ...eng.concurrency, within_category: num(v, 1) })} />
          </div>
        </div>

        {cfg.llm.engine === 'BaseExtract' ? (
          <div className="space-y-3 rounded-xl border border-purple-200/50 bg-purple-50/40 p-4 dark:bg-purple-950/20">
            <p className="text-sm font-semibold text-purple-700">批处理参数（BaseExtract）</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="长文本阈值" value={eng.batch.single_threshold} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, single_threshold: num(v, 8000) })} />
              <Field label="单批字符" value={eng.batch.batch_chars} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, batch_chars: num(v, 6000) })} />
              <Field label="批间重叠" value={eng.batch.overlap} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, overlap: num(v, 500) })} />
              <Field label="上下文截断" value={eng.batch.context_truncate} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, context_truncate: num(v, 32000) })} />
            </div>
          </div>
        ) : (
          <div className="space-y-3 rounded-xl border border-purple-200/50 bg-purple-50/40 p-4 dark:bg-purple-950/20">
            <p className="text-sm font-semibold text-purple-700">引擎专属参数（LangExtract）</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="抽取轮数 passes" value={num(eng.passes, 2)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'passes', num(v, 2))} />
              <Field label="共指消解窗口(字符)" value={num(eng.context_window_chars, 28000)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'context_window_chars', num(v, 28000))} />
              <Field label="单次输入字符上限" value={num(eng.max_char_buffer, 40000)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'max_char_buffer', num(v, 40000))} />
              <Field label="few-shot 示例数" value={num(eng.max_examples, 3)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'max_examples', num(v, 3))} />
              <div className="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <label className="text-xs font-medium text-muted-foreground">输出格式 format_type</label>
                <Select
                  value={eng.format_type ?? 'JSON'}
                  disabled={!canManage}
                  onChange={(e) => patchEngine(cfg.llm.engine, 'format_type', e.target.value)}
                  className="mt-1 h-9"
                >
                  <option value="JSON">JSON</option>
                  <option value="YAML">YAML</option>
                </Select>
              </div>
              <ToggleField label="围栏输出 fence_output" value={eng.fence_output ?? false} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'fence_output', v)} />
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="脚本工具 kb_tool"
        subtitle="kb_tool - 脚本可调用工具的性能与安全参数"
        icon={<Wand2 className="h-4 w-4 text-emerald-500" />}
        tone="bg-gradient-to-r from-emerald-500/10 to-emerald-500/5"
        open={open.kb_tool}
        onToggle={() => toggle('kb_tool')}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="embed 分批次大小" value={cfg.kb_tool.embed_batch_size} disabled={!canManage} onChange={(v) => patch('kb_tool', { embed_batch_size: num(v, 16) })} />
          <Field label="检索/匹配并发上限" value={cfg.kb_tool.search_concurrency} disabled={!canManage} onChange={(v) => patch('kb_tool', { search_concurrency: num(v, 10) })} />
          <Field label="semantic_search 默认 top_k" value={cfg.kb_tool.semantic_top_k} disabled={!canManage} onChange={(v) => patch('kb_tool', { semantic_top_k: num(v, 5) })} />
          <Field label="match_record 内部检索 top_k" value={cfg.kb_tool.match_top_k} disabled={!canManage} onChange={(v) => patch('kb_tool', { match_top_k: num(v, 1) })} />
          <Field label="match_record 匹配阈值" type="number" step={0.01} min={0} value={cfg.kb_tool.match_threshold} disabled={!canManage} onChange={(v) => patch('kb_tool', { match_threshold: num(v, 0.9) })} />
          <Field label="脚本执行超时（秒）" hint="post/validation 脚本单次执行上限" value={cfg.kb_tool.script_timeout} disabled={!canManage} testid="global-script-timeout" onChange={(v) => patch('kb_tool', { script_timeout: num(v, 10) })} />
          <Field label="脚本输出上限（字节）" value={cfg.kb_tool.script_max_output_bytes} disabled={!canManage} onChange={(v) => patch('kb_tool', { script_max_output_bytes: num(v, 1024 * 1024) })} />
          <Field label="注入术语集最大行数" value={cfg.kb_tool.script_max_term_rows} disabled={!canManage} onChange={(v) => patch('kb_tool', { script_max_term_rows: num(v, 1000) })} />
        </div>
      </SectionCard>
    </div>
  )
}
