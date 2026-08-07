<script setup lang="ts">
/**
 * 术语集详情编辑器
 *
 * 功能：
 * - manual 类型：可编辑术语表格（新增/修改/删除/批量保存），固定列
 * - api/db 类型：只读展示动态列数据（列来自数据源返回字段）+ 同步按钮 + 字段别名编辑
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Plus,
  Save,
  Loader2,
  Trash2,
  Search,
  X,
  BookMarked,
  RefreshCcw,
  Hand,
  Globe,
  Database as DbIcon,
  Settings2,
  Check,
} from 'lucide-vue-next'
import { kbApi, type TermBase, type TermBaseTerm } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { PageHeader } from '@/components/ui/page-header'
import { Pagination } from '@/components/ui/pagination'
import { Badge } from '@/components/ui/badge'
import { confirm } from '@/composables/useConfirm'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)
const baseId = computed(() => route.params.base_id as string)

const loading = ref(true)
const saving = ref(false)
const syncing = ref(false)
const termBase = ref<TermBase | null>(null)

const baseForm = ref({
  name: '',
  description: '',
})

// 是否为手动录入类型
const isManual = computed(() => termBase.value?.source_type === 'manual')

// 数据源类型元信息
const sourceTypeMeta: Record<string, { label: string; icon: any; color: string }> = {
  manual: { label: '手动录入', icon: Hand, color: 'bg-blue-100 text-blue-700' },
  api: { label: '接口拉取', icon: Globe, color: 'bg-green-100 text-green-700' },
  db: { label: '数据库', icon: DbIcon, color: 'bg-purple-100 text-purple-700' },
}

// 动态列定义（合并 column_aliases 生成显示名）
interface DisplayColumn {
  name: string       // 原始字段名（用于 extras 取值和同步映射）
  label: string      // 显示名称（优先使用别名，否则原始字段名）
  type: string
}

const displayColumns = computed<DisplayColumn[]>(() => {
  if (!termBase.value?.columns) return []
  const aliases = termBase.value.column_aliases || {}
  return termBase.value.columns.map(col => ({
    name: col.name,
    label: aliases[col.name] || col.label || col.name,
    type: col.type || 'string',
  }))
})

// 字段别名编辑面板
const aliasPanelOpen = ref(false)
const aliasSaving = ref(false)
// 编辑中的别名映射：原始字段名 -> 新显示名
const editingAliases = ref<Record<string, string>>({})

function openAliasPanel() {
  if (!termBase.value) return
  // 初始化：将当前别名复制到编辑状态，没有别名的字段用原始字段名填充
  const aliases = termBase.value.column_aliases || {}
  const initial: Record<string, string> = {}
  for (const col of termBase.value.columns) {
    initial[col.name] = aliases[col.name] || col.label || col.name
  }
  editingAliases.value = initial
  aliasPanelOpen.value = true
}

async function saveAliases() {
  if (!termBase.value) return
  aliasSaving.value = true
  try {
    // 只保存那些真正修改过的别名（与原始字段名不同的）
    const aliasesToSave: Record<string, string> = {}
    for (const col of termBase.value.columns) {
      const edited = (editingAliases.value[col.name] || '').trim()
      if (edited && edited !== col.name && edited !== (col.label || col.name)) {
        aliasesToSave[col.name] = edited
      }
    }
    await kbApi.updateTermBase(kbId.value, baseId.value, {
      column_aliases: aliasesToSave,
    })
    toast.success('字段名已更新')
    aliasPanelOpen.value = false
    await fetchBase()
  } catch {
    // 拦截器已处理
  } finally {
    aliasSaving.value = false
  }
}

function resetAlias(colName: string) {
  if (!termBase.value) return
  const col = termBase.value.columns.find(c => c.name === colName)
  if (col) {
    editingAliases.value[colName] = col.name
  }
}

interface EditableTerm extends TermBaseTerm {
  _isNew?: boolean
  _isDeleted?: boolean
  _modified?: boolean
}

const terms = ref<EditableTerm[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const keyword = ref('')
const searchField = ref('')  // 空字符串表示搜索全部字段

// 搜索字段选项
const searchFieldOptions = computed<{ value: string; label: string }[]>(() => {
  if (!termBase.value) return [{ value: '', label: '全部字段' }]
  if (isManual.value) {
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
  // api/db 类型：动态列
  const opts: { value: string; label: string }[] = [{ value: '', label: '全部字段' }]
  for (const col of displayColumns.value) {
    opts.push({ value: col.name, label: col.label })
  }
  return opts
})

let nextTempId = -1

async function fetchBase() {
  try {
    const res = await kbApi.listTermBases(kbId.value)
    termBase.value = res.items.find(b => b.id === baseId.value) || null
    if (termBase.value) {
      baseForm.value.name = termBase.value.name
      baseForm.value.description = termBase.value.description
    }
  } catch {
    termBase.value = null
  }
}

async function fetchTerms() {
  loading.value = true
  try {
    const res = await kbApi.listTermBaseTerms(kbId.value, baseId.value, {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      search_field: searchField.value || undefined,
    })
    terms.value = (res.items as EditableTerm[]) || []
    total.value = res.total
  } catch {
    terms.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function addRow() {
  const newRow: EditableTerm = {
    id: String(nextTempId--),
    term_base_id: baseId.value,
    term: '',
    english_term: '',
    aliases: [],
    definition: '',
    category: '',
    synonyms: [],
    extras: {},
    standard_number: '',
    status: 'active',
    created_at: new Date().toISOString(),
    updated_at: null,
    _isNew: true,
  }
  terms.value.unshift(newRow)
}

function markModified(row: EditableTerm) {
  if (!row._isNew) {
    row._modified = true
  }
}

function deleteRow(row: EditableTerm) {
  if (row._isNew) {
    const idx = terms.value.findIndex(t => t.id === row.id)
    if (idx >= 0) terms.value.splice(idx, 1)
  } else {
    row._isDeleted = !row._isDeleted
  }
}

function addAlias(row: EditableTerm, inputEl: HTMLInputElement) {
  const val = inputEl.value.trim()
  if (val && !row.aliases.includes(val)) {
    row.aliases = [...row.aliases, val]
    inputEl.value = ''
    markModified(row)
  }
}

function removeAlias(row: EditableTerm, idx: number) {
  row.aliases.splice(idx, 1)
  markModified(row)
}

function addSynonym(row: EditableTerm, inputEl: HTMLInputElement) {
  const val = inputEl.value.trim()
  if (val && !row.synonyms.includes(val)) {
    row.synonyms = [...row.synonyms, val]
    inputEl.value = ''
    markModified(row)
  }
}

function removeSynonym(row: EditableTerm, idx: number) {
  row.synonyms.splice(idx, 1)
  markModified(row)
}

async function saveBaseInfo() {
  if (!baseForm.value.name.trim()) {
    toast.warning('请填写术语集名称')
    return false
  }
  if (termBase.value) {
    try {
      await kbApi.updateTermBase(kbId.value, baseId.value, {
        name: baseForm.value.name.trim(),
        description: baseForm.value.description.trim(),
      })
      return true
    } catch {
      return false
    }
  }
  return true
}

async function saveAll() {
  if (!baseForm.value.name.trim()) {
    toast.warning('请填写术语集名称')
    return
  }

  for (const t of terms.value) {
    if (!t._isDeleted && !t.term.trim()) {
      toast.warning('存在未填写术语名称的行，请填写或删除')
      return
    }
  }

  saving.value = true
  try {
    const baseSaved = await saveBaseInfo()
    if (!baseSaved) {
      saving.value = false
      return
    }

    const itemsToSave = terms.value
      .filter(t => !t._isDeleted && (t._isNew || t._modified))
      .map(t => ({
        id: t._isNew ? undefined : t.id,
        term: t.term.trim(),
        english_term: t.english_term,
        aliases: t.aliases,
        definition: t.definition,
        category: t.category,
        synonyms: t.synonyms,
        extras: t.extras || {},
      }))

    const deletedIds = terms.value
      .filter(t => t._isDeleted && !t._isNew)
      .map(t => t.id)

    if (itemsToSave.length > 0 || deletedIds.length > 0) {
      await kbApi.batchSaveTermBaseTerms(kbId.value, baseId.value, {
        items: itemsToSave,
        deleted_ids: deletedIds,
      })
    }

    toast.success('保存成功')
    page.value = 1
    await Promise.all([fetchBase(), fetchTerms()])
  } catch {
    // 错误已由拦截器提示
  } finally {
    saving.value = false
  }
}

async function syncFromSource() {
  if (!termBase.value) return
  if (!await confirm(`将从数据源重新同步，现有数据将被覆盖，是否继续？`)) return
  syncing.value = true
  try {
    const res = await kbApi.syncTermBase(kbId.value, baseId.value)
    toast.success('同步完成', `导入 ${res.imported} 条数据`)
    await Promise.all([fetchBase(), fetchTerms()])
  } catch {
    // 错误已由拦截器提示
  } finally {
    syncing.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchTerms()
}

function handlePageChange(p: number) {
  page.value = p
  fetchTerms()
}

function goBack() {
  router.push({ name: 'KbTerms', params: { kb_id: kbId.value } })
}

// 获取动态列的单元格值
function getCellValue(row: EditableTerm, colName: string): string {
  if (row.extras && row.extras[colName] != null) {
    const v = row.extras[colName]
    if (Array.isArray(v)) return v.join(', ')
    return String(v)
  }
  return ''
}

onMounted(() => {
  fetchBase().then(fetchTerms)
})
</script>

<template>
  <div>
    <PageHeader :title="`编辑术语集 · ${termBase?.name || ''}`" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="goBack">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回列表
        </Button>
        <Button
          v-if="isEditor && !isManual"
          variant="outline"
          @click="syncFromSource"
          :disabled="syncing"
        >
          <RefreshCcw class="size-4" :class="{ 'animate-spin': syncing }" :stroke-width="1.5" />
          {{ syncing ? '同步中...' : '从数据源同步' }}
        </Button>
        <Button v-if="isEditor && isManual" :disabled="saving" @click="saveAll">
          <Save class="size-4" :stroke-width="1.5" />
          <Loader2 v-if="saving" class="ml-1 size-4 animate-spin" :stroke-width="1.5" />
          保存全部
        </Button>
      </template>
    </PageHeader>

    <!-- 基础信息编辑 -->
    <Card class="mb-4">
      <CardHeader class="pb-3">
        <CardTitle class="text-base flex items-center gap-2">
          <BookMarked class="size-4 text-primary" :stroke-width="1.5" />
          术语集信息
          <Badge v-if="termBase" :class="`ml-2 ${sourceTypeMeta[termBase.source_type]?.color || ''}`">
            <component :is="sourceTypeMeta[termBase.source_type]?.icon" class="mr-1 size-3" />
            {{ sourceTypeMeta[termBase.source_type]?.label }}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div class="space-y-1.5">
            <Label>术语集名称 *</Label>
            <Input
              v-model="baseForm.name"
              placeholder="术语集名称"
              :disabled="!isEditor"
            />
          </div>
          <div class="space-y-1.5">
            <Label>术语数量</Label>
            <div class="flex h-9 items-center rounded-md border px-3 text-sm text-muted-foreground">
              {{ total }} 条术语
              <span v-if="termBase?.last_synced_at" class="ml-3 text-xs">
                上次同步：{{ new Date(termBase.last_synced_at).toLocaleString() }}
              </span>
            </div>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Textarea
            v-model="baseForm.description"
            placeholder="描述该术语集的适用范围与用途"
            :rows="2"
            :disabled="!isEditor"
          />
        </div>
      </CardContent>
    </Card>

    <!-- 搜索与添加 -->
    <Card class="mb-4">
      <CardContent class="flex flex-wrap items-center gap-3 p-3">
        <div v-if="isEditor && isManual">
          <Button size="sm" @click="addRow">
            <Plus class="size-4" :stroke-width="1.5" />
            添加一行
          </Button>
        </div>
        <div v-if="isEditor && !isManual" class="text-xs text-muted-foreground shrink-0">
          该术语集数据来源于外部数据源，如需修改请在数据源处更新后点击同步
        </div>
        <!-- 搜索字段选择 -->
        <div class="w-[140px] shrink-0">
          <Select
            v-model="searchField"
            :options="searchFieldOptions"
            placeholder="搜索字段"
            class="h-9 text-sm"
          />
        </div>
        <!-- 搜索输入 -->
        <div class="relative flex-1 min-w-[200px]">
          <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
          <Input
            v-model="keyword"
            :placeholder="searchField ? `搜索${searchFieldOptions.find(o => o.value === searchField)?.label || ''}` : '搜索全部字段'"
            class="pl-8"
            @keyup.enter="handleSearch"
          />
        </div>
        <Button variant="outline" size="sm" @click="handleSearch">
          <Search class="size-4" :stroke-width="1.5" />
          搜索
        </Button>
        <!-- 修改字段按钮（非手动类型） -->
        <Button
          v-if="isEditor && !isManual"
          variant="outline"
          size="sm"
          @click="openAliasPanel"
        >
          <Settings2 class="size-4" :stroke-width="1.5" />
          修改字段
        </Button>
      </CardContent>
    </Card>

    <!-- 术语表格 -->
    <Card>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="border-b bg-muted/50">
            <tr>
              <th class="w-10 px-3 py-2 text-left font-medium text-muted-foreground">#</th>
              <!-- manual 类型：固定列 -->
              <template v-if="isManual">
                <th class="min-w-[140px] px-3 py-2 text-left font-medium text-muted-foreground">术语名称</th>
                <th class="min-w-[120px] px-3 py-2 text-left font-medium text-muted-foreground">英文名称</th>
                <th class="min-w-[160px] px-3 py-2 text-left font-medium text-muted-foreground">术语别称</th>
                <th class="min-w-[200px] px-3 py-2 text-left font-medium text-muted-foreground">术语定义</th>
                <th class="min-w-[100px] px-3 py-2 text-left font-medium text-muted-foreground">分类</th>
                <th class="min-w-[160px] px-3 py-2 text-left font-medium text-muted-foreground">同义词</th>
              </template>
              <!-- api/db 类型：动态列，表头使用别名 -->
              <th
                v-for="col in displayColumns"
                :key="col.name"
                class="min-w-[120px] px-3 py-2 text-left font-medium text-muted-foreground"
              >
                {{ col.label }}
              </th>
              <th v-if="isEditor && isManual" class="w-16 px-3 py-2 text-left font-medium text-muted-foreground">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td
                :colspan="1 + (isManual ? 6 : displayColumns.length) + (isEditor && isManual ? 1 : 0)"
                class="px-3 py-8 text-center text-muted-foreground"
              >
                <Loader2 class="mx-auto size-6 animate-spin" :stroke-width="1.5" />
              </td>
            </tr>
            <tr
              v-for="(t, idx) in terms"
              :key="t.id"
              class="border-b transition-colors"
              :class="{
                'opacity-50 bg-muted/30': t._isDeleted,
                'bg-success/5': t._isNew && !t._isDeleted,
                'bg-warning/5': t._modified && !t._isNew && !t._isDeleted,
              }"
            >
              <td class="px-3 py-2 align-top">
                <div class="flex flex-col gap-1">
                  <span class="text-muted-foreground text-xs">{{ (page - 1) * pageSize + idx + 1 }}</span>
                  <Badge v-if="t._isNew" variant="secondary" class="text-[10px]">新增</Badge>
                  <Badge v-else-if="t._modified" variant="secondary" class="bg-warning/20 text-warning text-[10px]">已修改</Badge>
                </div>
              </td>

              <!-- manual 类型：固定列 -->
              <template v-if="isManual">
                <!-- 术语名称 -->
                <td class="px-3 py-2 align-top">
                  <template v-if="isEditor && !t._isDeleted">
                    <Input
                      v-model="t.term"
                      placeholder="术语名称"
                      size="sm"
                      class="h-8"
                      @input="markModified(t)"
                    />
                  </template>
                  <template v-else>
                    <span class="text-sm">{{ t.term }}</span>
                  </template>
                </td>
                <td class="px-3 py-2 align-top">
                  <template v-if="isEditor && !t._isDeleted">
                    <Input
                      v-model="t.english_term"
                      placeholder="English"
                      size="sm"
                      class="h-8"
                      @input="markModified(t)"
                    />
                  </template>
                  <span v-else class="text-sm">{{ t.english_term }}</span>
                </td>
                <td class="px-3 py-2 align-top">
                  <template v-if="isEditor && !t._isDeleted">
                    <div class="space-y-1">
                      <div class="flex flex-wrap gap-1">
                        <Badge
                          v-for="(a, ai) in t.aliases"
                          :key="ai"
                          variant="secondary"
                          class="gap-1 text-xs cursor-pointer"
                          @click="removeAlias(t, ai)"
                        >
                          {{ a }}
                          <X class="size-3" />
                        </Badge>
                      </div>
                      <Input
                        placeholder="添加别称后回车"
                        size="sm"
                        class="h-7 text-xs"
                        @keyup.enter="(e: KeyboardEvent) => { addAlias(t, (e.target as HTMLInputElement)); (e.target as HTMLInputElement).value = '' }"
                      />
                    </div>
                  </template>
                  <div v-else class="flex flex-wrap gap-1">
                    <Badge v-for="(a, ai) in t.aliases" :key="ai" variant="secondary" class="text-xs">{{ a }}</Badge>
                  </div>
                </td>
                <td class="px-3 py-2 align-top">
                  <template v-if="isEditor && !t._isDeleted">
                    <Textarea
                      v-model="t.definition"
                      placeholder="术语定义"
                      class="min-h-[32px] text-xs resize-y"
                      :rows="1"
                      @input="markModified(t)"
                    />
                  </template>
                  <span v-else class="text-sm">{{ t.definition }}</span>
                </td>
                <td class="px-3 py-2 align-top">
                  <template v-if="isEditor && !t._isDeleted">
                    <Input
                      v-model="t.category"
                      placeholder="分类"
                      size="sm"
                      class="h-8"
                      @input="markModified(t)"
                    />
                  </template>
                  <span v-else class="text-sm">{{ t.category }}</span>
                </td>
                <td class="px-3 py-2 align-top">
                  <template v-if="isEditor && !t._isDeleted">
                    <div class="space-y-1">
                      <div class="flex flex-wrap gap-1">
                        <Badge
                          v-for="(s, si) in t.synonyms"
                          :key="si"
                          variant="secondary"
                          class="gap-1 text-xs cursor-pointer"
                          @click="removeSynonym(t, si)"
                        >
                          {{ s }}
                          <X class="size-3" />
                        </Badge>
                      </div>
                      <Input
                        placeholder="添加同义词后回车"
                        size="sm"
                        class="h-7 text-xs"
                        @keyup.enter="(e: KeyboardEvent) => { addSynonym(t, (e.target as HTMLInputElement)); (e.target as HTMLInputElement).value = '' }"
                      />
                    </div>
                  </template>
                  <div v-else class="flex flex-wrap gap-1">
                    <Badge v-for="(s, si) in t.synonyms" :key="si" variant="secondary" class="text-xs">{{ s }}</Badge>
                  </div>
                </td>
              </template>

              <!-- api/db 类型：动态列数据，全部从 extras 读取 -->
              <td
                v-for="col in displayColumns"
                :key="col.name"
                class="px-3 py-2 align-top"
              >
                <span class="text-sm break-all">{{ getCellValue(t, col.name) }}</span>
              </td>

              <td v-if="isEditor && isManual" class="px-3 py-2 align-top">
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-8 w-8 p-0"
                  :class="t._isDeleted ? 'text-success' : 'text-danger'"
                  :title="t._isDeleted ? '恢复' : '删除'"
                  @click="deleteRow(t)"
                >
                  <Trash2 v-if="!t._isDeleted" class="size-4" :stroke-width="1.5" />
                  <span v-else class="text-xs">恢复</span>
                </Button>
              </td>
            </tr>
            <tr v-if="!loading && terms.length === 0">
              <td
                :colspan="1 + (isManual ? 6 : displayColumns.length) + (isEditor && isManual ? 1 : 0)"
                class="px-3 py-12 text-center text-muted-foreground"
              >
                <BookMarked class="mx-auto size-8 opacity-50 mb-2" :stroke-width="1.5" />
                <p>暂无数据</p>
                <p v-if="isEditor && isManual" class="text-xs mt-1">点击"添加一行"开始创建术语</p>
                <p v-else-if="isEditor" class="text-xs mt-1">点击"从数据源同步"获取最新数据</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="total > pageSize" class="flex justify-center border-t p-3">
        <Pagination :page="page" :page-size="pageSize" :total="total" @change="handlePageChange" />
      </div>
    </Card>

    <div v-if="isEditor && isManual" class="mt-4 flex justify-end gap-2">
      <Button variant="outline" @click="goBack">取消</Button>
      <Button :disabled="saving" @click="saveAll">
        <Loader2 v-if="saving" class="size-4 animate-spin" :stroke-width="1.5" />
        保存全部修改
      </Button>
    </div>

    <!-- 字段别名编辑右侧半屏面板 -->
    <Transition name="slide-panel">
      <div v-if="aliasPanelOpen" class="fixed inset-0 z-50 flex justify-end">
        <!-- 遮罩 -->
        <div class="absolute inset-0 bg-black/30" @click="aliasPanelOpen = false"></div>
        <!-- 面板 -->
        <div class="relative w-full max-w-md bg-background shadow-xl flex flex-col h-full border-l">
          <div class="flex items-center justify-between border-b px-5 py-4">
            <div>
              <h3 class="text-base font-semibold">修改字段名称</h3>
              <p class="text-xs text-muted-foreground mt-0.5">修改显示名称，原始字段名保持不变以确保同步正确</p>
            </div>
            <Button variant="ghost" size="sm" class="h-8 w-8 p-0" @click="aliasPanelOpen = false">
              <X class="size-4" :stroke-width="1.5" />
            </Button>
          </div>

          <div class="flex-1 overflow-y-auto p-5 space-y-4">
            <!-- 表头 -->
            <div class="grid grid-cols-[1fr_1fr_auto] gap-3 pb-2 border-b text-xs font-medium text-muted-foreground">
              <span>新表头名称</span>
              <span>原始字段名</span>
              <span class="w-8"></span>
            </div>
            <!-- 字段列表 -->
            <div v-if="termBase" class="space-y-3">
              <div
                v-for="col in termBase.columns"
                :key="col.name"
                class="grid grid-cols-[1fr_1fr_auto] gap-3 items-center"
              >
                <Input
                  v-model="editingAliases[col.name]"
                  placeholder="输入显示名称"
                  size="sm"
                  class="h-8 text-sm"
                />
                <div class="flex h-8 items-center rounded-md border bg-muted/50 px-2 text-xs text-muted-foreground font-mono truncate" :title="col.name">
                  {{ col.name }}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                  title="重置为原始名称"
                  @click="resetAlias(col.name)"
                >
                  <X class="size-3" :stroke-width="1.5" />
                </Button>
              </div>
            </div>
            <div v-if="!termBase?.columns?.length" class="py-8 text-center text-sm text-muted-foreground">
              暂无字段
            </div>
          </div>

          <div class="border-t px-5 py-4 flex justify-end gap-2">
            <Button variant="outline" @click="aliasPanelOpen = false">取消</Button>
            <Button :disabled="aliasSaving" @click="saveAliases">
              <Check class="size-4" :stroke-width="1.5" />
              <Loader2 v-if="aliasSaving" class="ml-1 size-4 animate-spin" :stroke-width="1.5" />
              保存
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: opacity 0.25s ease;
}
.slide-panel-enter-active > div:last-child,
.slide-panel-leave-active > div:last-child {
  transition: transform 0.25s ease;
}
.slide-panel-enter-from,
.slide-panel-leave-to {
  opacity: 0;
}
.slide-panel-enter-from > div:last-child,
.slide-panel-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
