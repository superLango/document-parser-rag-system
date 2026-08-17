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
        className={`flex w-full items-center gap-2.5 border-b px-3 py-2.5 text-left transition-colors hover:bg-muted/40 ${props.tone}`}
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
      {props.open && <CardContent className="space-y-2 p-3">{props.children}</CardContent>}
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
    <div className="space-y-1 rounded-lg bg-muted/30 p-2">
      <label className="text-xs font-medium text-muted-foreground">{props.label}</label>
      <Input
        type={props.type ?? 'number'}
        value={props.value}
        disabled={props.disabled}
        step={props.step}
        min={props.min}
        onChange={(e) => props.onChange(props.type === 'text' ? e.target.value : Number(e.target.value))}
        className="mt-0.5 h-8"
        data-testid={props.testid}
      />
      {props.hint && <p className="text-[11px] leading-tight text-muted-foreground/80">{props.hint}</p>}
    </div>
  )
}

function ToggleField(props: { label: string; hint?: string; value: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 rounded-lg bg-muted/30 px-2.5 py-2 text-sm">
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
  const [open, setOpen] = useState<Record<string, boolean>>({ retrieval: false, llm: false, kb_tool: false })

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

  function patchEngine(engine: 'BaseExtract' | 'LangExtractPkg', key: string, value: unknown, sub?: string) {
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
    return <div className="space-y-2"><div className="h-24 animate-pulse rounded-xl bg-muted" /><div className="h-64 animate-pulse rounded-xl bg-muted" /></div>
  }
  if (!cfg) {
    return <p className="py-10 text-center text-sm text-muted-foreground">全局配置加载失败</p>
  }

  const eng = cfg.llm.engines[cfg.llm.engine]
  const toggle = (key: string) => setOpen((st) => ({ ...st, [key]: !st[key] }))
  const num = (v: unknown, fallback: number) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">结构化抽取全局参数，所有抽取任务默认使用以下参数；类别级配置可单独覆盖。</p>
        {canManage && (
          <Button size="sm" onClick={save} disabled={saving} className="gap-1.5" data-testid="btn-save-global">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存全局配置
          </Button>
        )}
      </div>

      <div className="flex items-center gap-2">
        <ToggleField label="启用全局配置" hint="关闭后全部回退内置默认参数（不会删除已保存的配置）；重新开启后恢复生效" value={enabled} disabled={!canManage} onChange={setEnabled} />
      </div>

      <SectionCard
        title="检索召回与上下文"
        subtitle="retrieval - 文档检索、类别召回与抽取上下文组装"
        icon={<Search className="h-4 w-4 text-primary" />}
        tone="bg-gradient-to-r from-primary/10 to-primary/5"
        open={open.retrieval}
        onToggle={() => toggle('retrieval')}
      >
        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="召回 top_k" hint="单类别最终召回的最大块数，决定送入 LLM 的上下文规模；值越大覆盖越全，但更耗 token 与时间" value={cfg.retrieval.top_k} disabled={!canManage} testid="global-retrieval-top-k" onChange={(v) => patch('retrieval', { top_k: num(v, 10) })} />
          <Field label="候选放大倍数" hint="检索每路先召回 top_k×倍数 个候选再做融合与截断；倍数过低可能漏掉相关块" value={cfg.retrieval.candidate_mult} disabled={!canManage} onChange={(v) => patch('retrieval', { candidate_mult: num(v, 2) })} />
          <Field label="默认置信度阈值" hint="类别命中的默认置信阈值（0~1）：低于该值的类别不进入抽取；Schema 类别可单独覆盖" type="number" step={0.05} min={0} value={cfg.retrieval.default_confidence_threshold} disabled={!canManage} onChange={(v) => patch('retrieval', { default_confidence_threshold: num(v, 0.35) })} />
          <Field label="标题路权重" hint="title 向量在稠密融合中的权重（0~1）；标题准确度高的文档可适当调高" type="number" step={0.05} min={0} value={cfg.retrieval.weights.title} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'weights', { ...cfg.retrieval.weights, title: num(v, 0.2) })} />
          <Field label="正文路权重" hint="content 向量在稠密融合中的权重（0~1）；正文语义为主，建议保持较高值" type="number" step={0.05} min={0} value={cfg.retrieval.weights.content} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'weights', { ...cfg.retrieval.weights, content: num(v, 0.8) })} />
          <Field label="上下文 top_k" hint="拼接抽取上下文的最大块数，超出部分按相关性截断；值越大上下文越全但越费 token" value={cfg.retrieval.context_top_k} disabled={!canManage} onChange={(v) => patch('retrieval', { context_top_k: num(v, 20) })} />
          <Field label="上下文最大 token" hint="拼接上下文的 token 上限，防止超出模型窗口导致请求失败" value={cfg.retrieval.context_max_tokens} disabled={!canManage} onChange={(v) => patch('retrieval', { context_max_tokens: num(v, 28000) })} />
          <Field label="字符/token 估算系数" hint="用字符数估算 token 的系数：中文约 1.5 字符/token；值越小估算出的 token 越多" type="number" step={0.1} min={0.1} value={cfg.retrieval.context.chars_per_token} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'context', { ...cfg.retrieval.context, chars_per_token: num(v, 1.5) })} />
          <Field label="上下文尾部最小保留字符" hint="按相关性截断时，上下文尾部至少保留的字符数，避免截断丢失关键信息" value={cfg.retrieval.context.min_keep_chars} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'context', { ...cfg.retrieval.context, min_keep_chars: num(v, 200) })} />
          <Field label="截断标记文本" hint="上下文截断处插入的占位标记，用于提示模型内容已被截断" type="text" value={cfg.retrieval.context.truncate_marker} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'context', { ...cfg.retrieval.context, truncate_marker: String(v) })} />
        </div>

        <div className="space-y-1.5 rounded-lg border border-primary/15 bg-primary/5 p-2">
          <p className="text-sm font-semibold text-primary-strong">类别召回</p>
          <div className="space-y-1 rounded-lg bg-muted/30 p-2 sm:col-span-2">
            <label className="text-xs font-medium text-muted-foreground">类别召回模式</label>
            <Select
              value={cfg.retrieval.category_recall.mode ?? 'loose'}
              disabled={!canManage}
              onChange={(e) => patchNested('retrieval', 'category_recall', { ...cfg.retrieval.category_recall, mode: e.target.value as 'loose' | 'strict' | 'off' })}
              className="mt-0.5 h-8"
              data-testid="global-category-recall-mode"
            >
              <option value="loose">宽松（零命中剔除，阈值仅记录）</option>
              <option value="strict">严格（命中分低于阈值且词法不足时剔除）</option>
              <option value="off">关闭（全部类别参与，不做召回过滤）</option>
            </Select>
            <p className="mt-0.5 text-[11px] leading-tight text-muted-foreground/80">9.5 演进：宽松为第一版行为；严格启用「置信度阈值 + 词法兜底（keyword_min_hits）」；关闭则所有类别进入抽取（零命中类别以空上下文参与）。</p>
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            <Field label="融合 top_k" hint="类别召回第一段检索的融合候选数：决定类别是否参与抽取（两段式召回，已生效）" value={cfg.retrieval.category_recall.top_k} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'category_recall', { ...cfg.retrieval.category_recall, top_k: num(v, 5) })} />
            <Field label="每维 top_k" hint="类别召回第一段检索时 dense/BM25 每路独立召回数（已生效）" value={cfg.retrieval.category_recall.per_dim_top_k} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'category_recall', { ...cfg.retrieval.category_recall, per_dim_top_k: num(v, 10) })} />
          </div>
        </div>

        <div className="space-y-1.5 rounded-lg border border-primary/15 bg-primary/5 p-2">
          <p className="text-sm font-semibold text-primary-strong">Query 编码与精简</p>
          <p className="text-[11px] leading-tight text-muted-foreground/80">
            精简开关与主/精简条目上限（dedupe / query_main_limit / query_refined_limit）在
            Schema 类别 → Query 术语集中按类别配置；此处仅设全局语义去重阈值与查询文本长度上限。
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="content 最大字符" hint="构造类别查询文本的最大字符数，超长截断后进入检索（已生效）" value={cfg.retrieval.query_embed.content_max_chars} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, content_max_chars: num(v, 2000) })} />
            <Field label="语义去重阈值" hint="精简查询的语义去重阈值（0~1）：Query 术语集开启 dedupe 后，词条余弦≥该值视为重复并合并，受 query_refined_limit 截断（已生效）" type="number" step={0.01} min={0} value={cfg.retrieval.query_embed.dedupe_similarity_threshold} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'query_embed', { ...cfg.retrieval.query_embed, dedupe_similarity_threshold: num(v, 0.85) })} />
          </div>
        </div>

        <div className="space-y-1.5 rounded-lg border border-emerald-200/50 bg-emerald-50/40 p-2 dark:bg-emerald-950/20">
          <p className="text-sm font-semibold text-emerald-700">混合检索（dense + BM25 · RRF）</p>
          <ToggleField label="启用混合检索" hint="开启后同时使用稠密（dense）与 BM25 词法两路召回并做 RRF 融合；关闭则仅用稠密路" value={cfg.retrieval.hybrid.enabled} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, enabled: v })} />
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="RRF 常数 rrf_k" hint="RRF 融合的平滑常数（rank 分母偏移），通常保持 60；越大融合越平滑、差距越小" value={cfg.retrieval.hybrid.rrf_k} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, rrf_k: num(v, 60) })} />
            <Field label="稠密权重" hint="稠密路结果在 RRF 融合中的权重；语义为主场景保持 1.0" type="number" step={0.1} min={0} value={cfg.retrieval.hybrid.dense_weight} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, dense_weight: num(v, 1) })} />
            <Field label="词法权重" hint="BM25 词法路在 RRF 融合中的权重；编号/型号/专有名词场景可适当调高" type="number" step={0.1} min={0} value={cfg.retrieval.hybrid.keyword_weight} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, keyword_weight: num(v, 1.2) })} />
            <Field label="词法兜底命中数" hint="词法命中达到该数即保留该类别（即使稠密分不足），用于强词法信号类别（如化学成分）" value={cfg.retrieval.hybrid.keyword_min_hits} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'hybrid', { ...cfg.retrieval.hybrid, keyword_min_hits: num(v, 1) })} />
          </div>
        </div>

        <div className="space-y-1.5 rounded-lg border border-warning/25 bg-warning/10 p-2">
          <p className="text-sm font-semibold text-warning">重排序（reranker · 预留）</p>
          <ToggleField label="启用重排序" hint="开启后对召回候选做 BGE-M3 语义精排（当前环境无独立重排模型，复用嵌入模型，已生效）；后续可替换为 bge-reranker" value={cfg.retrieval.reranker.enabled} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'reranker', { ...cfg.retrieval.reranker, enabled: v })} />
          <div className="grid gap-1.5 sm:grid-cols-2">
            <Field label="重排模型" hint="重排模型路径或标识（当前语义精排固定使用 BGE-M3，该字段为标识记录）" type="text" value={cfg.retrieval.reranker.model} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'reranker', { ...cfg.retrieval.reranker, model: String(v) })} />
            <Field label="重排后 top_n" hint="重排后保留并送入抽取的块数；开启重排后生效（预留）" value={cfg.retrieval.reranker.top_n} disabled={!canManage} onChange={(v) => patchNested('retrieval', 'reranker', { ...cfg.retrieval.reranker, top_n: num(v, 15) })} />
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="LLM 抽取参数"
        subtitle="llm - 大语言模型抽取引擎与调用参数"
        icon={<Cpu className="h-4 w-4 text-primary-strong" />}
        tone="bg-gradient-to-r from-primary-strong/10 to-primary-strong/5"
        open={open.llm}
        onToggle={() => toggle('llm')}
      >
        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1 rounded-lg bg-muted/30 p-2">
            <label className="text-xs font-medium text-muted-foreground">抽取引擎</label>
            <Select
              value={cfg.llm.engine}
              disabled={!canManage}
              onChange={(e) => patch('llm', { engine: e.target.value as 'BaseExtract' | 'LangExtractPkg' })}
              className="mt-0.5 h-8"
              data-testid="global-llm-engine"
            >
              <option value="BaseExtract">BaseExtract（直抽）</option>
              <option value="LangExtractPkg">LangExtractPkg（原包·XGrammar 强约束）</option>
            </Select>
            <p className="mt-0.5 text-[11px] leading-tight text-muted-foreground/80">BaseExtract 直抽快；LangExtractPkg 原包多轮+示例+XGrammar 约束，更稳但更慢。切换后下方参数自动联动。</p>
          </div>
          <Field label="温度 temperature" hint="LLM 采样温度：越低越确定、越贴近事实；结构化抽取建议保持 0" type="number" step={0.1} min={0} value={eng.temperature} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'temperature', num(v, 0))} />
          <Field label="top_p" hint="核采样概率，与 top_k 共同控制生成多样性；结构化抽取建议 0.1" type="number" step={0.01} min={0} value={eng.top_p} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'top_p', num(v, 0.1))} />
          <Field label="top_k" hint="生成时保留的候选 token 数；越大多样性越高" value={eng.top_k} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'top_k', num(v, 20))} />
          <Field label="max_tokens" hint="单次 LLM 生成的最大 token 数；Schema 类别可单独覆盖" value={eng.max_tokens} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'max_tokens', num(v, 32768))} />
          <Field label="超时 timeout（秒）" hint="单次 LLM 请求超时（秒），超时按任务失败/重试策略处理；过小会导致长文档抽取中断" value={eng.timeout} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'timeout', num(v, 300))} />
        </div>
        <ToggleField label="启用思考 enable_thinking" hint="关闭以适配 vLLM 结构化输出（thinking 模式可能与 XGrammar 冲突）；推理场景可开启" value={eng.enable_thinking} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'enable_thinking', v)} />

        <div className="space-y-1.5 rounded-lg border border-primary/15 bg-primary/5 p-2">
          <p className="text-sm font-semibold text-primary-strong">并发配置（{cfg.llm.engine}）</p>
          <div className="grid gap-1.5 sm:grid-cols-3">
            <Field label="总并发上限" hint="LLM 调用总并发上限，建议与 vLLM 的 --max-num-seqs 一致，避免排队或超限" value={eng.concurrency.max_concurrency} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'concurrency', { ...eng.concurrency, max_concurrency: num(v, 24) })} />
            <Field label="类别间并发" hint="同时调度处理的类别数量；BaseExtract 建议等于总并发以填满队列" value={eng.concurrency.cross_category} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'concurrency', { ...eng.concurrency, cross_category: num(v, 24) })} />
            <Field label="类别内并发" hint="单个类别内的并发数；BaseExtract 建议 1（类别内串行），LangExtractPkg 可适当提高" value={eng.concurrency.within_category} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'concurrency', { ...eng.concurrency, within_category: num(v, 1) })} />
          </div>
        </div>

        {cfg.llm.engine === 'BaseExtract' ? (
          <div className="space-y-1.5 rounded-lg border border-primary/15 bg-primary/5 p-2">
            <p className="text-sm font-semibold text-primary-strong">批处理参数（BaseExtract）</p>
            <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="长文本阈值" hint="上下文字符数超过该值即触发分批；过小会频繁分批、过大易超模型窗口" value={eng.batch.single_threshold} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, single_threshold: num(v, 8000) })} />
              <Field label="单批字符" hint="每批最大字符数，优先按表格边界切分；避免表格被拆断" value={eng.batch.batch_chars} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, batch_chars: num(v, 6000) })} />
              <Field label="批间重叠" hint="相邻批次间保留的重叠字符，避免上下文割裂；表格密集文档建议 ≥500" value={eng.batch.overlap} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, overlap: num(v, 500) })} />
              <Field label="上下文截断" hint="单次送入 LLM 的最大字符数，防止超出模型上下文" value={eng.batch.context_truncate} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'batch', { ...eng.batch, context_truncate: num(v, 32000) })} />
            </div>
          </div>
        ) : (
          <div className="space-y-1.5 rounded-lg border border-primary/15 bg-primary/5 p-2">
            <p className="text-sm font-semibold text-primary-strong">引擎专属参数（LangExtractPkg）</p>
            <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="抽取轮数 passes" hint="LangExtractPkg 的抽取迭代轮数：多轮可提升召回但更耗时，建议 1~2" value={num(eng.passes, 2)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'passes', num(v, 2))} />
              <Field label="共指消解窗口(字符)" hint="跨块共指消解的窗口字符数，窗口越大跨块关联越准但更耗时" value={num(eng.context_window_chars, 28000)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'context_window_chars', num(v, 28000))} />
              <Field label="单次输入字符上限" hint="LangExtractPkg 单次送入 LLM 的最大字符数，防止超模型窗口" value={num(eng.max_char_buffer, 40000)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'max_char_buffer', num(v, 40000))} />
              <Field label="few-shot 示例数" hint="从 Schema 字段 example 生成的示例条数；示例越多抽取越稳但更耗 token" value={num(eng.max_examples, 3)} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'max_examples', num(v, 3))} />
              <div className="space-y-1 rounded-lg bg-muted/30 p-2">
                <label className="text-xs font-medium text-muted-foreground">输出格式 format_type</label>
                <Select
                  value={eng.format_type ?? 'JSON'}
                  disabled={!canManage}
                  onChange={(e) => patchEngine(cfg.llm.engine, 'format_type', e.target.value)}
                  className="mt-0.5 h-8"
                >
                  <option value="JSON">JSON</option>
                  <option value="YAML">YAML</option>
                </Select>
                <p className="mt-0.5 text-[11px] leading-tight text-muted-foreground/80">结构化输出格式，仅 LangExtractPkg 生效。</p>
              </div>
              <ToggleField label="围栏输出 fence_output" hint="在输出外层包裹围栏标记；对接特定解析器时可能需要开启（仅 LangExtractPkg 生效）" value={eng.fence_output ?? false} disabled={!canManage} onChange={(v) => patchEngine(cfg.llm.engine, 'fence_output', v)} />
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="脚本工具 kb_tool"
        subtitle="kb_tool - 脚本可调用工具的性能与安全参数"
        icon={<Wand2 className="h-4 w-4 text-emerald-600" />}
        tone="bg-gradient-to-r from-emerald-500/10 to-emerald-500/5"
        open={open.kb_tool}
        onToggle={() => toggle('kb_tool')}
      >
        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="embed 分批次大小" hint="脚本调用 embed 时的分批大小：越大吞吐越高，但显存/内存占用越大" value={cfg.kb_tool.embed_batch_size} disabled={!canManage} onChange={(v) => patch('kb_tool', { embed_batch_size: num(v, 16) })} />
          <Field label="检索/匹配并发上限" hint="脚本中语义检索/匹配共享的信号量上限，防止脚本并发打满检索服务" value={cfg.kb_tool.search_concurrency} disabled={!canManage} onChange={(v) => patch('kb_tool', { search_concurrency: num(v, 10) })} />
          <Field label="semantic_search 默认 top_k" hint="脚本调用 semantic_search 未传 top_k 时的默认返回条数" value={cfg.kb_tool.semantic_top_k} disabled={!canManage} onChange={(v) => patch('kb_tool', { semantic_top_k: num(v, 5) })} />
          <Field label="match_record 内部检索 top_k" hint="脚本 match_record 内部检索的候选条数，候选越多匹配越准但越慢" value={cfg.kb_tool.match_top_k} disabled={!canManage} onChange={(v) => patch('kb_tool', { match_top_k: num(v, 1) })} />
          <Field label="match_record 匹配阈值" hint="脚本 match_record 判定命中的相似度阈值（0~1），低于该值不返回命中" type="number" step={0.01} min={0} value={cfg.kb_tool.match_threshold} disabled={!canManage} onChange={(v) => patch('kb_tool', { match_threshold: num(v, 0.9) })} />
          <Field label="脚本执行超时（秒）" hint="post/validation 脚本单次执行上限：防止脚本卡死阻塞抽取任务" value={cfg.kb_tool.script_timeout} disabled={!canManage} testid="global-script-timeout" onChange={(v) => patch('kb_tool', { script_timeout: num(v, 10) })} />
          <Field label="脚本输出上限（字节）" hint="脚本 stdout/stderr 截断上限：防止脚本输出爆炸占用资源" value={cfg.kb_tool.script_max_output_bytes} disabled={!canManage} onChange={(v) => patch('kb_tool', { script_max_output_bytes: num(v, 1024 * 1024) })} />
          <Field label="注入术语集最大行数" hint="注入脚本的每个术语集词条行数上限，防止上下文过大拖慢脚本" value={cfg.kb_tool.script_max_term_rows} disabled={!canManage} onChange={(v) => patch('kb_tool', { script_max_term_rows: num(v, 1000) })} />
        </div>
      </SectionCard>
    </div>
  )
}
