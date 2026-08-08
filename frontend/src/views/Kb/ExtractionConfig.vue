<script setup lang="ts">
/**
 * 知识库抽取配置中心
 *
 * 功能：抽取策略的页面配置化（零代码/低代码）
 * 页签：全局配置 / Schema 模板 / Prompt 模板 / 抽取规则 / 验证规则 / 版本管理
 *
 * 数据隔离：/kbs/{kb_id}/extraction-config，后端 RLS 强制
 * 权限：viewer 可查看；editor+ 可管理
 *
 * 命名规范：全局配置区块使用 retrieval / llm，不使用 phase 前缀；
 * 类别级 top_k / confidence_threshold 通过 Schema 模板类别节点设置。
 */
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Settings2,
  LayoutTemplate,
  FileText,
  ListChecks,
  ShieldCheck,
  History,
  GitCompareArrows,
  Plus,
  RefreshCw,
  Loader2,
  Trash2,
  Pencil,
  Save,
  FolderTree,
  FileBox,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Database,
  BookMarked,
  Search,
  Cpu,
  Wand2,
  Code2,
} from 'lucide-vue-next'
import { kbApi, type TermBase } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Select } from '@/components/ui/select'
import { Dialog } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import { confirm } from '@/composables/useConfirm'
import ScriptManager from './ScriptManager.vue'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const activeTab = ref((route.query.tab as string) || 'global')
const loading = ref(false)

// ============================================================
// 全局配置
// ============================================================
// 抽取引擎默认分组参数（BaseExtract / LangExtract）
const DEFAULT_ENGINES: Record<string, any> = {
  BaseExtract: {
    temperature: 0.0,
    top_p: 0.1,
    top_k: 20,
    max_tokens: 32768,
    timeout: 300,
    enable_thinking: false,
    concurrency: { max_concurrency: 24, cross_category: 24, within_category: 1 },
    batch: { single_threshold: 8000, batch_chars: 6000, overlap: 500, context_truncate: 32000 },
  },
  LangExtract: {
    temperature: 0.0,
    top_p: 0.1,
    top_k: 20,
    max_tokens: 32768,
    timeout: 300,
    enable_thinking: false,
    format_type: 'JSON',
    fence_output: false,
    max_examples: 3,
    passes: 2,
    context_window_chars: 28000,
    max_char_buffer: 40000,
    concurrency: { max_concurrency: 24, cross_category: 8, within_category: 3 },
  },
}
const globalConfig = ref<Record<string, any>>({
  retrieval: {
    top_k: 20,
    per_dim_top_k: 30,
    default_confidence_threshold: 0.35,
    context_top_k: 20,
    context_max_tokens: 28000,
    context: {
      chars_per_token: 1.5,
      min_keep_chars: 200,
      truncate_marker: '\n[...内容截断...]',
    },
    phase2: { top_k: 5, per_dim_top_k: 10 },
    query_embed: {
      content_max_chars: 2000,
      feature_repeat: 2,
      embed_max_length: 2048,
      type_query: '表格 数据结构 行列',
      dedupe_similarity_threshold: 0.85,
    },
    weights: {
      path: 0.15,
      title: 0.2,
      content: 0.45,
      type: 0.05,
      structural: 0.15,
    },
    reranker: {
      enabled: true,
      model: '',
      top_n: 15,
    },
    hybrid: {
      enabled: true,
      dense_candidate_k: 80,
      keyword_top_k: 60,
      rrf_k: 60,
      dense_weight: 1.0,
      keyword_weight: 1.2,
      keyword_min_hits: 1,
    },
  },
  llm: {
    engine: 'BaseExtract',
    engines: JSON.parse(JSON.stringify(DEFAULT_ENGINES)),
  },
  kb_tool: {
    embed_batch_size: 32,
    search_concurrency: 10,
    semantic_top_k: 5,
    match_top_k: 1,
    match_threshold: 0.9,
    script_timeout: 10,
  },
})
const globalSaving = ref(false)
// 全局配置各大区块折叠状态（仅大项可折叠，默认收起缩短页面）
const retrievalOpen = ref(false)
const llmOpen = ref(false)
const kbToolOpen = ref(false)

// 当前选中引擎及参数（引擎切换后视图联动）
const currentEngine = computed(() => globalConfig.value.llm?.engine || 'BaseExtract')
const currentEngineParams = computed(() => {
  const engines = globalConfig.value.llm?.engines || DEFAULT_ENGINES
  return engines[currentEngine.value] || engines.BaseExtract || {}
})

// 旧结构 → 新结构映射（引擎名重命名 + 顶层 llm 参数并入引擎分组）
function normalizeEngineName(engine?: string): string {
  if (engine === 'glmocr') return 'BaseExtract'
  if (engine === 'langextract') return 'LangExtract'
  return engine || 'BaseExtract'
}

function mergeEngineParams(base: any, override: any): any {
  const out = JSON.parse(JSON.stringify(base))
  override = override || {}
  for (const key of Object.keys(override)) {
    if (typeof override[key] === 'object' && override[key] !== null && typeof out[key] === 'object') {
      out[key] = { ...out[key], ...override[key] }
    } else {
      out[key] = override[key]
    }
  }
  return out
}

async function loadGlobal() {
  try {
    const res = await kbApi.getExtractionGlobal(kbId.value)
    const content = (res.content as Record<string, any>) || {}
    const rawLlm = content.llm || {}
    const rawRetrieval = content.retrieval || {}

    // 引擎：映射旧名，并兼容旧顶层 llm 参数并入 BaseExtract
    const engine = normalizeEngineName(rawLlm.engine || content.engine)
    const baseExtractOld: any = {}
    for (const k of ['temperature', 'top_p', 'top_k', 'max_tokens', 'timeout', 'enable_thinking']) {
      if (k in rawLlm) baseExtractOld[k] = rawLlm[k]
    }
    if (rawLlm.concurrency) baseExtractOld.concurrency = rawLlm.concurrency
    if (rawLlm.batch) baseExtractOld.batch = rawLlm.batch

    // format_type / fence_output 仅 LangExtract 生效，旧顶层值并入 LangExtract
    const langExtractOld: any = {}
    for (const k of ['format_type', 'fence_output']) {
      if (k in rawLlm) langExtractOld[k] = rawLlm[k]
    }

    const engines: Record<string, any> = {}
    for (const [name, def] of Object.entries(DEFAULT_ENGINES)) {
      const stored = (rawLlm.engines || {})[name]
      const legacy = name === 'BaseExtract' ? baseExtractOld : name === 'LangExtract' ? langExtractOld : {}
      engines[name] = mergeEngineParams(def, legacy)
      if (stored) engines[name] = mergeEngineParams(engines[name], stored)
    }

    globalConfig.value = {
      retrieval: {
        top_k: rawRetrieval.top_k ?? 20,
        per_dim_top_k: rawRetrieval.per_dim_top_k ?? 30,
        default_confidence_threshold: rawRetrieval.default_confidence_threshold ?? 0.35,
        context_top_k: rawRetrieval.context_top_k ?? 20,
        context_max_tokens: rawRetrieval.context_max_tokens ?? 28000,
        context: {
          chars_per_token: (rawRetrieval.context || {}).chars_per_token ?? 1.5,
          min_keep_chars: (rawRetrieval.context || {}).min_keep_chars ?? 200,
          truncate_marker: (rawRetrieval.context || {}).truncate_marker ?? '\n[...内容截断...]',
        },
        phase2: {
          top_k: (rawRetrieval.phase2 || {}).top_k ?? 5,
          per_dim_top_k: (rawRetrieval.phase2 || {}).per_dim_top_k ?? 10,
        },
        query_embed: {
          content_max_chars: (rawRetrieval.query_embed || {}).content_max_chars ?? 2000,
          feature_repeat: (rawRetrieval.query_embed || {}).feature_repeat ?? 2,
          embed_max_length: (rawRetrieval.query_embed || {}).embed_max_length ?? 2048,
          type_query: (rawRetrieval.query_embed || {}).type_query ?? '表格 数据结构 行列',
          dedupe_similarity_threshold: (rawRetrieval.query_embed || {}).dedupe_similarity_threshold ?? 0.85,
        },
        weights: { path: 0.15, title: 0.2, content: 0.45, type: 0.05, structural: 0.15, ...(rawRetrieval.weights || {}) },
        reranker: { enabled: true, model: '', top_n: 15, ...(rawRetrieval.reranker || {}) },
        hybrid: {
          enabled: (rawRetrieval.hybrid || {}).enabled ?? true,
          dense_candidate_k: (rawRetrieval.hybrid || {}).dense_candidate_k ?? 80,
          keyword_top_k: (rawRetrieval.hybrid || {}).keyword_top_k ?? 60,
          rrf_k: (rawRetrieval.hybrid || {}).rrf_k ?? 60,
          dense_weight: (rawRetrieval.hybrid || {}).dense_weight ?? 1.0,
          keyword_weight: (rawRetrieval.hybrid || {}).keyword_weight ?? 1.2,
          keyword_min_hits: (rawRetrieval.hybrid || {}).keyword_min_hits ?? 1,
        },
      },
      llm: {
        engine,
        engines,
      },
      kb_tool: {
        embed_batch_size: (content.kb_tool || {}).embed_batch_size ?? 32,
        search_concurrency: (content.kb_tool || {}).search_concurrency ?? 10,
        semantic_top_k: (content.kb_tool || {}).semantic_top_k ?? 5,
        match_top_k: (content.kb_tool || {}).match_top_k ?? 1,
        match_threshold: (content.kb_tool || {}).match_threshold ?? 0.9,
        script_timeout: (content.kb_tool || {}).script_timeout ?? 10,
      },
    }
  } catch {
    // 拦截器提示
  }
}

async function saveGlobal() {
  globalSaving.value = true
  try {
    await kbApi.saveExtractionGlobal(kbId.value, {
      enabled: true,
      content: globalConfig.value,
    })
    toast.success('全局配置已保存')
  } catch {
    // 拦截器提示
  } finally {
    globalSaving.value = false
  }
}

// ============================================================
// Schema 模板
// ============================================================
interface CategoryNode {
  id: string
  name: string
  description: string
  return_type: string
  extraction_strategy: string
  query_mode: string
  fixed_query: string | null
  confidence_threshold: number | null
  top_k: number | null
  rerank_top_k: number | null
  max_tokens: number | null
  datasets: Record<string, unknown>[]
  is_active: boolean
  sort_order: number
  // 名称来源 / Query 术语集配置
  name_source: string
  name_term_base_id: string | null
  name_term_field: string | null
  query_sources: QuerySourceConfig[]
  fields: FieldNode[]
}
interface QuerySourceConfig {
  label: string
  term_base_id: string
  group_field: string
  value_field: string
  in_query: boolean
  dedupe: boolean
  // 通用 Query 条目上限（取代原先全局 max_items/max_methods 等 item/method 限定）
  query_main_limit: number
  query_refined_limit: number
}
interface TermBaseColumn {
  name: string
  type: string
  label?: string
}
interface FieldNode {
  id: string
  name: string
  type: string
  description: string
  example: string | null
  required: boolean
  sort_order: number
}
interface TemplateItem {
  id: string
  name: string
  description: string
  is_active: boolean
  categories: CategoryNode[]
}

const templates = ref<TemplateItem[]>([])
const currentTemplate = ref<TemplateItem | null>(null)
const currentCat = ref<CategoryNode | null>(null)
const templateLoading = ref(false)
const expandedCats = ref<Set<string>>(new Set())

// 模板对话框
const tplDialogOpen = ref(false)
const tplForm = ref({ name: '', description: '' })
const tplSubmitting = ref(false)

// 类别对话框
const catDialogOpen = ref(false)
const catEditMode = ref(false)
const editingCatId = ref<string | null>(null)
const catForm = ref({
  name: '',
  description: '',
  return_type: 'array',
  extraction_strategy: 'auto',
  query_mode: 'fixed',
  fixed_query: '',
  confidence_threshold: '' as string | number,
  top_k: '' as string | number,
  rerank_top_k: '' as string | number,
  max_tokens: '' as string | number,
  is_active: true,
  // 名称来源 / Query 术语集配置
  name_source: 'manual',
  name_term_base_id: '',
  name_term_field: '',
  query_sources: [] as QuerySourceConfig[],
})
const catSubmitting = ref(false)

// 字段对话框
const fieldDialogOpen = ref(false)
const fieldEditMode = ref(false)
const editingFieldId = ref<string | null>(null)
const fieldForm = ref({
  name: '',
  type: 'string',
  description: '',
  example: '',
  required: true,
})
const fieldSubmitting = ref(false)

// 数据集列表（供类别数据集绑定选择）
const datasets = ref<Record<string, unknown>[]>([])

// 术语集列表（供名称来源 / Query 级联选择）
const termBases = ref<TermBase[]>([])
const termBaseLoading = ref(false)

// 名称来源术语集字段选项
const nameTermFields = computed<TermBaseColumn[]>(() =>
  effectiveFieldsOfTermBase(catForm.value.name_term_base_id),
)

// 手动类术语集的内置术语字段（columns 为空时使用）
const MANUAL_TERM_FIELDS: TermBaseColumn[] = [
  { name: 'term_name', label: '术语名称', type: 'string' },
  { name: 'standard_name', label: '标准名称', type: 'string' },
  { name: 'definition', label: '定义', type: 'string' },
  { name: 'category', label: '分类', type: 'string' },
  { name: 'synonyms', label: '同义词', type: 'string' },
  { name: 'aliases', label: '别称', type: 'string' },
  { name: 'standard_number', label: '标准编号', type: 'string' },
]

// 根据术语集 ID 获取其可选项字段（api/db 用 columns，manual 用内置术语字段）
// 显示名优先使用 column_aliases 中的新表头名称，value 仍为原始字段名
function effectiveFieldsOfTermBase(baseId: string): TermBaseColumn[] {
  const tb = termBases.value.find((b) => b.id === baseId)
  if (!tb) return []
  const aliases = tb.column_aliases || {}
  const fields = tb.columns && tb.columns.length > 0 ? tb.columns : MANUAL_TERM_FIELDS
  return fields.map((c) => ({
    ...c,
    label: aliases[c.name] || c.label || c.name,
  }))
}
function fieldsOfTermBase(baseId: string): TermBaseColumn[] {
  return effectiveFieldsOfTermBase(baseId)
}

// 类别显示名：term_base 类型 name 为空时，用术语库名作为默认显示名
function categoryDisplayName(cat: { name?: string; name_source?: string; name_term_base_id?: string | null }): string {
  if (cat.name && cat.name.trim()) return cat.name
  if (cat.name_source === 'term_base') {
    const tb = termBases.value.find((b) => b.id === cat.name_term_base_id)
    return tb ? tb.name : '术语类别'
  }
  return cat.name || '未命名类别'
}

async function loadTermBases() {
  termBaseLoading.value = true
  try {
    const res = await kbApi.listTermBases(kbId.value)
    termBases.value = (res.items as TermBase[]) || []
  } catch {
    termBases.value = []
  } finally {
    termBaseLoading.value = false
  }
}

// 添加 / 移除 Query 术语集
const expandedPool = ref<Set<number>>(new Set())

function addQuerySource() {
  catForm.value.query_sources.push({
    label: '',
    term_base_id: '',
    group_field: '',
    value_field: '',
    in_query: false,
    dedupe: false,
    query_main_limit: 30,
    query_refined_limit: 8,
  })
  // 新添加的术语集默认展开
  expandedPool.value.add(catForm.value.query_sources.length - 1)
}
function removeQuerySource(index: number) {
  catForm.value.query_sources.splice(index, 1)
  // 移除后重建索引集合
  const next = new Set<number>()
  const old = Array.from(expandedPool.value)
  for (let i = 0; i < catForm.value.query_sources.length; i++) {
    if (old.includes(i)) next.add(i)
  }
  expandedPool.value = next
}
function toggleExpandPool(index: number) {
  if (expandedPool.value.has(index)) expandedPool.value.delete(index)
  else expandedPool.value.add(index)
}
// 保存：名称替换为术语集名称并收起
function saveQuerySource(index: number) {
  const qs = catForm.value.query_sources[index]
  const tb = termBases.value.find((b) => b.id === qs.term_base_id)
  if (tb) qs.label = tb.name
  expandedPool.value.delete(index)
}

async function loadTemplates() {
  templateLoading.value = true
  try {
    const list = await kbApi.listSchemaTemplates(kbId.value)
    templates.value = (list as unknown as TemplateItem[]) || []
    if (templates.value.length > 0) {
      await selectTemplate(templates.value[0].id)
    } else {
      currentTemplate.value = null
    }
  } catch {
    templates.value = []
  } finally {
    templateLoading.value = false
  }
}

async function selectTemplate(id: string) {
  try {
    const detail = await kbApi.getSchemaTemplate(kbId.value, id)
    const tpl = detail as unknown as TemplateItem
    // 确保 categories 和 fields 存在
    if (!tpl.categories) tpl.categories = []
    tpl.categories = tpl.categories.map(cat => ({
      ...cat,
      fields: cat.fields || [],
    }))
    currentTemplate.value = tpl
  } catch {
    // 拦截器提示
  }
}

function openCreateTemplate() {
  tplForm.value = { name: '', description: '' }
  tplDialogOpen.value = true
}

async function submitTemplate() {
  if (!tplForm.value.name.trim()) {
    toast.warning('请填写模板名称')
    return
  }
  tplSubmitting.value = true
  try {
    const t = await kbApi.createSchemaTemplate(kbId.value, {
      name: tplForm.value.name.trim(),
      description: tplForm.value.description.trim() || undefined,
    })
    toast.success('模板已创建', tplForm.value.name)
    tplDialogOpen.value = false
    await loadTemplates()
    await selectTemplate(t.id as string)
  } catch {
    // 拦截器提示
  } finally {
    tplSubmitting.value = false
  }
}

async function deleteTemplate(t: TemplateItem) {
  if (!currentTemplate.value) return
  if (!await confirm(`确定删除模板「${t.name}」？其下所有类别与字段将一并删除。`)) return
  try {
    await kbApi.deleteSchemaTemplate(kbId.value, t.id)
    toast.success('模板已删除', t.name)
    await loadTemplates()
  } catch {
    // 拦截器提示
  }
}

function openCreateCategory() {
  catEditMode.value = false
  editingCatId.value = null
  catForm.value = {
    name: '',
    description: '',
    return_type: 'array',
    extraction_strategy: 'auto',
    query_mode: 'fixed',
    fixed_query: '',
    confidence_threshold: '',
    top_k: '',
    rerank_top_k: '',
    max_tokens: '',
    is_active: true,
    name_source: 'manual',
    name_term_base_id: '',
    name_term_field: '',
    query_sources: [],
  }
  expandedPool.value = new Set()
  catDialogOpen.value = true
}

function openEditCategory(cat: CategoryNode) {
  catEditMode.value = true
  editingCatId.value = cat.id
  catForm.value = {
    name: cat.name,
    description: cat.description,
    return_type: cat.return_type,
    extraction_strategy: cat.extraction_strategy,
    query_mode: cat.query_mode,
    fixed_query: cat.fixed_query || '',
    confidence_threshold: cat.confidence_threshold ?? '',
    top_k: cat.top_k ?? '',
    rerank_top_k: cat.rerank_top_k ?? '',
    max_tokens: cat.max_tokens ?? '',
    is_active: cat.is_active,
    name_source: cat.name_source || 'manual',
    name_term_base_id: cat.name_term_base_id || '',
    name_term_field: cat.name_term_field || '',
    query_sources: (cat.query_sources || []).map((s) => ({
      label: s.label || '',
      term_base_id: s.term_base_id || '',
      group_field: s.group_field || '',
      value_field: s.value_field || '',
      in_query: !!s.in_query,
      dedupe: !!s.dedupe,
      query_main_limit: s.query_main_limit ?? 30,
      query_refined_limit: s.query_refined_limit ?? 8,
    })),
  }
  expandedPool.value = new Set()
  catDialogOpen.value = true
}

async function submitCategory() {
  if (!currentTemplate.value) return

  // ---- 名称来源 / Query 校验 ----
  if (catForm.value.name_source === 'manual' && !catForm.value.name.trim()) {
    toast.warning('请填写类别名称')
    return
  }
  if (catForm.value.name_source === 'term_base') {
    if (!catForm.value.name_term_base_id) {
      toast.warning('请选择名称来源术语集')
      return
    }
    if (!catForm.value.name_term_field) {
      toast.warning('请选择名称来源字段')
      return
    }
  }
  for (const [i, s] of catForm.value.query_sources.entries()) {
    if (!s.label.trim()) {
      toast.warning(`第 ${i + 1} 个术语集名称不能为空`)
      return
    }
    if (!s.term_base_id) {
      toast.warning(`第 ${i + 1} 个术语集未选择术语集`)
      return
    }
    if (!s.value_field) {
      toast.warning(`第 ${i + 1} 个术语集的值字段必选`)
      return
    }
  }

  catSubmitting.value = true
  try {
    const payload: Record<string, unknown> = {
      name: catForm.value.name.trim(),
      description: catForm.value.description.trim(),
      return_type: catForm.value.return_type,
      extraction_strategy: catForm.value.extraction_strategy,
      query_mode: 'fixed',
      is_active: catForm.value.is_active,
      name_source: catForm.value.name_source,
      name_term_base_id: catForm.value.name_term_base_id || null,
      name_term_field: catForm.value.name_term_field || null,
      query_sources: catForm.value.query_sources.map((s) => ({
        label: s.label.trim(),
        term_base_id: s.term_base_id,
        group_field: s.group_field || null,
        value_field: s.value_field,
        in_query: !!s.in_query,
        dedupe: !!s.dedupe,
        query_main_limit: s.query_main_limit ?? 30,
        query_refined_limit: s.query_refined_limit ?? 8,
      })),
    }
    payload.fixed_query = catForm.value.fixed_query || null
    if (catForm.value.extraction_strategy === 'auto') {
      payload.confidence_threshold =
        catForm.value.confidence_threshold === '' ? null : Number(catForm.value.confidence_threshold)
    }
    payload.top_k = catForm.value.top_k === '' ? null : Number(catForm.value.top_k)
    payload.rerank_top_k =
      catForm.value.rerank_top_k === '' ? null : Number(catForm.value.rerank_top_k)
    payload.max_tokens = catForm.value.max_tokens === '' ? null : Number(catForm.value.max_tokens)

    if (catEditMode.value) {
      // 编辑模式：使用 editingCatId
      if (editingCatId.value) {
        await kbApi.updateSchemaCategory(kbId.value, currentTemplate.value.id, editingCatId.value, payload)
        toast.success('类别已更新', catForm.value.name)
      }
    } else {
      await kbApi.createSchemaCategory(kbId.value, currentTemplate.value.id, payload)
      toast.success('类别已创建', catForm.value.name)
    }
    catDialogOpen.value = false
    await selectTemplate(currentTemplate.value.id)
  } catch {
    // 拦截器提示
  } finally {
    catSubmitting.value = false
  }
}

async function deleteCategory(cat: CategoryNode) {
  if (!currentTemplate.value) return
  if (!await confirm(`确定删除类别「${cat.name}」？其下所有字段将一并删除。`)) return
  try {
    await kbApi.deleteSchemaCategory(kbId.value, currentTemplate.value.id, cat.id)
    toast.success('类别已删除', cat.name)
    await selectTemplate(currentTemplate.value.id)
  } catch {
    // 拦截器提示
  }
}

function toggleExpand(catId: string) {
  if (expandedCats.value.has(catId)) expandedCats.value.delete(catId)
  else expandedCats.value.add(catId)
}

function openCreateField(cat: CategoryNode) {
  fieldEditMode.value = false
  editingFieldId.value = null
  currentCat.value = cat
  fieldForm.value = { name: '', type: 'string', description: '', example: '', required: true }
  fieldDialogOpen.value = true
}

function openEditField(cat: CategoryNode, field: FieldNode) {
  fieldEditMode.value = true
  editingFieldId.value = field.id
  currentCat.value = cat
  fieldForm.value = {
    name: field.name,
    type: field.type || 'string',
    description: field.description || '',
    example: field.example || '',
    required: field.required,
  }
  fieldDialogOpen.value = true
}

async function submitField() {
  if (!currentTemplate.value || !currentCat.value) return
  if (!fieldForm.value.name.trim()) {
    toast.warning('请填写字段名称')
    return
  }
  fieldSubmitting.value = true
  try {
    const payload: Record<string, unknown> = {
      name: fieldForm.value.name.trim(),
      type: fieldForm.value.type,
      description: fieldForm.value.description.trim(),
      example: fieldForm.value.example.trim() || null,
      required: fieldForm.value.required,
    }
    if (fieldEditMode.value) {
      if (editingFieldId.value) {
        await kbApi.updateSchemaField(kbId.value, currentTemplate.value.id, currentCat.value.id, editingFieldId.value, payload)
        toast.success('字段已更新', fieldForm.value.name)
      }
    } else {
      await kbApi.createSchemaField(kbId.value, currentTemplate.value.id, currentCat.value.id, payload)
      toast.success('字段已创建', fieldForm.value.name)
    }
    fieldDialogOpen.value = false
    currentCat.value = null
    await selectTemplate(currentTemplate.value.id)
  } catch {
    // 拦截器提示
  } finally {
    fieldSubmitting.value = false
  }
}

async function deleteField(cat: CategoryNode, field: FieldNode) {
  if (!currentTemplate.value) return
  if (!await confirm(`确定删除字段「${field.name}」？`)) return
  try {
    await kbApi.deleteSchemaField(kbId.value, currentTemplate.value.id, cat.id, field.id)
    toast.success('字段已删除', field.name)
    await selectTemplate(currentTemplate.value.id)
  } catch {
    // 拦截器提示
  }
}

// ============================================================
// Prompt 模板
// ============================================================
interface PromptItem {
  id: string
  name: string
  description: string
  scope: string
  system_prompt: string
  user_prompt: string | null
  schema_template_id: string | null
  is_active: boolean
}
const prompts = ref<PromptItem[]>([])
const promptLoading = ref(false)
const promptDialogOpen = ref(false)
const promptSubmitting = ref(false)

// 新建 Prompt 弹框表单
const promptForm = ref({
  name: '',
  description: '',
  scope: 'simple' as 'simple' | 'schema',
  schema_template_id: '',
  category_ids: [] as string[],
  is_active: true,
})
// Schema 模板列表（供选择）
const promptSchemaTemplates = ref<{ id: string; name: string; categories: PromptSchemaCat[] }[]>([])
const promptSchemaLoading = ref(false)
// 选中 Schema 模板的类别（全选状态管理）
interface PromptSchemaCat {
  id: string
  name: string
  name_source?: string
  name_term_base_id?: string | null
}
const promptSchemaCats = ref<PromptSchemaCat[]>([])

async function loadPrompts() {
  promptLoading.value = true
  try {
    const res = await kbApi.listExtractionPrompts(kbId.value)
    prompts.value = (res.items as unknown as PromptItem[]) || []
  } catch {
    prompts.value = []
  } finally {
    promptLoading.value = false
  }
}

async function loadPromptSchemaTemplates() {
  promptSchemaLoading.value = true
  try {
    const list = (await kbApi.listSchemaTemplates(kbId.value)) as unknown as {
      id: string
      name: string
      categories: { id: string; name: string }[]
    }[]
    promptSchemaTemplates.value = list || []
  } catch {
    promptSchemaTemplates.value = []
  } finally {
    promptSchemaLoading.value = false
  }
}

// 选中 Schema 模板后加载类别（默认全选）
async function onPromptSchemaChange() {
  promptSchemaCats.value = []
  promptForm.value.category_ids = []
  const id = promptForm.value.schema_template_id
  if (!id) return
  const tpl = promptSchemaTemplates.value.find((t) => t.id === id)
  if (tpl && tpl.categories && tpl.categories.length > 0) {
    promptSchemaCats.value = tpl.categories
    promptForm.value.category_ids = tpl.categories.map((c) => c.id)
  } else {
    // 列表未带类别时，拉取详情
    try {
      const detail = (await kbApi.getSchemaTemplate(kbId.value, id)) as unknown as {
        categories: PromptSchemaCat[]
      }
      const cats = detail.categories || []
      promptSchemaCats.value = cats
      promptForm.value.category_ids = cats.map((c) => c.id)
    } catch {
      promptSchemaCats.value = []
    }
  }
}

function togglePromptCat(id: string) {
  const idx = promptForm.value.category_ids.indexOf(id)
  if (idx >= 0) promptForm.value.category_ids.splice(idx, 1)
  else promptForm.value.category_ids.push(id)
}

// 监听选中 Schema 模板，加载类别并默认全选
watch(
  () => promptForm.value.schema_template_id,
  () => {
    onPromptSchemaChange()
  },
)

function openCreatePrompt() {
  promptForm.value = {
    name: '',
    description: '',
    scope: 'simple',
    schema_template_id: '',
    category_ids: [],
    is_active: true,
  }
  promptSchemaCats.value = []
  promptDialogOpen.value = true
  loadPromptSchemaTemplates()
}

async function submitPrompt() {
  if (!promptForm.value.name.trim()) {
    toast.warning('请填写模板名称')
    return
  }
  if (promptForm.value.scope === 'schema' && !promptForm.value.schema_template_id) {
    toast.warning('请选择 Schema 模板')
    return
  }
  if (promptForm.value.scope === 'schema' && promptForm.value.category_ids.length === 0) {
    toast.warning('请至少选择一个类别')
    return
  }
  promptSubmitting.value = true
  try {
    const payload = {
      name: promptForm.value.name.trim(),
      description: promptForm.value.description.trim(),
      scope: promptForm.value.scope,
      is_active: promptForm.value.is_active,
      schema_template_id: promptForm.value.scope === 'schema' ? promptForm.value.schema_template_id : null,
      category_ids: promptForm.value.scope === 'schema' ? promptForm.value.category_ids : [],
    }
    const created = await kbApi.createExtractionPrompt(kbId.value, payload)
    const newId = (created as { id?: string }).id
    promptDialogOpen.value = false
    await loadPrompts()
    // 创建后跳转独立编辑页
    if (newId) {
      router.push(`/kbs/${kbId.value}/extraction-config/prompts/${newId}`)
    }
  } catch {
    // 拦截器提示
  } finally {
    promptSubmitting.value = false
  }
}

function openEditPrompt(p: PromptItem) {
  router.push(`/kbs/${kbId.value}/extraction-config/prompts/${p.id}`)
}

async function deletePrompt(p: PromptItem) {
  if (!await confirm(`确定删除 Prompt「${p.name}」？`)) return
  try {
    await kbApi.deleteExtractionPrompt(kbId.value, p.id)
    toast.success('Prompt 已删除', p.name)
    await loadPrompts()
  } catch {
    // 拦截器提示
  }
}

// ============================================================
// 后处理与校验规则（按 Schema 模板分组）
// ============================================================
interface RuleGroupItem {
  id: string
  category_id: string
  category_name: string
  script_id: string
  script_name: string
  script_description: string
  stage: 'post' | 'validation'
  sort_order: number
}
interface RuleGroupCategory {
  id: string
  name: string
  rules: RuleGroupItem[]
}
interface RuleGroup {
  id: string
  name: string
  schema_template_id: string
  schema_template_name: string
  description: string
  category_count: number
  item_count: number
  categories?: RuleGroupCategory[]
  loaded?: boolean
}

const ruleGroups = ref<RuleGroup[]>([])
const ruleGroupsLoading = ref(false)
const expandedGroups = ref<Set<string>>(new Set())
const expandedCategories = ref<Set<string>>(new Set())
const scriptsByFolder = ref<Record<string, any[]>>({ post: [], validation: [] })

async function loadRuleGroups() {
  ruleGroupsLoading.value = true
  try {
    const res = await kbApi.listRuleGroups(kbId.value)
    ruleGroups.value = (res.items as unknown as RuleGroup[]) || []
    // 加载脚本目录（供添加规则选择）
    const scripts = await kbApi.listScripts(kbId.value)
    const grouped: Record<string, any[]> = { post: [], validation: [] }
    for (const it of (scripts.items as any[]) || []) {
      const f = it.folder || 'post'
      if (!grouped[f]) grouped[f] = []
      grouped[f].push(it)
    }
    scriptsByFolder.value = grouped
  } catch {
    ruleGroups.value = []
  } finally {
    ruleGroupsLoading.value = false
  }
}

function toggleGroup(id: string) {
  if (expandedGroups.value.has(id)) {
    expandedGroups.value.delete(id)
    return
  }
  expandedGroups.value.add(id)
  const g = ruleGroups.value.find((x) => x.id === id)
  if (g && !g.loaded) loadRuleGroupDetail(g)
}

async function loadRuleGroupDetail(g: RuleGroup) {
  try {
    const d = await kbApi.getRuleGroup(kbId.value, g.id)
    g.categories = (d.categories as RuleGroupCategory[]) || []
    g.loaded = true
  } catch {
    // 拦截器提示
  }
}

function toggleCategory(groupId: string, catId: string) {
  const k = `${groupId}:${catId}`
  if (expandedCategories.value.has(k)) expandedCategories.value.delete(k)
  else expandedCategories.value.add(k)
}

// --- 新建规则组 ---
const groupDialogOpen = ref(false)
const groupSubmitting = ref(false)
const groupForm = ref({ name: '', schema_template_id: '', description: '' })
function openCreateGroup() {
  groupForm.value = {
    name: '',
    schema_template_id: templates.value[0]?.id || '',
    description: '',
  }
  groupDialogOpen.value = true
}
async function submitGroup() {
  if (!groupForm.value.schema_template_id) {
    toast.warning('请选择 Schema 模板')
    return
  }
  groupSubmitting.value = true
  try {
    await kbApi.createRuleGroup(kbId.value, {
      name: groupForm.value.name.trim() || undefined,
      schema_template_id: groupForm.value.schema_template_id,
      description: groupForm.value.description.trim() || undefined,
    })
    toast.success('规则组已创建')
    groupDialogOpen.value = false
    await loadRuleGroups()
  } catch {
    // 拦截器提示
  } finally {
    groupSubmitting.value = false
  }
}
async function deleteGroup(g: RuleGroup) {
  if (!(await confirm(`确定删除规则组「${g.name}」？其下所有规则将一并删除。`))) return
  try {
    await kbApi.deleteRuleGroup(kbId.value, g.id)
    toast.success('规则组已删除')
    await loadRuleGroups()
  } catch {
    // 拦截器提示
  }
}

// --- 添加规则（先选阶段，脚本仅显示该阶段） ---
const addRuleDialogOpen = ref(false)
const addRuleSubmitting = ref(false)
const addRuleCtx = ref<{ groupId: string; categoryId: string; categoryName: string } | null>(null)
const addRuleForm = ref({ stage: 'post' as 'post' | 'validation', script_id: '' })
function openAddRule(groupId: string, cat: RuleGroupCategory) {
  addRuleCtx.value = { groupId, categoryId: cat.id, categoryName: cat.name }
  addRuleForm.value = { stage: 'post', script_id: '' }
  addRuleDialogOpen.value = true
}
const addRuleScripts = computed<any[]>(() =>
  (scriptsByFolder.value[addRuleForm.value.stage] || []).filter((s) => s.enabled !== false),
)
async function submitAddRule() {
  if (!addRuleForm.value.script_id) {
    toast.warning('请选择脚本')
    return
  }
  if (!addRuleCtx.value) return
  addRuleSubmitting.value = true
  try {
    const g = ruleGroups.value.find((x) => x.id === addRuleCtx.value!.groupId)
    const cat = g?.categories?.find((c) => c.id === addRuleCtx.value!.categoryId)
    if (!g || !cat) return
    const script = (scriptsByFolder.value[addRuleForm.value.stage] || []).find(
      (s) => s.id === addRuleForm.value.script_id,
    )
    cat.rules = cat.rules || []
    cat.rules.push({
      id: '',
      category_id: cat.id,
      category_name: cat.name,
      script_id: addRuleForm.value.script_id,
      script_name: script?.name || '',
      script_description: script?.description || '',
      stage: addRuleForm.value.stage,
      sort_order: cat.rules.length,
    })
    await persistCategoryItems(g, cat)
    toast.success('规则已添加')
    addRuleDialogOpen.value = false
  } catch {
    // 拦截器提示
  } finally {
    addRuleSubmitting.value = false
  }
}
async function removeItem(g: RuleGroup, cat: RuleGroupCategory, rule: RuleGroupItem) {
  if (!(await confirm(`确定移除此规则「${rule.script_name}」？`))) return
  cat.rules = cat.rules.filter((r) => r !== rule)
  cat.rules.forEach((r, i) => (r.sort_order = i))
  await persistCategoryItems(g, cat)
}
async function persistCategoryItems(g: RuleGroup, cat: RuleGroupCategory) {
  try {
    await kbApi.saveRuleGroupItems(kbId.value, g.id, {
      category_id: cat.id,
      category_name: cat.name,
      items: cat.rules.map((r, i) => ({
        category_id: cat.id,
        category_name: cat.name,
        script_id: r.script_id,
        stage: r.stage,
        sort_order: i,
      })),
    })
  } catch {
    // 拦截器提示
  }
}

// --- 拖拽排序（原生 HTML5，跨 stage 统一） ---
let dragItem: RuleGroupItem | null = null
function onRuleDragStart(rule: RuleGroupItem) {
  dragItem = rule
}
function onRuleDragOver(e: DragEvent) {
  e.preventDefault()
}
function onRuleDrop(g: RuleGroup, cat: RuleGroupCategory, target: RuleGroupItem) {
  if (dragItem && dragItem !== target) {
    const fromIdx = cat.rules.indexOf(dragItem)
    const toIdx = cat.rules.indexOf(target)
    cat.rules.splice(fromIdx, 1)
    cat.rules.splice(toIdx, 0, dragItem)
    cat.rules.forEach((r, i) => (r.sort_order = i))
    persistCategoryItems(g, cat)
  }
  dragItem = null
}
function moveRule(g: RuleGroup, cat: RuleGroupCategory, rule: RuleGroupItem, dir: -1 | 1) {
  const idx = cat.rules.indexOf(rule)
  const to = idx + dir
  if (to < 0 || to >= cat.rules.length) return
  cat.rules.splice(idx, 1)
  cat.rules.splice(to, 0, rule)
  cat.rules.forEach((r, i) => (r.sort_order = i))
  persistCategoryItems(g, cat)
}

// 类别规则摘要（后处理/校验数量），对齐 Schema 类别行下方描述
function summarizeStages(cat: RuleGroupCategory): string {
  const rules = cat.rules || []
  const parts: string[] = []
  const post = rules.filter((r) => r.stage === 'post').length
  const val = rules.filter((r) => r.stage === 'validation').length
  if (post) parts.push(`后处理 ${post}`)
  if (val) parts.push(`校验 ${val}`)
  return parts.join(' · ')
}

// ============================================================
// 版本管理
// ============================================================
interface VersionItem {
  id: string
  version: number
  name: string
  description: string
  created_at: string
  created_by: string | null
}
const versions = ref<VersionItem[]>([])
const versionLoading = ref(false)
const versionDialogOpen = ref(false)
const versionForm = ref({ name: '', description: '' })
const versionSubmitting = ref(false)

async function loadVersions() {
  versionLoading.value = true
  try {
    const res = await kbApi.listExtractionVersions(kbId.value)
    versions.value = (res.items as unknown as VersionItem[]) || []
  } catch {
    versions.value = []
  } finally {
    versionLoading.value = false
  }
}

function openCreateVersion() {
  versionForm.value = { name: '', description: '' }
  versionDialogOpen.value = true
}

async function submitVersion() {
  if (!versionForm.value.name.trim()) {
    toast.warning('请填写版本名称')
    return
  }
  versionSubmitting.value = true
  try {
    await kbApi.createExtractionVersion(kbId.value, {
      name: versionForm.value.name.trim(),
      description: versionForm.value.description.trim() || undefined,
    })
    toast.success('版本快照已创建', versionForm.value.name)
    versionDialogOpen.value = false
    await loadVersions()
  } catch {
    // 拦截器提示
  } finally {
    versionSubmitting.value = false
  }
}

// 版本详情 / 对比 / 回滚预警
const detailDialogOpen = ref(false)
const detailData = ref<Record<string, any> | null>(null)
const detailLoading = ref(false)
const diffDialogOpen = ref(false)
const diffData = ref<Record<string, any> | null>(null)
const diffLoading = ref(false)
const rollbackTarget = ref<VersionItem | null>(null)
const rollbackConfirmOpen = ref(false)
const rollingBack = ref(false)

async function openVersionDetail(v: VersionItem) {
  detailDialogOpen.value = true
  detailLoading.value = true
  detailData.value = null
  try {
    const res = await kbApi.getExtractionVersionDetail(kbId.value, v.id)
    detailData.value = (res as Record<string, any>) || {}
  } catch {
    // 拦截器提示
  } finally {
    detailLoading.value = false
  }
}

async function openVersionDiff(v: VersionItem) {
  diffDialogOpen.value = true
  diffLoading.value = true
  diffData.value = null
  try {
    const res = await kbApi.diffExtractionVersion(kbId.value, v.id)
    diffData.value = (res as Record<string, any>) || {}
  } catch {
    // 拦截器提示
  } finally {
    diffLoading.value = false
  }
}

// 回滚前预警：先拉取当前配置与目标版本的差异，展示将覆盖的配置项
async function openRollbackConfirm(v: VersionItem) {
  rollbackTarget.value = v
  rollbackConfirmOpen.value = true
  diffLoading.value = true
  diffData.value = null
  try {
    const res = await kbApi.diffExtractionVersion(kbId.value, v.id)
    diffData.value = (res as Record<string, any>) || {}
  } catch {
    // 拦截器提示
  } finally {
    diffLoading.value = false
  }
}

async function confirmRollback() {
  if (!rollbackTarget.value) return
  rollingBack.value = true
  try {
    await kbApi.rollbackExtractionVersion(kbId.value, rollbackTarget.value.id)
    toast.success('已回滚', rollbackTarget.value.name)
    rollbackConfirmOpen.value = false
    await loadGlobal()
    await loadVersions()
  } catch {
    // 拦截器提示
  } finally {
    rollingBack.value = false
  }
}

async function deleteVersion(v: VersionItem) {
  if (!await confirm(`确定删除快照「${v.name}」(v${v.version})？此操作不可撤销。`)) return
  try {
    await kbApi.deleteExtractionVersion(kbId.value, v.id)
    toast.success('已删除', v.name)
    await loadVersions()
  } catch {
    // 拦截器提示
  }
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

function onTabChange() {
  if (activeTab.value === 'global') loadGlobal()
  else if (activeTab.value === 'schema') loadTemplates()
  else if (activeTab.value === 'prompt') loadPrompts()
  else if (activeTab.value === 'rules') loadRuleGroups()
  else if (activeTab.value === 'versions') loadVersions()
}

onMounted(async () => {
  await loadTermBases()
  await loadGlobal()
  await loadTemplates()
  await loadPrompts()
  await loadRuleGroups()
  await loadVersions()
})
</script>

<template>
  <div>
    <PageHeader title="抽取配置中心" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="onTabChange">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <Tabs v-model="activeTab" class="w-full">
      <TabsList class="flex-wrap">
        <TabsTrigger value="global"><Settings2 class="mr-1 size-4" :stroke-width="1.5" />全局配置</TabsTrigger>
        <TabsTrigger value="schema"><LayoutTemplate class="mr-1 size-4" :stroke-width="1.5" />Schema 模板</TabsTrigger>
        <TabsTrigger value="prompt"><FileText class="mr-1 size-4" :stroke-width="1.5" />Prompt 模板</TabsTrigger>
        <TabsTrigger value="rules"><ListChecks class="mr-1 size-4" :stroke-width="1.5" />后处理与校验规则</TabsTrigger>
        <TabsTrigger value="scripts"><Code2 class="mr-1 size-4" :stroke-width="1.5" />脚本管理</TabsTrigger>
        <TabsTrigger value="versions"><History class="mr-1 size-4" :stroke-width="1.5" />版本管理</TabsTrigger>
      </TabsList>

      <!-- ============ 全局配置 ============ -->
      <TabsContent value="global" class="space-y-4">
        <div class="flex items-center justify-between">
          <p class="text-sm text-muted-foreground">全局抽取参数配置，所有抽取任务默认使用以下参数</p>
          <Button v-if="isEditor" size="sm" :disabled="globalSaving" @click="saveGlobal">
            <Loader2 v-if="globalSaving" class="size-4 animate-spin" :stroke-width="1.5" />
            <Save v-else class="size-4" :stroke-width="1.5" />
            保存全局配置
          </Button>
        </div>

        <!-- 检索配置 -->
        <Card class="overflow-hidden border-2 border-blue-500/20 shadow-sm">
          <button
            type="button"
            class="w-full border-b bg-gradient-to-r from-blue-500/10 to-blue-500/5 px-6 pb-3 pt-4 text-left"
            @click="retrievalOpen = !retrievalOpen"
          >
            <div class="flex items-center gap-2">
              <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/20 text-blue-500">
                <Search class="size-4" :stroke-width="2" />
              </div>
              <div class="flex-1">
                <CardTitle class="text-base font-semibold text-blue-600">检索参数</CardTitle>
                <p class="text-xs text-muted-foreground">retrieval - 文档检索与召回配置</p>
              </div>
              <ChevronDown class="size-4 text-muted-foreground transition-transform" :class="{ 'rotate-180': retrievalOpen }" :stroke-width="2" />
            </div>
          </button>
          <div v-show="retrievalOpen">
          <CardContent class="space-y-5 p-5">
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">召回 top_k</Label>
                <Input v-model.number="globalConfig.retrieval.top_k" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">单类别最终召回的最大块数，决定送入 LLM 的上下文规模</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">每维 top_k</Label>
                <Input v-model.number="globalConfig.retrieval.per_dim_top_k" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">五维检索中每个维度独立召回的最大块数</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">默认置信度阈值</Label>
                <Input v-model.number="globalConfig.retrieval.default_confidence_threshold" type="number" step="0.05" class="mt-1" />
                <p class="text-xs text-muted-foreground">类别命中判定的默认置信阈值，类别级可单独覆盖</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">上下文 top_k</Label>
                <Input v-model.number="globalConfig.retrieval.context_top_k" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">抽取上下文按块数截断的上限</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">上下文最大 token</Label>
                <Input v-model.number="globalConfig.retrieval.context_max_tokens" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">拼接上下文的最大 token 数，超出按相关性截断</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">字符/token 估算系数</Label>
                <Input v-model.number="globalConfig.retrieval.context.chars_per_token" type="number" step="0.1" class="mt-1" />
                <p class="text-xs text-muted-foreground">上下文 token 估算系数（中文约 1.5 字符/token）</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">上下文尾部最小保留字符</Label>
                <Input v-model.number="globalConfig.retrieval.context.min_keep_chars" type="number" min="0" class="mt-1" />
                <p class="text-xs text-muted-foreground">按相关性截断时上下文尾部至少保留的字符数，避免截断丢失关键信息</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">截断标记文本</Label>
                <Input v-model="globalConfig.retrieval.context.truncate_marker" type="text" class="mt-1" />
                <p class="text-xs text-muted-foreground">上下文截断处插入的占位标记文本，提示模型内容已截断</p>
              </div>
            </div>
            <!-- Phase 2 类别召回参数 -->
            <div class="rounded-lg border-2 border-blue-200/50 bg-blue-50/50 p-4 dark:bg-blue-950/20">
              <Label class="mb-3 block text-sm font-semibold text-blue-700 dark:text-blue-300">Phase 2 类别召回</Label>
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">融合 top_k</Label>
                  <Input v-model.number="globalConfig.retrieval.phase2.top_k" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">各维融合后用于判定类别命中的块数</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">每维 top_k</Label>
                  <Input v-model.number="globalConfig.retrieval.phase2.per_dim_top_k" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">每维独立召回的块数</p>
                </div>
              </div>
            </div>
            <!-- 五维 Query 编码参数（条目上限位于类别 Query 术语集配置） -->
            <div class="rounded-lg border-2 border-blue-200/50 bg-blue-50/50 p-4 dark:bg-blue-950/20">
              <Label class="mb-3 block text-sm font-semibold text-blue-700 dark:text-blue-300">五维 Query 编码参数</Label>
              <p class="mb-3 text-xs text-muted-foreground">各 Query 维条目上限（主查询维/精简维）在 Schema 模板类别的 Query 术语集配置中设置</p>
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">content 最大字符</Label>
                  <Input v-model.number="globalConfig.retrieval.query_embed.content_max_chars" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">主查询维（content）query 文本最大字符数，避免过长导致 embed 耗时</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">feature 重复次数</Label>
                  <Input v-model.number="globalConfig.retrieval.query_embed.feature_repeat" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">主查询维中 feature 名重复次数，增强大类语义权重</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">嵌入 max_length</Label>
                  <Input v-model.number="globalConfig.retrieval.query_embed.embed_max_length" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">embed 编码的最大 token 长度（bge-m3 上限）</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2 sm:col-span-2 lg:col-span-2">
                  <Label class="text-xs font-medium text-blue-600">type 维固定查询文本</Label>
                  <Input v-model="globalConfig.retrieval.query_embed.type_query" type="text" class="mt-1" />
                  <p class="text-xs text-muted-foreground">type 维固定查询文本（参考示例：表格 数据结构 行列，可按需修改）</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">语义去重阈值</Label>
                  <Input v-model.number="globalConfig.retrieval.query_embed.dedupe_similarity_threshold" type="number" step="0.01" min="0" max="1" class="mt-1" />
                  <p class="text-xs text-muted-foreground">Query 词条字符级相似度去重阈值（相似度 ≥ 该值视为重复词条）</p>
                </div>
              </div>
            </div>
            <!-- 五维权重配置 -->
            <div class="rounded-lg border-2 border-blue-200/50 bg-blue-50/50 p-4 dark:bg-blue-950/20">
              <Label class="mb-3 block text-sm font-semibold text-blue-700 dark:text-blue-300">五维权重配置</Label>
              <div class="grid gap-3 sm:grid-cols-5">
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">path (路径)</Label>
                  <Input v-model.number="globalConfig.retrieval.weights.path" type="number" step="0.05" class="mt-1" />
                  <p class="text-xs text-muted-foreground">路径维度加权</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">title (标题)</Label>
                  <Input v-model.number="globalConfig.retrieval.weights.title" type="number" step="0.05" class="mt-1" />
                  <p class="text-xs text-muted-foreground">标题维度加权</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">content (内容)</Label>
                  <Input v-model.number="globalConfig.retrieval.weights.content" type="number" step="0.05" class="mt-1" />
                  <p class="text-xs text-muted-foreground">内容维度加权（主检索维度）</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">type (类型)</Label>
                  <Input v-model.number="globalConfig.retrieval.weights.type" type="number" step="0.05" class="mt-1" />
                  <p class="text-xs text-muted-foreground">类型维度加权</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-blue-600">structural (结构)</Label>
                  <Input v-model.number="globalConfig.retrieval.weights.structural" type="number" step="0.05" class="mt-1" />
                  <p class="text-xs text-muted-foreground">结构位置维度加权</p>
                </div>
              </div>
            </div>
            <!-- 重排序（reranker） -->
            <div class="rounded-lg border-2 border-blue-200/50 bg-blue-50/50 p-4 dark:bg-blue-950/20">
              <Label class="mb-3 block text-sm font-semibold text-blue-700 dark:text-blue-300">重排序（reranker）</Label>
              <div class="grid gap-3 sm:grid-cols-3">
                <label class="flex items-center gap-2 rounded-md bg-background/80 p-3 text-sm">
                  <Switch v-model="globalConfig.retrieval.reranker.enabled" />
                  <span class="font-medium">启用重排序</span>
                </label>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">重排后 top_n</Label>
                  <Input v-model.number="globalConfig.retrieval.reranker.top_n" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">召回后重排序保留的块数</p>
                </div>
              </div>
            </div>
            <!-- 混合检索（hybrid） -->
            <div class="rounded-lg border-2 border-cyan-200/50 bg-cyan-50/50 p-4 dark:bg-cyan-950/20">
              <Label class="mb-3 block text-sm font-semibold text-cyan-700 dark:text-cyan-300">混合检索（hybrid · 稠密+稀疏 BM25 · RRF 融合）</Label>
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <label class="flex items-center gap-2 rounded-md bg-background/80 p-3 text-sm">
                  <Switch v-model="globalConfig.retrieval.hybrid.enabled" />
                  <span class="font-medium">启用混合检索</span>
                </label>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">稠密候选数 dense_candidate_k</Label>
                  <Input v-model.number="globalConfig.retrieval.hybrid.dense_candidate_k" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">稠密路融合前召回候选块数</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">词法候选数 keyword_top_k</Label>
                  <Input v-model.number="globalConfig.retrieval.hybrid.keyword_top_k" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">BM25 词法路召回候选块数</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">RRF 常数 rrf_k</Label>
                  <Input v-model.number="globalConfig.retrieval.hybrid.rrf_k" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">RRF 融合 rank 分母偏移</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">稠密权重 dense_weight</Label>
                  <Input v-model.number="globalConfig.retrieval.hybrid.dense_weight" type="number" step="0.1" class="mt-1" />
                  <p class="text-xs text-muted-foreground">稠密路在 RRF 中的权重</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">词法权重 keyword_weight</Label>
                  <Input v-model.number="globalConfig.retrieval.hybrid.keyword_weight" type="number" step="0.1" class="mt-1" />
                  <p class="text-xs text-muted-foreground">词法路在 RRF 中的权重</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-muted-foreground">词法兜底命中数 keyword_min_hits</Label>
                  <Input v-model.number="globalConfig.retrieval.hybrid.keyword_min_hits" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">类型过滤中，词法命中达到该数即保留类别（恢复强词法类别）</p>
                </div>
              </div>
            </div>
          </CardContent>
          </div>
        </Card>

        <!-- 抽取模型配置 -->
        <Card class="overflow-hidden border-2 border-purple-500/20 shadow-sm">
          <button
            type="button"
            class="w-full border-b bg-gradient-to-r from-purple-500/10 to-purple-500/5 px-6 pb-3 pt-4 text-left"
            @click="llmOpen = !llmOpen"
          >
            <div class="flex items-center gap-2">
              <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/20 text-purple-500">
                <Cpu class="size-4" :stroke-width="2" />
              </div>
              <div class="flex-1">
                <CardTitle class="text-base font-semibold text-purple-600">抽取模型</CardTitle>
                <p class="text-xs text-muted-foreground">llm - 大语言模型配置与参数调优</p>
              </div>
              <ChevronDown class="size-4 text-muted-foreground transition-transform" :class="{ 'rotate-180': llmOpen }" :stroke-width="2" />
            </div>
          </button>
          <div v-show="llmOpen">
          <CardContent class="space-y-5 p-5">
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">引擎</Label>
                <Select
                  :model-value="globalConfig.llm?.engine"
                  :options="[
                    { value: 'BaseExtract', label: 'BaseExtract' },
                    { value: 'LangExtract', label: 'LangExtract' },
                  ]"
                  @update:model-value="(v: any) => (globalConfig.llm.engine = v)"
                  class="mt-1"
                />
                <p class="text-xs text-muted-foreground">选用 BaseExtract（直抽）或 LangExtract（结构化强约束）抽取引擎，切换后下方展示对应参数</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">温度 temperature</Label>
                <Input v-model.number="currentEngineParams.temperature" type="number" step="0.1" class="mt-1" />
                <p class="text-xs text-muted-foreground">采样温度，越低越确定；LangExtract 留空回退 BaseExtract 温度</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">top_p</Label>
                <Input v-model.number="currentEngineParams.top_p" type="number" step="0.01" class="mt-1" />
                <p class="text-xs text-muted-foreground">采样概率核，与 top_k 共同控制生成多样性</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">top_k</Label>
                <Input v-model.number="currentEngineParams.top_k" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">生成时保留的候选 token 数</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">max_tokens</Label>
                <Input v-model.number="currentEngineParams.max_tokens" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">单次 LLM 生成的最大 token 数，类别级可覆盖</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">超时 timeout (秒)</Label>
                <Input v-model.number="currentEngineParams.timeout" type="number" class="mt-1" />
                <p class="text-xs text-muted-foreground">单次 LLM 请求超时秒数，留空表示不设超时</p>
              </div>
            </div>

            <!-- 开关（当前引擎公用） -->
            <div class="grid gap-3 sm:grid-cols-3">
              <label class="flex flex-col gap-2 rounded-md bg-background/80 p-3 text-sm sm:col-span-1">
                <span class="flex items-center gap-2">
                  <Switch v-model="currentEngineParams.enable_thinking" />
                  <span class="font-medium">启用思考（enable_thinking）</span>
                </span>
                <span class="text-xs text-muted-foreground">关闭以适配 vLLM 结构化输出（Qwen 思考模式可能与 XGrammar 冲突）</span>
              </label>
            </div>

            <!-- 并发配置（当前引擎） -->
            <div class="rounded-lg border-2 border-purple-200/50 bg-purple-50/50 p-4 dark:bg-purple-950/20">
              <Label class="mb-3 block text-sm font-semibold text-purple-700 dark:text-purple-300">并发配置（{{ currentEngine }}）</Label>
              <div class="grid gap-3 sm:grid-cols-3">
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">总并发上限</Label>
                  <Input v-model.number="currentEngineParams.concurrency.max_concurrency" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">LLM 调用总并发上限，应匹配 vLLM --max-num-seqs</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">类别间并发</Label>
                  <Input v-model.number="currentEngineParams.concurrency.cross_category" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">类别间的调度并发（BaseExtract 填满队列；LangExtract 独立控制）</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">类别内并发</Label>
                  <Input v-model.number="currentEngineParams.concurrency.within_category" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">类别内并发（LangExtract 对应 max_workers）</p>
                </div>
              </div>
            </div>

            <!-- BaseExtract 批处理参数 -->
            <div v-if="currentEngine === 'BaseExtract'" class="rounded-lg border-2 border-purple-200/50 bg-purple-50/50 p-4 dark:bg-purple-950/20">
              <Label class="mb-3 block text-sm font-semibold text-purple-700 dark:text-purple-300">批处理参数（BaseExtract）</Label>
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">长文本阈值</Label>
                  <Input v-model.number="currentEngineParams.batch.single_threshold" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">上下文字符数超过该阈值即触发分批</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">单批字符</Label>
                  <Input v-model.number="currentEngineParams.batch.batch_chars" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">每批最大字符数，按表格边界切分</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">批间重叠 overlap</Label>
                  <Input v-model.number="currentEngineParams.batch.overlap" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">相邻批次间保留的重叠字符，避免上下文割裂</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">上下文截断</Label>
                  <Input v-model.number="currentEngineParams.batch.context_truncate" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">单次输入最大字符数，保护不超出模型上下文</p>
                </div>
              </div>
            </div>

            <!-- LangExtract 引擎专属参数 -->
            <div v-if="currentEngine === 'LangExtract'" class="rounded-lg border-2 border-purple-200/50 bg-purple-50/50 p-4 dark:bg-purple-950/20">
              <Label class="mb-3 block text-sm font-semibold text-purple-700 dark:text-purple-300">引擎专属参数（LangExtract）</Label>
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">抽取轮数 passes</Label>
                  <Input v-model.number="currentEngineParams.passes" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">抽取迭代轮数，多轮提升召回但更耗时</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">共指消解窗口(字符)</Label>
                  <Input v-model.number="currentEngineParams.context_window_chars" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">跨块共指消解的窗口字符数</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">单次输入字符上限</Label>
                  <Input v-model.number="currentEngineParams.max_char_buffer" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">单次送入 LLM 的最大字符数</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">few-shot 示例数</Label>
                  <Input v-model.number="currentEngineParams.max_examples" type="number" class="mt-1" />
                  <p class="text-xs text-muted-foreground">从 Schema 字段 example 生成的示例条数</p>
                </div>
                <div class="space-y-1 rounded-md bg-background/80 p-2">
                  <Label class="text-xs font-medium text-purple-600">输出格式 format_type</Label>
                  <Select
                    :model-value="currentEngineParams.format_type"
                    :options="[
                      { value: 'JSON', label: 'JSON' },
                      { value: 'YAML', label: 'YAML' },
                    ]"
                    @update:model-value="(v: any) => (currentEngineParams.format_type = v)"
                    class="mt-1"
                  />
                  <p class="text-xs text-muted-foreground">LLM 结构化输出格式（仅 LangExtract 生效）</p>
                </div>
                <label class="flex flex-col gap-2 rounded-md bg-background/80 p-3 text-sm">
                  <span class="flex items-center gap-2">
                    <Switch v-model="currentEngineParams.fence_output" />
                    <span class="font-medium">围栏输出 fence_output</span>
                  </span>
                  <span class="text-xs text-muted-foreground">在输出外层包裹围栏标记（仅 LangExtract 生效）</span>
                </label>
              </div>
            </div>
          </CardContent>
          </div>
        </Card>

        <!-- 脚本工具（kb_tool）配置 -->
        <Card class="overflow-hidden border-2 border-emerald-500/20 shadow-sm">
          <button
            type="button"
            class="w-full border-b bg-gradient-to-r from-emerald-500/10 to-emerald-500/5 px-6 pb-3 pt-4 text-left"
            @click="kbToolOpen = !kbToolOpen"
          >
            <div class="flex items-center gap-2">
              <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-500">
                <Wand2 class="size-4" :stroke-width="2" />
              </div>
              <div class="flex-1">
                <CardTitle class="text-base font-semibold text-emerald-600">脚本工具（kb_tool）</CardTitle>
                <p class="text-xs text-muted-foreground">kb_tool - 脚本可调用工具的性能参数</p>
              </div>
              <ChevronDown class="size-4 text-muted-foreground transition-transform" :class="{ 'rotate-180': kbToolOpen }" :stroke-width="2" />
            </div>
          </button>
          <div v-show="kbToolOpen">
          <CardContent class="space-y-5 p-5">
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">embed 分批次大小</Label>
                <Input v-model.number="globalConfig.kb_tool.embed_batch_size" type="number" min="1" class="mt-1" />
                <p class="text-xs text-muted-foreground">embed 向量化分批大小（默认 32）</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">检索/匹配并发上限</Label>
                <Input v-model.number="globalConfig.kb_tool.search_concurrency" type="number" min="1" class="mt-1" />
                <p class="text-xs text-muted-foreground">语义检索/匹配共享信号量（默认 10）</p>
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">semantic_search 默认 top_k</Label>
                <Input v-model.number="globalConfig.kb_tool.semantic_top_k" type="number" min="1" class="mt-1" />
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">match_record 内部检索 top_k</Label>
                <Input v-model.number="globalConfig.kb_tool.match_top_k" type="number" min="1" class="mt-1" />
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">match_record 匹配阈值</Label>
                <Input v-model.number="globalConfig.kb_tool.match_threshold" type="number" step="0.01" min="0" max="1" class="mt-1" />
              </div>
              <div class="space-y-1.5 rounded-lg bg-muted/30 p-3">
                <Label class="text-xs font-medium text-muted-foreground">脚本执行超时（秒）</Label>
                <Input v-model.number="globalConfig.kb_tool.script_timeout" type="number" min="1" class="mt-1" />
                <p class="text-xs text-muted-foreground">抽取后处理 / 校验脚本的单次执行超时上限（默认 10 秒），防止脚本卡死阻塞抽取</p>
              </div>
            </div>
            <p class="text-xs text-muted-foreground">
              仅影响脚本工具（embed / semantic_search / match_record）的耗时与吞吐，不影响抽取结果正确性；无脚本调用时不产生任何影响。
            </p>
          </CardContent>
          </div>
        </Card>

        </TabsContent>

      <!-- ============ Schema 模板 ============ -->
      <TabsContent value="schema">
        <div class="grid gap-4 lg:grid-cols-[260px_1fr]">
          <!-- 模板列表 -->
          <Card>
            <CardHeader class="pb-2">
              <div class="flex items-center justify-between">
                <CardTitle class="text-base">模板</CardTitle>
                <Button v-if="isEditor" variant="ghost" size="sm" title="新建模板" @click="openCreateTemplate">
                  <Plus class="size-4" :stroke-width="1.5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent class="space-y-1">
              <div v-if="templateLoading" class="space-y-2">
                <div v-for="i in 3" :key="i" class="h-10 animate-pulse rounded-md bg-muted" />
              </div>
              <EmptyState
                v-else-if="templates.length === 0"
                :icon="LayoutTemplate"
                title="暂无模板"
                description="创建 Schema 模板以定义抽取结构"
                class="py-8"
              />
              <button
                v-for="t in templates"
                :key="t.id"
                class="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
                :class="currentTemplate?.id === t.id ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground'"
                @click="selectTemplate(t.id)"
              >
                <span class="truncate">{{ t.name }}</span>
                <Badge v-if="!t.is_active" variant="secondary" class="text-[10px]">停用</Badge>
              </button>
            </CardContent>
          </Card>

          <!-- 模板详情 -->
          <Card>
            <CardHeader class="pb-2">
              <div class="flex items-center justify-between">
                <CardTitle class="text-base">{{ currentTemplate?.name || '请选择模板' }}</CardTitle>
                <div v-if="currentTemplate && isEditor" class="flex items-center gap-1">
                  <Button variant="outline" size="sm" @click="openCreateCategory">
                    <Plus class="size-4" :stroke-width="1.5" />
                    新建类别
                  </Button>
                  <Button variant="ghost" size="sm" title="删除模板" @click="deleteTemplate(currentTemplate)">
                    <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
                  </Button>
                </div>
              </div>
              <p v-if="currentTemplate?.description" class="text-xs text-muted-foreground">{{ currentTemplate.description }}</p>
            </CardHeader>
            <CardContent>
              <EmptyState
                v-if="currentTemplate && currentTemplate.categories.length === 0"
                :icon="FolderTree"
                title="暂无类别"
                description="添加类别以定义抽取目标（如：室温拉伸、化学成分）"
                class="py-12"
              />
              <div v-else class="space-y-3">
                <div v-for="cat in currentTemplate?.categories || []" :key="cat.id" class="rounded-lg border border-border">
                  <!-- 类别行 -->
                  <div class="flex items-center gap-3 p-3">
                    <button class="flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted" @click="toggleExpand(cat.id)">
                      <ChevronDown v-if="expandedCats.has(cat.id)" class="size-4" :stroke-width="1.5" />
                      <ChevronRight v-else class="size-4" :stroke-width="1.5" />
                    </button>
                    <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <FolderTree class="size-4" :stroke-width="1.5" />
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="flex flex-wrap items-center gap-2">
                        <p class="font-medium text-foreground">{{ categoryDisplayName(cat) }}</p>
                        <Badge variant="outline" class="text-[10px]">{{ cat.return_type }}</Badge>
                        <Badge variant="secondary" class="text-[10px]">{{ cat.extraction_strategy }}</Badge>
                        <Badge v-if="cat.name_source === 'term_base'" variant="secondary" class="bg-amber-500/10 text-amber-600 text-[10px]">使用术语库</Badge>
                        <Badge v-if="(cat.query_sources || []).some((s) => s.in_query)" variant="secondary" class="bg-amber-500/10 text-amber-600 text-[10px]">Query术语集({{ (cat.query_sources || []).filter((s) => s.in_query).length }})</Badge>
                        <Badge v-if="cat.top_k" variant="secondary" class="text-[10px]">top_k={{ cat.top_k }}</Badge>
                        <Badge v-if="!cat.is_active" variant="secondary" class="bg-danger/10 text-danger text-[10px]">停用</Badge>
                      </div>
                      <p v-if="cat.description" class="mt-0.5 truncate text-xs text-muted-foreground">{{ cat.description }}</p>
                    </div>
                    <div v-if="isEditor" class="flex shrink-0 items-center gap-1">
                      <Button variant="ghost" size="sm" title="添加字段" @click="openCreateField(cat)">
                        <Plus class="size-4" :stroke-width="1.5" />
                      </Button>
                      <Button variant="ghost" size="sm" title="编辑" @click="openEditCategory(cat)">
                        <Pencil class="size-4" :stroke-width="1.5" />
                      </Button>
                      <Button variant="ghost" size="sm" title="删除" @click="deleteCategory(cat)">
                        <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
                      </Button>
                    </div>
                  </div>

                  <!-- 字段列表 -->
                  <div v-if="expandedCats.has(cat.id)" class="space-y-2 border-t border-border p-3">
                    <EmptyState
                      v-if="cat.fields.length === 0"
                      :icon="FileBox"
                      title="暂无字段"
                      description="添加字段以定义抽取项"
                      class="py-6"
                    />
                    <div v-for="field in cat.fields" :key="field.id" class="flex items-center gap-3 rounded-md bg-muted/40 p-2.5">
                      <div class="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                        <FileBox class="size-4" :stroke-width="1.5" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2">
                          <p class="text-sm font-medium text-foreground">{{ field.name }}</p>
                          <Badge variant="outline" class="text-[10px]">{{ field.type }}</Badge>
                          <Badge v-if="field.required" variant="secondary" class="text-[10px]">必填</Badge>
                        </div>
                        <p v-if="field.description" class="mt-0.5 truncate text-xs text-muted-foreground">{{ field.description }}</p>
                      </div>
                      <div v-if="isEditor" class="flex shrink-0 items-center gap-1">
                        <Button variant="ghost" size="sm" title="编辑" @click="openEditField(cat, field)">
                          <Pencil class="size-3.5" :stroke-width="1.5" />
                        </Button>
                        <Button variant="ghost" size="sm" title="删除" @click="deleteField(cat, field)">
                          <Trash2 class="size-3.5 text-danger" :stroke-width="1.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </TabsContent>

      <!-- ============ Prompt 模板 ============ -->
      <TabsContent value="prompt">
        <Card>
          <CardHeader>
            <div class="flex items-center justify-between">
              <CardTitle class="text-base">Prompt 模板</CardTitle>
              <Button v-if="isEditor" size="sm" @click="openCreatePrompt">
                <Plus class="size-4" :stroke-width="1.5" />
                新建模板
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div v-if="promptLoading" class="grid gap-3 sm:grid-cols-2">
              <div v-for="i in 4" :key="i" class="h-28 animate-pulse rounded-md bg-muted" />
            </div>
            <EmptyState
              v-else-if="prompts.length === 0"
              :icon="FileText"
              title="暂无 Prompt 模板"
              description="创建 Prompt 模板以控制模型抽取行为"
              class="py-12"
            />
            <div v-else class="grid gap-3 sm:grid-cols-2">
              <Card v-for="p in prompts" :key="p.id" class="bg-muted/20">
                <CardContent class="p-4">
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                      <p class="font-medium text-foreground">{{ p.name }}</p>
                      <Badge variant="outline" class="text-[10px]">{{ p.scope === 'schema' ? 'Schema' : '简单' }}</Badge>
                    </div>
                    <div v-if="isEditor" class="flex items-center gap-1">
                      <Button variant="ghost" size="sm" title="编辑" @click="openEditPrompt(p)">
                        <Pencil class="size-4" :stroke-width="1.5" />
                      </Button>
                      <Button variant="ghost" size="sm" title="删除" @click="deletePrompt(p)">
                        <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
                      </Button>
                    </div>
                  </div>
                  <p class="mt-1 line-clamp-2 text-xs text-muted-foreground">{{ p.description || '暂无描述' }}</p>
                  <p class="mt-2 line-clamp-3 rounded-md bg-muted p-2 font-mono text-xs">{{ p.system_prompt || p.user_prompt }}</p>
                </CardContent>
              </Card>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============ 后处理与校验规则（按 Schema 模板分组） ============ -->
      <TabsContent value="rules">
        <Card>
          <CardHeader>
            <div class="flex items-center justify-between">
              <CardTitle class="text-base">后处理与校验规则</CardTitle>
              <Button v-if="isEditor" variant="outline" size="sm" @click="openCreateGroup">
                <Plus class="size-4" :stroke-width="1.5" />
                新建规则组
              </Button>
            </div>
          </CardHeader>
          <CardContent class="space-y-4">
            <div v-if="ruleGroupsLoading" class="space-y-2">
              <div v-for="i in 3" :key="i" class="h-14 animate-pulse rounded-md bg-muted" />
            </div>
            <EmptyState
              v-else-if="ruleGroups.length === 0"
              :icon="ListChecks"
              title="暂无规则组"
              description="新建规则组并绑定 Schema 模板，然后按类别配置后处理与校验脚本规则"
              class="py-12"
            />
            <div v-else class="space-y-3">
              <!-- 规则组列表 -->
              <div
                v-for="g in ruleGroups"
                :key="g.id"
                class="overflow-hidden rounded-xl border border-border bg-card shadow-sm transition-all duration-200 hover:shadow-md"
              >
                <!-- 顶部渐变条 -->
                <div class="h-1 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent" />
                <div class="flex items-center justify-between gap-3 p-3.5">
                  <div class="flex min-w-0 flex-1 cursor-pointer items-start gap-3" @click="toggleGroup(g.id)">
                    <div class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <FolderTree class="size-4" :stroke-width="1.5" />
                    </div>
                    <div class="min-w-0">
                      <div class="flex items-center gap-2">
                        <ChevronDown v-if="expandedGroups.has(g.id)" class="size-3.5 shrink-0 text-muted-foreground" :stroke-width="2" />
                        <ChevronRight v-else class="size-3.5 shrink-0 text-muted-foreground" :stroke-width="2" />
                        <p class="truncate font-semibold text-foreground">{{ g.name }}</p>
                        <Badge variant="secondary" class="shrink-0 text-[10px]">{{ g.category_count }} 类别</Badge>
                        <Badge variant="outline" class="shrink-0 text-[10px]">{{ g.item_count }} 规则</Badge>
                      </div>
                      <p class="mt-1 truncate text-xs text-muted-foreground">
                        <span class="inline-flex items-center gap-1">
                          <LayoutTemplate class="size-3" :stroke-width="1.5" />
                          {{ g.schema_template_name }}
                        </span>
                        <template v-if="g.description"> · {{ g.description }}</template>
                      </p>
                    </div>
                  </div>
                  <Button v-if="isEditor" variant="ghost" size="icon" class="size-8 shrink-0 text-muted-foreground hover:text-destructive" @click="deleteGroup(g)">
                    <Trash2 class="size-4" :stroke-width="1.5" />
                  </Button>
                </div>

                <!-- 规则组展开：类别列表 -->
                <div v-if="expandedGroups.has(g.id)" class="space-y-2 border-t border-border/70 bg-muted/20 p-3">
                  <template v-if="!g.loaded">
                    <div class="space-y-2">
                      <div v-for="i in 2" :key="i" class="h-10 animate-pulse rounded-md bg-muted" />
                    </div>
                  </template>
                  <template v-else-if="g.categories && g.categories.length === 0">
                    <div class="flex flex-col items-center gap-1.5 py-6 text-muted-foreground">
                      <FileBox class="size-6" :stroke-width="1.5" />
                      <p class="text-xs">该模板下暂无类别</p>
                    </div>
                  </template>
                  <template v-else>
                    <div
                      v-for="cat in g.categories"
                      :key="cat.id"
                      class="overflow-hidden rounded-lg border border-border transition-shadow hover:shadow-sm"
                    >
                      <!-- 类别行（对齐 Schema 模板右侧类别风格，点击整行展开/收起） -->
                      <div class="flex cursor-pointer items-center gap-3 p-3 transition-colors hover:bg-primary/5" @click="toggleCategory(g.id, cat.id)">
                        <div class="flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground">
                          <ChevronDown v-if="expandedCategories.has(`${g.id}:${cat.id}`)" class="size-4" :stroke-width="1.5" />
                          <ChevronRight v-else class="size-4" :stroke-width="1.5" />
                        </div>
                        <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                          <FolderTree class="size-4" :stroke-width="1.5" />
                        </div>
                        <div class="min-w-0 flex-1">
                          <div class="flex flex-wrap items-center gap-2">
                            <p class="font-medium text-foreground">{{ cat.name }}</p>
                            <Badge variant="secondary" class="text-[10px]">{{ (cat.rules || []).length }} 规则</Badge>
                          </div>
                          <p v-if="(cat.rules || []).length" class="mt-0.5 truncate text-xs text-muted-foreground">
                            {{ summarizeStages(cat) }}
                          </p>
                        </div>
                        <Button v-if="isEditor" variant="ghost" size="sm" title="添加规则" @click.stop="openAddRule(g.id, cat)">
                          <Plus class="size-4" :stroke-width="1.5" />
                        </Button>
                      </div>

                      <!-- 类别展开：单栏规则列表（后处理与校验交叉排序，对齐 Schema 字段行风格） -->
                      <div v-if="expandedCategories.has(`${g.id}:${cat.id}`)" class="space-y-2 border-t border-border bg-muted/20 p-3">
                        <div v-if="(cat.rules || []).length === 0" class="py-4 text-center text-xs text-muted-foreground">
                          暂无规则，点击右侧「＋」或下方「添加规则」
                        </div>
                        <div
                          v-for="(rule, ri) in cat.rules"
                          :key="ri"
                          draggable="true"
                          class="group flex items-center gap-3 rounded-md bg-white/60 p-2.5 transition-colors hover:bg-primary/5 dark:bg-muted/40 active:cursor-grabbing"
                          @dragstart="onRuleDragStart(rule)"
                          @dragover="onRuleDragOver"
                          @drop="onRuleDrop(g, cat, rule)"
                        >
                          <span class="cursor-grab text-lg leading-none text-muted-foreground/40">⋮⋮</span>
                          <div
                            class="flex size-8 shrink-0 items-center justify-center rounded-md"
                            :class="rule.stage === 'post' ? 'bg-primary/10 text-primary' : 'bg-warning/15 text-warning'"
                            :title="rule.stage === 'post' ? '后处理' : '校验'"
                          >
                            <Wand2 v-if="rule.stage === 'post'" class="size-4" :stroke-width="1.5" />
                            <ShieldCheck v-else class="size-4" :stroke-width="1.5" />
                          </div>
                          <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-2">
                              <p class="truncate text-sm font-medium text-foreground">{{ rule.script_name || '未命名脚本' }}</p>
                              <Badge :variant="rule.stage === 'post' ? 'default' : 'outline'" class="shrink-0 text-[10px]">
                                {{ rule.stage === 'post' ? '后处理' : '校验' }}
                              </Badge>
                            </div>
                            <p v-if="rule.script_description" class="mt-0.5 truncate text-xs text-muted-foreground">{{ rule.script_description }}</p>
                          </div>
                          <div class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                            <Button variant="ghost" size="icon" class="size-7 text-muted-foreground hover:text-foreground" title="上移" :disabled="ri === 0" @click.prevent="moveRule(g, cat, rule, -1)">
                              <ChevronUp class="size-3.5" :stroke-width="2" />
                            </Button>
                            <Button variant="ghost" size="icon" class="size-7 text-muted-foreground hover:text-foreground" title="下移" :disabled="ri === cat.rules.length - 1" @click.prevent="moveRule(g, cat, rule, 1)">
                              <ChevronDown class="size-3.5" :stroke-width="2" />
                            </Button>
                            <Button v-if="isEditor" variant="ghost" size="icon" class="size-7 text-muted-foreground hover:text-destructive" title="移除" @click.prevent="removeItem(g, cat, rule)">
                              <Trash2 class="size-3.5" :stroke-width="1.75" />
                            </Button>
                          </div>
                        </div>
                        <Button v-if="isEditor" variant="outline" size="sm" class="w-full border-dashed hover:bg-primary/5" @click="openAddRule(g.id, cat)">
                          <Plus class="size-4" :stroke-width="1.5" />
                          添加规则
                        </Button>
                      </div>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============ 版本管理 ============ -->
      <TabsContent value="versions">
        <Card>
          <CardHeader>
            <div class="flex items-center justify-between">
              <CardTitle class="text-base">版本快照</CardTitle>
              <Button v-if="isEditor" size="sm" @click="openCreateVersion">
                <Plus class="size-4" :stroke-width="1.5" />
                创建快照
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div v-if="versionLoading" class="space-y-2">
              <div v-for="i in 3" :key="i" class="h-14 animate-pulse rounded-md bg-muted" />
            </div>
            <EmptyState
              v-else-if="versions.length === 0"
              :icon="History"
              title="暂无版本快照"
              description="创建快照以支持配置回滚与复用"
              class="py-12"
            />
            <div v-else class="space-y-2">
              <div v-for="v in versions" :key="v.id" class="flex items-center gap-3 rounded-lg border border-border p-3">
                <Badge variant="secondary" class="shrink-0">v{{ v.version }}</Badge>
                <div class="min-w-0 flex-1">
                  <p class="font-medium text-foreground">{{ v.name }}</p>
                  <p class="mt-0.5 text-xs text-muted-foreground">{{ v.description || '—' }} · {{ formatTime(v.created_at) }}</p>
                </div>
                <Button variant="ghost" size="sm" @click="openVersionDetail(v)">
                  <FileText class="size-4" :stroke-width="1.5" />
                  详情
                </Button>
                <Button variant="ghost" size="sm" @click="openVersionDiff(v)">
                  <GitCompareArrows class="size-4" :stroke-width="1.5" />
                  对比
                </Button>
                <Button v-if="isEditor" variant="outline" size="sm" @click="openRollbackConfirm(v)">
                  <History class="size-4" :stroke-width="1.5" />
                  回滚
                </Button>
                <Button v-if="isEditor" variant="ghost" size="sm" class="text-destructive hover:text-destructive" @click="deleteVersion(v)">
                  <Trash2 class="size-4" :stroke-width="1.5" />
                  删除
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============ 脚本管理 ============ -->
      <TabsContent value="scripts">
        <ScriptManager />
      </TabsContent>

    </Tabs>

    <!-- 新建模板对话框 -->
    <Dialog :open="tplDialogOpen" title="新建 Schema 模板" @update:open="(v: boolean) => (tplDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>模板名称 *</Label>
          <Input v-model="tplForm.name" placeholder="如：材料检测抽取模板" />
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Textarea v-model="tplForm.description" placeholder="模板用途说明" :rows="2" />
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="tplDialogOpen = false">取消</Button>
        <Button :disabled="tplSubmitting" @click="submitTemplate">
          <Loader2 v-if="tplSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          创建
        </Button>
      </div>
    </Dialog>

    <!-- 类别对话框 -->
    <Dialog :open="catDialogOpen" :title="catEditMode ? '编辑类别' : '新建类别'" content-class="max-h-[85vh] overflow-y-auto" @update:open="(v: boolean) => (catDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>类别名称来源</Label>
          <Select
            v-model="catForm.name_source"
            :options="[
              { value: 'manual', label: '手动输入' },
              { value: 'term_base', label: '术语集' },
            ]"
          />
        </div>
        <div v-if="catForm.name_source === 'manual'" class="space-y-1.5">
          <Label>类别名称 *</Label>
          <Input v-model="catForm.name" placeholder="如：室温拉伸" />
        </div>
        <div v-else-if="catForm.name_source === 'term_base'" class="space-y-1.5">
          <Label>名称来源术语集 *（选择后按该字段值循环生成类别）</Label>
          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-1.5">
              <Label class="text-xs text-muted-foreground">术语集</Label>
              <Select
                v-model="catForm.name_term_base_id"
                :options="termBases.map((b) => ({ value: b.id, label: b.name }))"
                placeholder="选择术语集"
                :disabled="termBaseLoading"
              />
            </div>
            <div class="space-y-1.5">
              <Label class="text-xs text-muted-foreground">取值字段</Label>
              <Select
                v-model="catForm.name_term_field"
                :options="nameTermFields.map((c) => ({ value: c.name, label: c.label || c.name }))"
                placeholder="选择字段"
                :disabled="!catForm.name_term_base_id"
              />
            </div>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Textarea v-model="catForm.description" placeholder="类别用途说明" :rows="2" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <Label>返回类型</Label>
            <Select
              v-model="catForm.return_type"
              :options="[
                { value: 'array', label: '数组' },
                { value: 'object', label: '对象' },
              ]"
            />
          </div>
          <div class="space-y-1.5">
            <Label>抽取策略</Label>
            <Select
              v-model="catForm.extraction_strategy"
              :options="[
                { value: 'auto', label: 'auto（按置信度）' },
                { value: 'always', label: 'always（强制抽取）' },
                { value: 'never', label: 'never（不抽取）' },
              ]"
            />
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>固定 Query 文本</Label>
          <Input v-model="catForm.fixed_query" placeholder="如：标准名称 标准编号 文件编号" />
        </div>

        <!-- Query 关联（参与 query 的术语集） -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <Label>Query 关联（挂载到 Query 的术语集）</Label>
          </div>
          <EmptyState
            v-if="catForm.query_sources.filter((s) => s.in_query).length === 0"
            :icon="BookMarked"
            title="暂无参与 Query 的术语集"
            description="在下方术语集中开启参与 Query 后，将在此展示"
            class="py-4"
          />
          <div
            v-for="(qs, idx) in catForm.query_sources.filter((s) => s.in_query)"
            :key="idx"
            class="rounded-lg border border-border bg-muted/30 p-3"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="flex items-center gap-2">
                <span class="text-amber-500">#</span>
                <p class="text-sm font-medium text-foreground">{{ qs.label || '未命名术语集' }}</p>
              </div>
              <div class="flex flex-wrap items-center gap-3">
                <label class="flex items-center gap-1.5 text-xs text-muted-foreground">
                  主查询上限
                  <Input v-model.number="qs.query_main_limit" type="number" min="1" class="h-7 w-14" />
                </label>
                <label class="flex items-center gap-1.5 text-xs text-muted-foreground">
                  精简上限
                  <Input v-model.number="qs.query_refined_limit" type="number" min="1" class="h-7 w-14" />
                </label>
                <label class="flex items-center gap-1.5 text-xs text-muted-foreground">
                  精简
                  <Switch v-model="qs.dedupe" />
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  title="取消与 Query 的关联（术语集保留）"
                  @click="qs.in_query = false"
                >
                  <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
                </Button>
              </div>
            </div>
          </div>
        </div>

        <!-- 术语集（可添加多个） -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <Label>术语集</Label>
            <Button v-if="isEditor" variant="outline" size="sm" @click="addQuerySource">
              <Plus class="size-4" :stroke-width="1.5" />
              添加术语集
            </Button>
          </div>
          <EmptyState
            v-if="catForm.query_sources.length === 0"
            :icon="BookMarked"
            title="暂无术语集"
            description="添加术语集用于构造动态 Query"
            class="py-4"
          />
          <template v-for="(qs, idx) in catForm.query_sources" :key="idx">
            <!-- 折叠态：仅显示名称，点击展开查看设置 -->
            <button
              v-if="!expandedPool.has(idx)"
              type="button"
              class="flex w-full items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:bg-muted/40"
              @click="toggleExpandPool(idx)"
            >
              <span class="flex min-w-0 items-center gap-2">
                <ChevronRight class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
                <span class="truncate text-sm font-medium text-foreground">{{ qs.label || '未命名术语集' }}</span>
              </span>
              <span class="flex shrink-0 items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  title="移除"
                  @click.stop="removeQuerySource(idx)"
                >
                  <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
                </Button>
              </span>
            </button>
            <!-- 展开态：完整设置 + 保存 -->
            <div
              v-else
              class="rounded-lg border border-border p-3"
            >
              <div class="mb-2 flex items-center justify-between">
                <button type="button" class="flex items-center gap-1.5" @click="toggleExpandPool(idx)">
                  <ChevronDown class="size-4 text-muted-foreground" :stroke-width="1.5" />
                  <p class="text-sm font-medium text-foreground">术语集 {{ idx + 1 }}</p>
                </button>
                <Button variant="ghost" size="sm" title="移除" @click="removeQuerySource(idx)">
                  <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
                </Button>
              </div>
              <div class="space-y-2">
                <div class="space-y-1.5">
                  <Label class="text-xs text-muted-foreground">术语集名称 *</Label>
                  <Input v-model="qs.label" placeholder="该术语集的显示名称（必填）" />
                </div>
                <div class="space-y-1.5">
                  <Label class="text-xs text-muted-foreground">术语集 *</Label>
                  <Select
                    v-model="qs.term_base_id"
                    :options="termBases.map((b) => ({ value: b.id, label: b.name }))"
                    placeholder="选择术语集"
                  />
                </div>
                <div class="grid grid-cols-2 gap-3">
                  <div class="space-y-1.5">
                    <Label class="text-xs text-muted-foreground">分组字段（可选）</Label>
                    <Select
                      v-model="qs.group_field"
                      :options="fieldsOfTermBase(qs.term_base_id).map((c) => ({ value: c.name, label: c.label || c.name }))"
                      placeholder="选择分组字段"
                      :disabled="!qs.term_base_id"
                    />
                  </div>
                  <div class="space-y-1.5">
                    <Label class="text-xs text-muted-foreground">值字段 *</Label>
                    <Select
                      v-model="qs.value_field"
                      :options="fieldsOfTermBase(qs.term_base_id).map((c) => ({ value: c.name, label: c.label || c.name }))"
                      placeholder="选择值字段"
                      :disabled="!qs.term_base_id"
                    />
                  </div>
                </div>
                <label class="flex items-center gap-2 text-sm">
                  <Switch v-model="qs.in_query" />
                  参与 Query（开启后挂载到 Query 下方）
                </label>
              </div>
              <div class="mt-3 flex justify-end">
                <Button type="button" variant="default" size="sm" @click="saveQuerySource(idx)">保存</Button>
              </div>
            </div>
          </template>
        </div>
        <div v-if="catForm.extraction_strategy === 'auto'" class="space-y-1.5">
          <Label>置信度阈值（覆盖全局）</Label>
          <Input v-model.number="catForm.confidence_threshold" type="number" step="0.05" placeholder="留空使用全局默认" />
        </div>
        <div class="space-y-1.5">
          <Label>检索 top_k（覆盖全局）</Label>
          <Input v-model.number="catForm.top_k" type="number" placeholder="留空使用全局默认" />
        </div>
        <div class="space-y-1.5">
          <Label>重排序 top_k（覆盖全局）</Label>
          <Input v-model.number="catForm.rerank_top_k" type="number" placeholder="留空使用全局默认" />
        </div>
        <div class="space-y-1.5">
          <Label>最大输出 token（覆盖全局）</Label>
          <Input v-model.number="catForm.max_tokens" type="number" placeholder="留空使用全局默认" />
        </div>
        <label class="flex items-center gap-2 text-sm">
          <Switch v-model="catForm.is_active" />
          启用（参与抽取）
        </label>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="catDialogOpen = false">取消</Button>
        <Button :disabled="catSubmitting" @click="submitCategory">
          <Loader2 v-if="catSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ catEditMode ? '保存' : '创建' }}
        </Button>
      </div>
    </Dialog>

    <!-- 字段对话框 -->
    <Dialog :open="fieldDialogOpen" :title="fieldEditMode ? '编辑字段' : '新建字段'" @update:open="(v: boolean) => (fieldDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>字段名称 *</Label>
          <Input v-model="fieldForm.name" placeholder="如：项目名称" />
        </div>
        <div class="space-y-1.5">
          <Label>字段类型</Label>
          <Select
            v-model="fieldForm.type"
            :options="[
              { value: 'string', label: 'string' },
              { value: 'number', label: 'number' },
              { value: 'boolean', label: 'boolean' },
              { value: 'array', label: 'array' },
            ]"
          />
        </div>
        <div class="space-y-1.5">
          <Label>字段说明（提升抽取精度）</Label>
          <Textarea v-model="fieldForm.description" placeholder="说明该字段含义与抽取规则" :rows="2" />
        </div>
        <div class="space-y-1.5">
          <Label>示例（提升抽取精度）</Label>
          <Input v-model="fieldForm.example" placeholder="如：抗拉强度 Rm" />
        </div>
        <label class="flex items-center gap-2 text-sm">
          <Switch v-model="fieldForm.required" />
          必填
        </label>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="fieldDialogOpen = false">取消</Button>
        <Button :disabled="fieldSubmitting" @click="submitField">
          <Loader2 v-if="fieldSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ fieldEditMode ? '保存' : '创建' }}
        </Button>
      </div>
    </Dialog>

    <!-- Prompt 模板对话框（新建） -->
    <Dialog :open="promptDialogOpen" title="新建 Prompt 模板" @update:open="(v: boolean) => (promptDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>模板名称 *</Label>
          <Input v-model="promptForm.name" placeholder="如：材料检测抽取 Prompt" />
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Input v-model="promptForm.description" placeholder="模板用途说明" />
        </div>
        <div class="space-y-1.5">
          <Label>绑定 Schema 模板（可选）</Label>
          <Select
            v-model="promptForm.scope"
            :options="[
              { value: 'simple', label: '不绑定（单个 user 提示词）' },
              { value: 'schema', label: '绑定 Schema（按类别拆分 user 提示词）' },
            ]"
          />
        </div>
        <template v-if="promptForm.scope === 'schema'">
          <div class="space-y-1.5">
            <Label>选择 Schema 模板 *</Label>
            <Select
              v-model="promptForm.schema_template_id"
              :options="promptSchemaTemplates.map((t) => ({ value: t.id, label: t.name }))"
              placeholder="请选择 Schema 模板"
            />
          </div>
          <div v-if="promptSchemaCats.length > 0" class="space-y-1.5">
            <Label>选择类别（默认全选）</Label>
            <div class="max-h-40 space-y-1 overflow-y-auto rounded-md border p-2">
              <label
                v-for="cat in promptSchemaCats"
                :key="cat.id"
                class="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-muted"
              >
                <input
                  type="checkbox"
                  class="size-4"
                  :checked="promptForm.category_ids.includes(cat.id)"
                  @change="togglePromptCat(cat.id)"
                />
                {{ categoryDisplayName(cat) }}
                <Badge v-if="(cat as any).name_source === 'term_base'" variant="secondary" class="bg-amber-500/10 text-amber-600 text-[10px]">术语库</Badge>
              </label>
            </div>
          </div>
        </template>
        <label class="flex items-center gap-2 text-sm">
          <Switch v-model="promptForm.is_active" />
          启用
        </label>
        <p class="text-xs text-muted-foreground">创建后进入编辑页，可配置 system / user 提示词并使用 ${字段名} 占位符。</p>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="promptDialogOpen = false">取消</Button>
        <Button :disabled="promptSubmitting" @click="submitPrompt">
          <Loader2 v-if="promptSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          创建
        </Button>
      </div>
    </Dialog>

    <!-- 新建规则组对话框 -->
    <Dialog :open="groupDialogOpen" title="新建规则组" description="按 Schema 模板分组，为各类别统一配置后处理与校验脚本规则" @update:open="(v: boolean) => (groupDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>规则组名称（可不填，默认取 Schema 模板名）</Label>
          <Input v-model="groupForm.name" placeholder="如：材料检测规则组" />
        </div>
        <div class="space-y-1.5">
          <Label>Schema 模板 *</Label>
          <Select
            :model-value="groupForm.schema_template_id"
            :options="templates.map((t) => ({ value: t.id, label: t.name }))"
            placeholder="选择 Schema 模板"
            @update:model-value="(v: any) => (groupForm.schema_template_id = v)"
          />
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Textarea v-model="groupForm.description" placeholder="规则组用途说明" :rows="2" />
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="groupDialogOpen = false">取消</Button>
        <Button :disabled="groupSubmitting" @click="submitGroup">
          <Loader2 v-if="groupSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          创建
        </Button>
      </div>
    </Dialog>

    <!-- 添加规则对话框（先选阶段，脚本仅显示该阶段） -->
    <Dialog :open="addRuleDialogOpen" title="添加规则" description="先选择阶段，脚本列表仅展示该阶段目录下已启用的脚本" @update:open="(v: boolean) => (addRuleDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>阶段 *</Label>
          <Select
            :model-value="addRuleForm.stage"
            :options="[
              { value: 'post', label: '后处理' },
              { value: 'validation', label: '校验' },
            ]"
            @update:model-value="(v: any) => {
              addRuleForm.stage = v
              addRuleForm.script_id = ''
            }"
          />
        </div>
        <div class="space-y-1.5">
          <Label>选择脚本 *（{{ addRuleForm.stage === 'post' ? '抽取后处理' : '校验' }}目录）</Label>
          <Select
            :model-value="addRuleForm.script_id"
            :options="addRuleScripts.map((s) => ({ value: s.id, label: s.name }))"
            placeholder="选择脚本"
            @update:model-value="(v: any) => (addRuleForm.script_id = v)"
          />
          <p v-if="addRuleScripts.length === 0" class="text-xs text-warning">
            该阶段暂无启用脚本，请先在「脚本管理」中创建
          </p>
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="addRuleDialogOpen = false">取消</Button>
        <Button :disabled="addRuleSubmitting || !addRuleForm.script_id" @click="submitAddRule">
          <Loader2 v-if="addRuleSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          添加
        </Button>
      </div>
    </Dialog>

    <!-- 版本快照对话框 -->
    <Dialog :open="versionDialogOpen" title="创建版本快照" @update:open="(v: boolean) => (versionDialogOpen = v)">
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>版本名称 *</Label>
          <Input v-model="versionForm.name" placeholder="如：材料检测 v1 基线" />
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Textarea v-model="versionForm.description" placeholder="版本说明" :rows="2" />
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="versionDialogOpen = false">取消</Button>
        <Button :disabled="versionSubmitting" @click="submitVersion">
          <Loader2 v-if="versionSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          创建
        </Button>
      </div>
    </Dialog>

    <!-- 版本详情对话框 -->
    <Dialog :open="detailDialogOpen" :title="detailData ? `版本详情 · ${String(detailData.name || '')} (v${Number(detailData.version)})` : '版本详情'" @update:open="(v: boolean) => (detailDialogOpen = v)">
      <div v-if="detailLoading" class="space-y-2 py-4">
        <div v-for="i in 4" :key="i" class="h-8 animate-pulse rounded-md bg-muted" />
      </div>
      <template v-else-if="detailData">
        <p v-if="detailData.description" class="mb-3 text-sm text-muted-foreground">{{ detailData.description }}</p>
        <div class="space-y-3">
          <div class="rounded-lg border border-border p-3">
            <p class="mb-2 text-xs font-medium text-muted-foreground">全局配置</p>
            <p class="text-sm text-foreground">{{ detailData.summary?.global ? '已启用' : '未配置' }}</p>
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div class="rounded-lg border border-border p-3">
              <p class="mb-2 text-xs font-medium text-muted-foreground">Schema 模板</p>
              <p v-if="detailData.summary?.schema_templates?.length" class="text-sm text-foreground">{{ detailData.summary.schema_templates.length }} 个：{{ detailData.summary.schema_templates.map((t: any) => t.name).join('、') }}</p>
              <p v-else class="text-sm text-muted-foreground">无</p>
            </div>
            <div class="rounded-lg border border-border p-3">
              <p class="mb-2 text-xs font-medium text-muted-foreground">Prompt 模板</p>
              <p v-if="detailData.summary?.prompt_templates?.length" class="text-sm text-foreground">{{ detailData.summary.prompt_templates.length }} 个：{{ detailData.summary.prompt_templates.map((p: any) => p.name).join('、') }}</p>
              <p v-else class="text-sm text-muted-foreground">无</p>
            </div>
            <div class="rounded-lg border border-border p-3">
              <p class="mb-2 text-xs font-medium text-muted-foreground">处理脚本</p>
              <p v-if="detailData.summary?.scripts?.length" class="text-sm text-foreground">{{ detailData.summary.scripts.length }} 个：{{ detailData.summary.scripts.join('、') }}</p>
              <p v-else class="text-sm text-muted-foreground">无</p>
            </div>
            <div class="rounded-lg border border-border p-3">
              <p class="mb-2 text-xs font-medium text-muted-foreground">数据集</p>
              <p v-if="detailData.summary?.datasets?.length" class="text-sm text-foreground">{{ detailData.summary.datasets.length }} 个：{{ detailData.summary.datasets.join('、') }}</p>
              <p v-else class="text-sm text-muted-foreground">无</p>
            </div>
            <div class="rounded-lg border border-border p-3">
              <p class="mb-2 text-xs font-medium text-muted-foreground">规则</p>
              <p v-if="detailData.summary?.rules?.length" class="text-sm text-foreground">{{ detailData.summary.rules.length }} 条：{{ detailData.summary.rules.join('、') }}</p>
              <p v-else class="text-sm text-muted-foreground">无</p>
            </div>
            <div class="rounded-lg border border-border p-3">
              <p class="mb-2 text-xs font-medium text-muted-foreground">规则组</p>
              <p v-if="detailData.summary?.rule_groups?.length" class="text-sm text-foreground">{{ detailData.summary.rule_groups.length }} 个：{{ detailData.summary.rule_groups.map((g: any) => g.name).join('、') }}</p>
              <p v-else class="text-sm text-muted-foreground">无</p>
            </div>
          </div>
          <div class="rounded-lg border border-border p-3">
            <p class="mb-2 text-xs font-medium text-muted-foreground">术语绑定</p>
            <p class="text-sm text-foreground">{{ detailData.summary?.term_bindings || 0 }} 条</p>
          </div>
        </div>
      </template>
      <div class="mt-6 flex justify-end">
        <Button variant="outline" @click="detailDialogOpen = false">关闭</Button>
      </div>
    </Dialog>

    <!-- 版本对比对话框 -->
    <Dialog :open="diffDialogOpen" :title="diffData ? `对比 · ${String(diffData.name || '')} (v${Number(diffData.version)})` : '版本对比'" @update:open="(v: boolean) => (diffDialogOpen = v)">
      <div v-if="diffLoading" class="space-y-2 py-4">
        <div v-for="i in 4" :key="i" class="h-8 animate-pulse rounded-md bg-muted" />
      </div>
      <template v-else-if="diffData">
        <p class="mb-3 text-sm text-muted-foreground">「当前配置」与「该版本」的差异对比。</p>
        <div v-if="diffData.diff?.changed === false" class="rounded-lg border border-emerald-300/50 bg-emerald-50/50 p-3 text-sm text-emerald-700 dark:text-emerald-300">
          当前配置与该版本完全一致，无差异。
        </div>
        <div v-else class="space-y-3">
          <div v-for="(d, key) in diffData.diff?.domains" :key="key" class="rounded-lg border border-border p-3">
            <p class="mb-2 text-sm font-medium text-foreground">{{ (d as any).label }} <span class="text-xs font-normal text-muted-foreground">(新增 {{ (d as any).added.length }} · 删除 {{ (d as any).removed.length }} · 修改 {{ (d as any).modified.length }})</span></p>
            <div v-if="(d as any).added.length" class="mb-1 flex flex-wrap gap-1.5">
              <Badge v-for="name in (d as any).added" :key="'a' + name" variant="default" class="text-[10px]">＋ {{ name }}</Badge>
            </div>
            <div v-if="(d as any).removed.length" class="mb-1 flex flex-wrap gap-1.5">
              <Badge v-for="name in (d as any).removed" :key="'r' + name" variant="destructive" class="text-[10px]">－ {{ name }}</Badge>
            </div>
            <div v-if="(d as any).modified.length" class="flex flex-wrap gap-1.5">
              <Badge v-for="name in (d as any).modified" :key="'m' + name" variant="outline" class="text-[10px]">* {{ name }}</Badge>
            </div>
          </div>
        </div>
      </template>
      <div class="mt-6 flex justify-end">
        <Button variant="outline" @click="diffDialogOpen = false">关闭</Button>
      </div>
    </Dialog>

    <!-- 回滚确认预警对话框 -->
    <Dialog :open="rollbackConfirmOpen" :title="rollbackTarget ? `回滚到 ${rollbackTarget.name} (v${rollbackTarget.version})` : '回滚确认'" @update:open="(v: boolean) => (rollbackConfirmOpen = v)">
      <div class="space-y-4">
        <div class="rounded-lg border border-amber-300/40 bg-amber-50/50 p-3 text-sm text-amber-700 dark:text-amber-300">
          回滚将<strong>全量覆盖</strong>当前抽取配置（全局 / 脚本 / 数据集 / Schema 模板 / 术语绑定 / Prompt 模板 / 规则 / 规则组）为该版本保存时的状态，此操作不可撤销。
        </div>
        <div v-if="diffLoading" class="space-y-2">
          <div v-for="i in 3" :key="i" class="h-7 animate-pulse rounded-md bg-muted" />
        </div>
        <template v-else-if="diffData">
          <p class="text-xs font-medium text-muted-foreground">将发生变化的配置项：</p>
          <div v-if="diffData.diff?.changed === false" class="rounded-lg border border-emerald-300/50 bg-emerald-50/50 p-3 text-sm text-emerald-700 dark:text-emerald-300">
            当前配置与该版本一致，回滚无实际变化。
          </div>
          <div v-else class="max-h-[40vh] space-y-2 overflow-y-auto pr-1">
            <template v-for="(d, key) in diffData.diff?.domains" :key="key">
              <div v-if="(d as any).added.length || (d as any).removed.length || (d as any).modified.length" class="rounded-lg border border-border p-2.5">
                <p class="mb-1.5 text-xs font-medium text-foreground">{{ (d as any).label }}</p>
                <div v-if="(d as any).added.length" class="mb-1 flex flex-wrap gap-1.5">
                  <Badge v-for="name in (d as any).added" :key="'a' + name" variant="default" class="text-[10px]">＋ {{ name }}</Badge>
                </div>
                <div v-if="(d as any).removed.length" class="mb-1 flex flex-wrap gap-1.5">
                  <Badge v-for="name in (d as any).removed" :key="'r' + name" variant="destructive" class="text-[10px]">－ 将删除 {{ name }}</Badge>
                </div>
                <div v-if="(d as any).modified.length" class="flex flex-wrap gap-1.5">
                  <Badge v-for="name in (d as any).modified" :key="'m' + name" variant="outline" class="text-[10px]">* 将覆盖 {{ name }}</Badge>
                </div>
              </div>
            </template>
          </div>
        </template>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="rollbackConfirmOpen = false">取消</Button>
        <Button variant="destructive" :disabled="rollingBack" @click="confirmRollback">
          <Loader2 v-if="rollingBack" class="size-4 animate-spin" :stroke-width="1.5" />
          确认回滚
        </Button>
      </div>
    </Dialog>
  </div>
</template>