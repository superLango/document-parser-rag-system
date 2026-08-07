<script setup lang="ts">
/**
 * Prompt 模板独立编辑页
 *
 * - simple 模式：上部 system 提示词 + 下部 user 提示词
 * - schema 模式：上部 system 提示词 + 三栏（左类别列表 / 中 user 提示词 / 右可用字段）
 *   - 右侧字段支持 ${字段名} / ${字段名.子属性} 占位符插入
 * - 保存：simple 传 system_prompt + user_prompt；schema 传 system_prompt + categories[]
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Save,
  Loader2,
  BookMarked,
  FileText,
  Braces,
  ChevronRight,
  Info,
  Play,
} from 'lucide-vue-next'
import { kbApi, type TermBase, type TermBaseTerm } from '@/api/modules/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import TestPanel from './TestPanel.vue'

const route = useRoute()
const router = useRouter()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)
const promptId = computed(() => route.params.prompt_id as string)

const loading = ref(true)
const saving = ref(false)
const prompt = ref<Record<string, any> | null>(null)

// 顶部信息
const name = ref('')
const description = ref('')
const scope = ref<'simple' | 'schema'>('simple')
const isActive = ref(true)
const systemPrompt = ref('')

// simple 模式
const simpleUserPrompt = ref('')

// schema 模式
interface FieldDef {
  id: string
  name: string
  type: string
  description: string
  example: string | null
  required: boolean
}
interface TermRef {
  label: string
  term_base_id: string
  group_field: string
  value_field: string
}
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
  fields: FieldDef[]
}
const categories = ref<EditorCategory[]>([])
const activeCatId = ref('')

// 术语库列表（解析 term_base 类别默认显示名）
const termBases = ref<TermBase[]>([])

function categoryDisplayName(cat: EditorCategory): string {
  if (cat.name && cat.name.trim()) return cat.name
  if (cat.name_source === 'term_base') {
    const tb = termBases.value.find((b) => b.id === cat.name_term_base_id)
    return tb ? tb.name : '术语类别'
  }
  return cat.name || '未命名类别'
}

const activeCat = computed(() => categories.value.find((c) => c.id === activeCatId.value) || null)

// 系统参数（右侧面板可插入）
const SYSTEM_PARAMS: { label: string; placeholder: string }[] = [
  { label: 'feature（类别名）', placeholder: '${feature}' },
  { label: 'feature_descript（类别描述）', placeholder: '${feature_descript}' },
  { label: 'schema（当前类别组装后的 Schema）', placeholder: '${schema}' },
  { label: 'context（文档上下文）', placeholder: '${context}' },
  { label: 'return_type（返回类型）', placeholder: '${return_type}' },
  { label: 'prev_brands（前批牌号）', placeholder: '${prev_brands}' },
]

// 当前类别的术语集参数（名称来源术语集 + Query 术语集）
const activeTermRefs = computed<TermRef[]>(() => {
  const cat = activeCat.value
  if (!cat) return []
  const seen = new Set<string>()
  const refs: TermRef[] = []
  // 名称来源术语集
  if (cat.name_source === 'term_base' && cat.name_term_base_id) {
    const tb = termBases.value.find((b) => b.id === cat.name_term_base_id)
    seen.add(cat.name_term_base_id)
    refs.push({
      label: tb ? tb.name : '术语类别',
      term_base_id: cat.name_term_base_id,
      group_field: '',
      value_field: cat.name_term_field || '',
    })
  }
  // Query 术语集
  for (const q of cat.query_sources || []) {
    if (!q.term_base_id || seen.has(q.term_base_id)) continue
    seen.add(q.term_base_id)
    const tb = termBases.value.find((b) => b.id === q.term_base_id)
    refs.push({
      label: q.label || (tb ? tb.name : '术语集'),
      term_base_id: q.term_base_id,
      group_field: q.group_field,
      value_field: q.value_field,
    })
  }
  return refs
})

async function load() {
  loading.value = true
  try {
    const res = await kbApi.getExtractionPrompt(kbId.value, promptId.value)
    const data = (res as Record<string, any>) || {}
    prompt.value = data
    name.value = data.name || ''
    description.value = data.description || ''
    scope.value = data.scope === 'schema' ? 'schema' : 'simple'
    isActive.value = data.is_active !== false
    systemPrompt.value = data.system_prompt || ''
    simpleUserPrompt.value = data.user_prompt || ''

    // 加载术语库（解析 term_base 类别默认显示名）
    try {
      const tbRes = await kbApi.listTermBases(kbId.value)
      termBases.value = (tbRes.items as TermBase[]) || []
    } catch {
      termBases.value = []
    }

    // 加载 Schema 模板详情（获取类别字段，用于右侧面板）
    if (scope.value === 'schema' && data.schema_template_id) {
      const cats = (data.categories as { category_id: string; name: string; user_prompt: string }[]) || []
      const promptCatMap = new Map(cats.map((c) => [c.category_id, c.user_prompt || '']))
      try {
        const tpl = (await kbApi.getSchemaTemplate(kbId.value, data.schema_template_id)) as unknown as {
          categories: {
            id: string
            name: string
            name_source?: string
            name_term_base_id?: string | null
            name_term_field?: string | null
            description?: string
            return_type?: string
            query_sources?: TermRef[]
            fields: FieldDef[]
          }[]
        }
        const tplCats = tpl.categories || []
        categories.value = tplCats.map((c) => ({
          id: c.id,
          name: c.name,
          name_source: c.name_source,
          name_term_base_id: c.name_term_base_id,
          name_term_field: c.name_term_field,
          description: c.description || '',
          return_type: c.return_type || 'array',
          query_sources: c.query_sources || [],
          user_prompt: promptCatMap.get(c.id) || '',
          fields: c.fields || [],
        }))
      } catch {
        // 模板加载失败，回退到 prompt 返回的类别（无字段）
        categories.value = cats.map((c) => ({
          id: c.category_id,
          name: c.name,
          description: '',
          return_type: 'array',
          query_sources: [],
          user_prompt: c.user_prompt || '',
          fields: [],
        }))
      }
      if (categories.value.length > 0) {
        activeCatId.value = categories.value[0].id
      }
    }
  } catch {
    // 拦截器提示
  } finally {
    loading.value = false
  }
}

function selectCat(id: string) {
  activeCatId.value = id
}

// 插入占位符到目标 textarea 光标处
function insertPlaceholder(placeholder: string) {
  if (scope.value === 'simple') {
    const el = document.getElementById('user-prompt-simple') as HTMLTextAreaElement | null
    insertInto(el, placeholder, (v) => (simpleUserPrompt.value = v))
    return
  }
  const cat = activeCat.value
  if (!cat) return
  const el = document.getElementById(`user-prompt-${cat.id}`) as HTMLTextAreaElement | null
  insertInto(el, placeholder, (v) => (cat.user_prompt = v))
}

function insertInto(
  el: HTMLTextAreaElement | null,
  text: string,
  setter: (v: string) => void,
) {
  if (!el) {
    setter((scope.value === 'simple' ? simpleUserPrompt.value : activeCat.value?.user_prompt || ''))
  }
  const start = el?.selectionStart ?? 0
  const end = el?.selectionEnd ?? 0
  const current = el ? el.value : ''
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

// ============================================================
// 组装测试
// ============================================================
const testResult = ref<{ system: string; user: string } | null>(null)
const testCatName = ref('')

// 组装当前类别的 schema 预览（模拟 ${schema} 替换）
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

// 术语集字段值缓存：baseId -> (field -> values[])
const termBaseValuesCache = ref<Map<string, Map<string, string[]>>>(new Map())

// 手动术语集内置字段到 TermBaseTerm 字段的映射
function manualTermValue(t: TermBaseTerm, field: string): unknown {
  const map: Record<string, unknown> = {
    term_name: t.term,
    standard_name: t.english_term || t.extras?.standard_name,
    definition: t.definition,
    category: t.category,
    synonyms: t.synonyms,
    aliases: t.aliases,
    standard_number: t.standard_number,
  }
  return map[field] ?? t.extras?.[field]
}

// 从单个术语记录读取指定字段的值（兼容 manual / api / db）
function readTermValue(t: TermBaseTerm, base: TermBase, field: string): unknown {
  if (base.source_type === 'manual') {
    const v = manualTermValue(t, field)
    if (v != null) return v
  }
  return t.extras?.[field] ?? t.extras?.[field.toLowerCase()] ?? manualTermValue(t, field)
}

// 从术语记录中提取指定字段的全部值（去重，可按 groupField 过滤）
function extractFieldValues(
  rows: TermBaseTerm[],
  base: TermBase,
  field: string,
  filter?: { groupField: string; groupValue: string },
): string[] {
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

// 预加载文本中引用的术语集字段值（${术语集名.字段}）
// 术语集名优先匹配类别 query_sources 的自定义 label，回退到术语集实际 name
function buildTermRefMap(cat: EditorCategory | null): Map<string, { baseId: string; groupField?: string }> {
  const m = new Map<string, { baseId: string; groupField?: string }>()
  for (const b of termBases.value) m.set(b.name, { baseId: b.id })
  if (cat) {
    for (const qs of cat.query_sources) {
      if (qs.label) m.set(qs.label, { baseId: qs.term_base_id, groupField: qs.group_field || undefined })
    }
  }
  return m
}

// 分页加载某术语集全部术语记录（后端 page_size 上限 100）
async function loadAllTermBaseRows(baseId: string): Promise<TermBaseTerm[]> {
  const rows: TermBaseTerm[] = []
  let page = 1
  let total = -1
  while (total === -1 || rows.length < total) {
    const res = (await kbApi.listTermBaseTerms(kbId.value, baseId, {
      page,
      page_size: 100,
    })) as unknown as { items: TermBaseTerm[]; total: number }
    rows.push(...((res.items as TermBaseTerm[]) || []))
    total = res.total ?? rows.length
    if (!res.items || res.items.length === 0) break
    page += 1
  }
  return rows
}

// 异步加载并缓存某术语集某字段的全部值（可指定 groupField 过滤）
async function ensureFieldValue(
  baseId: string,
  base: TermBase,
  field: string,
  filter?: { groupField: string; groupValue: string },
) {
  const cache = termBaseValuesCache.value
  if (!cache.has(baseId)) cache.set(baseId, new Map())
  const fieldCache = cache.get(baseId)!
  const keys = [field, field.toLowerCase()]
  const hit = keys.find((k) => fieldCache.has(k))
  if (hit) return
  const rows = await loadAllTermBaseRows(baseId)
  for (const k of keys) {
    fieldCache.set(k, extractFieldValues(rows, base, k, filter))
  }
}

// term_base 类别：返回名称来源字段（name_term_field）的第一个值，作为测试类别名与分组过滤值
async function termBaseFirstValue(cat: EditorCategory): Promise<string> {
  if (!cat || cat.name_source !== 'term_base' || !cat.name_term_base_id || !cat.name_term_field) return ''
  const base = termBases.value.find((b) => b.id === cat.name_term_base_id)
  if (!base) return ''
  await ensureFieldValue(cat.name_term_base_id, base, cat.name_term_field)
  const fieldCache = termBaseValuesCache.value.get(cat.name_term_base_id)
  const first = fieldCache?.get(cat.name_term_field) || fieldCache?.get(cat.name_term_field.toLowerCase())
  return (first?.[0] as string) || ''
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
    const base = termBases.value.find((b) => b.id === ref.baseId)
    if (!base) continue
    const jobKey = `${ref.baseId}:${field}:${ref.groupField || ''}:${groupValue}`
    if (seen.has(jobKey)) continue
    seen.add(jobKey)
    jobs.push({
      base,
      field,
      // 当前类别为 term_base，且该术语集配置了分组字段时，按分组值过滤
      filter: ref.groupField && groupValue ? { groupField: ref.groupField, groupValue } : undefined,
    })
  }
  for (const job of jobs) {
    try {
      await ensureFieldValue(job.base.id, job.base, job.field, job.filter)
    } catch {
      // 加载失败则保留占位符
    }
  }
}

// 渲染 user 提示词中的 ${xxx} 占位符（无实际值的参数保留占位符）
function renderUserPrompt(text: string, cat: EditorCategory | null, groupValue = ''): string {
  if (!text) return text
  const fieldMap = new Map((cat?.fields || []).map((f) => [f.name, f]))
  const refMap = buildTermRefMap(cat)
  return text.replace(/\$\{([^{}]+)\}/g, (full, raw) => {
    const key = String(raw).trim()
    // 字段子属性 / 术语集字段
    if (key.includes('.')) {
      const [fname, attr] = key.split('.', 2)
      // 术语集占位符：${术语集名.字段}
      const ref = refMap.get(fname)
      if (ref) {
        const cache = termBaseValuesCache.value.get(ref.baseId)
        const fieldCache = cache ? cache.get(attr) || cache.get(attr.toLowerCase()) : undefined
        if (fieldCache && fieldCache.length > 0) return `[${fieldCache.join(', ')}]`
        return full
      }
      const f = fieldMap.get(fname)
      if (f) {
        if (attr === '类型') return f.type
        if (attr === '必填') return f.required ? '是' : '否'
        if (attr === '描述') return f.description
        if (attr === '示例') return f.example || ''
        if (attr === '枚举') return ''
        if (attr === '术语集') return ''
      }
      return full
    }
    // 字段名：仅代入字段名称
    if (fieldMap.has(key)) return key
    // 系统参数
    if (key === 'feature') return cat ? groupValue || categoryDisplayName(cat) : ''
    if (key === 'feature_descript') return cat?.description || ''
    if (key === 'schema') return cat ? buildSchemaPreview(cat) : ''
    if (key === 'return_type') return cat?.return_type || 'array'
    // context / prev_brands：暂无实际值，保留占位符
    return full
  })
}

async function runTest() {
  const cat = scope.value === 'schema' ? activeCat.value : null
  const userText = scope.value === 'simple' ? simpleUserPrompt.value : cat?.user_prompt || ''
  // term_base 类别：取名称来源字段第一个值作为测试类别名与分组过滤值
  const groupValue = scope.value === 'schema' && cat ? await termBaseFirstValue(cat) : ''
  await ensureTermBaseValues(userText, cat, groupValue)
  testCatName.value = scope.value === 'schema' && cat ? groupValue || categoryDisplayName(cat) : ''
  testResult.value = {
    system: systemPrompt.value,
    user: renderUserPrompt(userText, cat, groupValue),
  }
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, any> = {
      system_prompt: systemPrompt.value,
      is_active: isActive.value,
    }
    if (scope.value === 'simple') {
      payload.user_prompt = simpleUserPrompt.value
    } else {
      payload.categories = categories.value.map((c) => ({
        category_id: c.id,
        user_prompt: c.user_prompt,
      }))
    }
    await kbApi.saveExtractionPrompt(kbId.value, promptId.value, payload)
    toast.success('Prompt 已保存', name.value)
  } catch {
    // 拦截器提示
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="flex flex-col gap-4 p-4 lg:p-6">
    <PageHeader
      :title="name || 'Prompt 模板'"
      :description="description || '配置抽取提示词'"
    >
      <template #actions>
        <Button variant="outline" @click="router.push(`/kbs/${kbId}/extraction-config?tab=prompt`)">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回
        </Button>
        <Button v-if="isEditor" :disabled="saving" @click="save">
          <Loader2 v-if="saving" class="size-4 animate-spin" :stroke-width="1.5" />
          <Save v-else class="size-4" :stroke-width="1.5" />
          保存
        </Button>
      </template>
    </PageHeader>

    <div v-if="loading" class="flex items-center justify-center py-20">
      <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
    </div>

    <template v-else-if="prompt">
      <!-- 顶部信息 -->
      <Card>
        <CardContent class="flex flex-wrap items-center justify-between gap-3 p-4">
          <div class="flex items-center gap-2">
            <Badge variant="outline">{{ scope === 'schema' ? 'Schema 模式' : '简单模式' }}</Badge>
            <Badge :variant="isActive ? 'default' : 'secondary'">{{ isActive ? '启用' : '停用' }}</Badge>
          </div>
          <label class="flex items-center gap-2 text-sm">
            <Switch :model-value="isActive" @update:model-value="(v: boolean) => (isActive = v)" />
            启用
          </label>
        </CardContent>
      </Card>

      <!-- system 提示词 -->
      <Card>
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-sm">
            <BookMarked class="size-4" :stroke-width="1.5" />
            System 系统提示词
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Textarea
            v-model="systemPrompt"
            :disabled="!isEditor"
            :rows="8"
            class="font-mono text-sm"
            placeholder="输入系统提示词"
          />
          <p class="flex items-center gap-1 text-xs text-muted-foreground">
            <Info class="size-3.5" :stroke-width="1.5" />
            System 提示词为全局角色设定，不使用 ${...} 占位符
          </p>
        </CardContent>
      </Card>

      <!-- simple 模式：单一 user 提示词 -->
      <Card v-if="scope === 'simple'">
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-sm">
            <FileText class="size-4" :stroke-width="1.5" />
            User 提示词
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div class="grid items-start gap-4 lg:grid-cols-2">
            <div class="space-y-3">
              <Textarea
                id="user-prompt-simple"
                v-model="simpleUserPrompt"
                :disabled="!isEditor"
                :rows="14"
                class="font-mono text-sm"
                placeholder="输入 user 提示词"
              />
              <p class="flex items-center gap-1 text-xs text-muted-foreground">
                <Info class="size-3.5" :stroke-width="1.5" />
                可用占位符：${feature}、${feature_descript}、${schema}、${context}、${return_type}、${prev_brands}
              </p>
              <div class="flex justify-end">
                <Button variant="outline" size="sm" @click="runTest">
                  <Play class="size-4" :stroke-width="1.5" />
                  测试组装
                </Button>
              </div>
            </div>
            <TestPanel :result="testResult" :cat-name="testCatName" />
          </div>
        </CardContent>
      </Card>

      <!-- schema 模式：三栏 -->
      <Card v-else>
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-sm">
            <FileText class="size-4" :stroke-width="1.5" />
            按类别配置 User 提示词
          </CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            v-if="categories.length === 0"
            :icon="FileText"
            title="暂无类别"
            description="该 Schema 模板下没有选中类别"
            class="py-10"
          />
          <div v-else class="grid gap-4 lg:grid-cols-4">
            <!-- 左栏：类别列表 -->
            <div class="space-y-1 rounded-lg border p-2">
              <p class="px-1 pb-1 text-xs font-medium text-muted-foreground">类别</p>
              <button
                v-for="cat in categories"
                :key="cat.id"
                type="button"
                class="flex w-full items-center justify-between gap-1 rounded-md px-2 py-1.5 text-left text-sm transition-colors"
                :class="activeCatId === cat.id ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-muted'"
                @click="selectCat(cat.id)"
              >
                <span class="min-w-0 flex-1">
                  <span class="line-clamp-1">{{ categoryDisplayName(cat) }}</span>
                  <span v-if="cat.name_source === 'term_base'" class="block text-[10px] text-amber-600">使用术语库</span>
                </span>
                <ChevronRight class="size-3.5 shrink-0 opacity-60" :stroke-width="1.5" />
              </button>
            </div>

            <!-- 栏2：可用参数 -->
            <div class="rounded-lg border p-2">
              <p class="flex items-center gap-1 px-1 pb-1 text-xs font-medium text-muted-foreground">
                <Braces class="size-3.5" :stroke-width="1.5" />
                可用参数
              </p>
              <div class="max-h-[480px] space-y-3 overflow-y-auto">
                <!-- 系统参数 -->
                <div class="space-y-1">
                  <p class="px-1 text-[10px] font-medium text-muted-foreground">系统参数</p>
                  <button
                    v-for="p in SYSTEM_PARAMS"
                    :key="p.placeholder"
                    type="button"
                    :disabled="!isEditor"
                    class="flex w-full items-center justify-between gap-1 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-muted"
                    @click="insertPlaceholder(p.placeholder)"
                  >
                    <span class="min-w-0 flex-1">
                      <span class="line-clamp-1 text-foreground">{{ p.label }}</span>
                      <span class="block font-mono text-[10px] text-primary">{{ p.placeholder }}</span>
                    </span>
                    <Badge variant="outline" class="shrink-0 text-[9px]">系统</Badge>
                  </button>
                </div>

                <!-- 字段 -->
                <div v-if="activeCat && activeCat.fields.length > 0" class="space-y-1">
                  <p class="px-1 text-[10px] font-medium text-muted-foreground">字段</p>
                  <button
                    v-for="f in activeCat.fields"
                    :key="f.id"
                    type="button"
                    :disabled="!isEditor"
                    class="flex w-full items-center justify-between gap-1 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-muted"
                    @click="insertPlaceholder(`\${${f.name}}`)"
                  >
                    <span class="line-clamp-1 font-mono text-primary">{{ '$' + '{' + f.name + '}' }}</span>
                    <Badge variant="outline" class="shrink-0 text-[9px]">{{ f.type }}</Badge>
                  </button>
                </div>

                <!-- 术语集 / Query -->
                <div v-if="activeTermRefs.length > 0" class="space-y-1">
                  <p class="px-1 text-[10px] font-medium text-muted-foreground">术语集 / Query</p>
                  <div v-for="ref in activeTermRefs" :key="ref.term_base_id" class="space-y-1 rounded-md bg-muted/40 p-1.5">
                    <button
                      type="button"
                      :disabled="!isEditor"
                      class="flex w-full items-center justify-between gap-1 rounded px-1.5 py-1 text-left text-xs transition-colors hover:bg-muted"
                      @click="insertPlaceholder(`\${${ref.label}}`)"
                    >
                      <span class="line-clamp-1 font-mono text-primary">{{ '$' + '{' + ref.label + '}' }}</span>
                      <Badge variant="outline" class="shrink-0 text-[9px]">术语集</Badge>
                    </button>
                    <div v-if="ref.value_field" class="flex flex-wrap gap-1 px-1">
                      <button
                        v-if="ref.group_field"
                        type="button"
                        :disabled="!isEditor"
                        class="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted"
                        @click="insertPlaceholder(`\${${ref.label}.${ref.group_field}}`)"
                      >
                        {{ ref.group_field }}
                      </button>
                      <button
                        type="button"
                        :disabled="!isEditor"
                        class="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted"
                        @click="insertPlaceholder(`\${${ref.label}.${ref.value_field}}`)"
                      >
                        {{ ref.value_field }}
                      </button>
                    </div>
                  </div>
                </div>

                <p v-if="SYSTEM_PARAMS.length === 0 && (!activeCat || activeCat.fields.length === 0) && activeTermRefs.length === 0" class="px-1 pt-2 text-[10px] text-muted-foreground">
                  点击参数名插入 ${参数} 占位符
                </p>
              </div>
            </div>

            <!-- 栏3：当前类别 user 提示词 -->
            <div class="flex flex-col gap-2">
              <div v-if="activeCat" class="flex items-center justify-between">
                <span class="text-sm font-medium">{{ categoryDisplayName(activeCat) }} - User 提示词</span>
                <Badge variant="outline" class="text-[10px]">{{ activeCat.fields.length }} 个字段</Badge>
              </div>
              <Textarea
                v-if="activeCat"
                :id="`user-prompt-${activeCat.id}`"
                :model-value="activeCat.user_prompt"
                :disabled="!isEditor"
                :rows="16"
                class="flex-1 font-mono text-sm"
                placeholder="输入该类别的 user 提示词"
                @update:model-value="(v: string) => { const c = activeCat; if (c) c.user_prompt = v }"
              />
              <div class="flex justify-end">
                <Button variant="outline" size="sm" @click="runTest">
                  <Play class="size-4" :stroke-width="1.5" />
                  测试组装
                </Button>
              </div>
            </div>

            <!-- 栏4：测试效果 -->
            <TestPanel :result="testResult" :cat-name="testCatName" />
          </div>
        </CardContent>
      </Card>
    </template>
  </div>
</template>