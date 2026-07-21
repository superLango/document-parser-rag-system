<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import {
  Search,
  Plus,
  Pencil,
  Trash2,
  BookText,
  Upload,
  Loader2,
  X,
  Check,
} from 'lucide-vue-next'
import { termApi } from '@/api/modules/term'
import type { Term, TermCreate } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Tooltip } from '@/components/ui/tooltip'
import { Pagination } from '@/components/ui/pagination'

// ---------- 列表 ----------
const loading = ref(true)
const terms = ref<Term[]>([])
const total = ref(0)
const ALL_CATEGORY = '__all__'
const query = reactive({
  keyword: '',
  category: ALL_CATEGORY,
  page: 1,
  page_size: 20,
})

const categories = ref<string[]>([])
const categoryOptions = computed(() => [
  { value: ALL_CATEGORY, label: '全部分类' },
  ...categories.value.map((c) => ({ value: c, label: c })),
])

async function loadCategories() {
  try {
    categories.value = await termApi.getCategories()
  } catch {
    categories.value = []
  }
}

async function fetchList() {
  loading.value = true
  try {
    const res = await termApi.getList({
      keyword: query.keyword.trim() || undefined,
      category: query.category === ALL_CATEGORY ? undefined : query.category,
      page: query.page,
      page_size: query.page_size,
    })
    terms.value = res.items
    total.value = res.total
  } catch {
    terms.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  query.page = 1
  fetchList()
}

function handlePageChange(page: number) {
  query.page = page
  fetchList()
}

// ---------- 新增 / 编辑 ----------
const dialogVisible = ref(false)
const editingTerm = ref<Term | null>(null)
const submitting = ref(false)
const form = reactive({
  term: '',
  english_term: '',
  definition: '',
  category: '',
  standard_number: '',
  synonyms: '',
})

function resetForm() {
  form.term = ''
  form.english_term = ''
  form.definition = ''
  form.category = ''
  form.standard_number = ''
  form.synonyms = ''
}

function openCreate() {
  editingTerm.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: Term) {
  editingTerm.value = row
  form.term = row.term
  form.english_term = row.english_term || ''
  form.definition = row.definition || ''
  form.category = row.category || ''
  form.standard_number = row.standard_number || ''
  form.synonyms = (row.synonyms || []).join(', ')
  dialogVisible.value = true
}

async function submit() {
  if (!form.term.trim()) {
    toast.warning('请填写术语名', '术语名不能为空')
    return
  }
  if (!form.definition.trim()) {
    toast.warning('请填写定义', '定义不能为空')
    return
  }
  if (!form.category.trim()) {
    toast.warning('请选择分类', '分类不能为空')
    return
  }

  const payload: TermCreate = {
    term: form.term.trim(),
    english_term: form.english_term.trim() || undefined,
    definition: form.definition.trim(),
    category: form.category.trim(),
    standard_number: form.standard_number.trim() || undefined,
    synonyms: form.synonyms
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  }

  submitting.value = true
  try {
    if (editingTerm.value) {
      await termApi.update(editingTerm.value.id, payload)
      toast.success('已更新', `术语「${payload.term}」已保存`)
    } else {
      await termApi.create(payload)
      toast.success('已创建', `术语「${payload.term}」已添加`)
    }
    dialogVisible.value = false
    await fetchList()
    await loadCategories()
  } catch {
    // 错误已处理
  } finally {
    submitting.value = false
  }
}

// ---------- 删除 ----------
const deleteDialogVisible = ref(false)
const deleteTarget = ref<Term | null>(null)
const deleting = ref(false)

function openDeleteDialog(row: Term) {
  deleteTarget.value = row
  deleteDialogVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await termApi.remove(deleteTarget.value.id)
    toast.success('已删除', `术语「${deleteTarget.value.term}」已移除`)
    deleteDialogVisible.value = false
    await fetchList()
  } catch {
    // 错误已处理
  } finally {
    deleting.value = false
  }
}

// ---------- 批量导入 ----------
const importDialogVisible = ref(false)
const importText = ref('')
const importing = ref(false)

function openImport() {
  importText.value = ''
  importDialogVisible.value = true
}

async function handleImport() {
  let data: TermCreate[]
  try {
    data = JSON.parse(importText.value)
    if (!Array.isArray(data)) {
      throw new Error('not array')
    }
  } catch {
    toast.error('JSON 格式错误', '请粘贴有效的 JSON 数组')
    return
  }

  importing.value = true
  try {
    const res = await termApi.batchImport(data)
    toast.success('导入完成', `共导入 ${res.imported} 条术语`)
    importDialogVisible.value = false
    await fetchList()
    await loadCategories()
  } catch {
    // 错误已处理
  } finally {
    importing.value = false
  }
}

// ---------- 工具函数 ----------
function formatSynonyms(synonyms: string[] | undefined): string {
  if (!synonyms || synonyms.length === 0) return ''
  return synonyms.join('、')
}

function formatTime(value: string | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

onMounted(() => {
  loadCategories()
  fetchList()
})
</script>

<template>
  <div>
    <PageHeader title="术语库" description="技术标准术语的检索与统一管理">
      <template #actions>
        <Button variant="outline" @click="openImport">
          <Upload class="size-4" :stroke-width="1.5" />
          批量导入
        </Button>
        <Button @click="openCreate">
          <Plus class="size-4" :stroke-width="1.5" />
          新增术语
        </Button>
      </template>
    </PageHeader>

    <!-- 搜索栏 -->
    <Card class="mb-4">
      <CardContent class="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <div class="relative flex-1">
          <Search
            class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            :stroke-width="1.5"
          />
          <Input
            v-model="query.keyword"
            placeholder="搜索术语、英文、同义词"
            class="pl-9"
            @keyup.enter="handleSearch"
          />
        </div>
        <Select
          v-model="query.category"
          :options="categoryOptions"
          placeholder="选择分类"
          class="sm:w-[200px]"
          @update:model-value="handleSearch"
        />
        <Button class="sm:w-[88px]" @click="handleSearch">
          <Search class="size-4" :stroke-width="1.5" />
          查询
        </Button>
      </CardContent>
    </Card>

    <!-- 术语列表 -->
    <Card>
      <CardContent class="p-0">
        <!-- 表头 -->
        <div
          class="hidden grid-cols-12 gap-3 border-b border-border bg-muted/40 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground lg:grid"
        >
          <div class="col-span-2">术语</div>
          <div class="col-span-2">英文</div>
          <div class="col-span-4">定义</div>
          <div class="col-span-1">分类</div>
          <div class="col-span-2">标准号</div>
          <div class="col-span-1 text-right">操作</div>
        </div>

        <!-- 加载态 -->
        <div v-if="loading" class="divide-y divide-border">
          <div
            v-for="i in 6"
            :key="i"
            class="grid grid-cols-12 gap-3 px-4 py-3"
          >
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-4 h-5" />
            <Skeleton class="col-span-1 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-1 h-5" />
          </div>
        </div>

        <!-- 空态 -->
        <EmptyState
          v-else-if="terms.length === 0"
          :icon="BookText"
          title="暂无术语"
          description="点击右上角「新增术语」开始构建术语库，或使用批量导入快速录入"
          class="py-16"
        />

        <!-- 数据行 -->
        <div v-else class="divide-y divide-border">
          <div
            v-for="term in terms"
            :key="term.id"
            class="grid grid-cols-12 gap-3 px-4 py-3 transition-colors hover:bg-muted/30"
          >
            <!-- 术语名 -->
            <div class="col-span-12 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">术语</div>
              <span class="font-medium text-foreground">{{ term.term }}</span>
            </div>

            <!-- 英文 -->
            <div class="col-span-6 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">英文</div>
              <span class="font-mono text-sm text-muted-foreground">
                {{ term.english_term || '-' }}
              </span>
            </div>

            <!-- 定义 -->
            <div class="col-span-12 lg:col-span-4">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">定义</div>
              <p class="line-clamp-2 text-sm text-muted-foreground" :title="term.definition">
                {{ term.definition || '-' }}
              </p>
              <div v-if="formatSynonyms(term.synonyms)" class="mt-1 flex flex-wrap gap-1">
                <span
                  v-for="syn in term.synonyms"
                  :key="syn"
                  class="inline-flex items-center rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {{ syn }}
                </span>
              </div>
            </div>

            <!-- 分类 -->
            <div class="col-span-6 lg:col-span-1">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">分类</div>
              <Badge v-if="term.category" variant="outline" class="text-[10px]">
                {{ term.category }}
              </Badge>
              <span v-else class="text-muted-foreground">-</span>
            </div>

            <!-- 标准号 -->
            <div class="col-span-12 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">标准号</div>
              <span class="font-mono text-sm text-muted-foreground">
                {{ term.standard_number || '-' }}
              </span>
            </div>

            <!-- 操作 -->
            <div class="col-span-12 flex items-center justify-end gap-1 lg:col-span-1">
              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    aria-label="编辑"
                    @click="openEdit(term)"
                  >
                    <Pencil class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>编辑术语</span>
              </Tooltip>
              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                    aria-label="删除"
                    @click="openDeleteDialog(term)"
                  >
                    <Trash2 class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>删除术语</span>
              </Tooltip>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div
          v-if="total > 0"
          class="flex items-center justify-between border-t border-border px-4 py-3"
        >
          <p class="text-xs text-muted-foreground">共 {{ total }} 条</p>
          <Pagination
            :current-page="query.page"
            :page-size="query.page_size"
            :total="total"
            @current-change="handlePageChange"
          />
        </div>
      </CardContent>
    </Card>

    <!-- 新增/编辑 Dialog -->
    <Dialog
      :open="dialogVisible"
      :title="editingTerm ? '编辑术语' : '新增术语'"
      :description="editingTerm ? `修改术语「${editingTerm.term}」` : '录入术语信息并指定分类'"
      class="max-w-xl"
      @update:open="(v) => (dialogVisible = v)"
    >
      <div class="space-y-4">
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label for="term-name">术语名 <span class="text-danger">*</span></Label>
            <Input
              id="term-name"
              v-model="form.term"
              placeholder="如：术语标准"
            />
          </div>
          <div class="space-y-1.5">
            <Label for="term-en">英文</Label>
            <Input
              id="term-en"
              v-model="form.english_term"
              placeholder="如：terminology"
              class="font-mono"
            />
          </div>
        </div>

        <div class="space-y-1.5">
          <Label for="term-def">定义 <span class="text-danger">*</span></Label>
          <Textarea
            id="term-def"
            v-model="form.definition"
            :rows="3"
            placeholder="术语的详细定义"
          />
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label for="term-cat">分类 <span class="text-danger">*</span></Label>
            <Input
              id="term-cat"
              v-model="form.category"
              placeholder="如：通用、机械、电气"
              list="term-category-list"
            />
            <datalist id="term-category-list">
              <option v-for="cat in categories" :key="cat" :value="cat" />
            </datalist>
          </div>
          <div class="space-y-1.5">
            <Label for="term-std">标准号</Label>
            <Input
              id="term-std"
              v-model="form.standard_number"
              placeholder="如：GB/T 1.1-2020"
              class="font-mono"
            />
          </div>
        </div>

        <div class="space-y-1.5">
          <Label for="term-syn">同义词</Label>
          <Input
            id="term-syn"
            v-model="form.synonyms"
            placeholder="多个同义词用逗号分隔"
          />
          <p class="text-xs text-muted-foreground">
            输入多个同义词时请使用英文或中文逗号分隔
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="dialogVisible = false">取消</Button>
        <Button :disabled="submitting" @click="submit">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ editingTerm ? '保存修改' : '创建术语' }}
        </Button>
      </div>
    </Dialog>

    <!-- 批量导入 Dialog -->
    <Dialog
      :open="importDialogVisible"
      title="批量导入术语"
      description="粘贴 JSON 数组以批量录入术语"
      class="max-w-2xl"
      @update:open="(v) => (importDialogVisible = v)"
    >
      <div class="space-y-3">
        <div class="flex items-start gap-3 rounded-md border border-primary/30 bg-primary/5 p-3">
          <Check class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
          <div class="flex-1 space-y-1 text-sm">
            <p class="font-medium text-foreground">JSON 数组格式示例</p>
            <pre class="overflow-x-auto rounded bg-muted/60 p-2 font-mono text-[11px] text-muted-foreground">[{ "term": "术语", "definition": "定义", "category": "分类" }]</pre>
            <p class="text-xs text-muted-foreground">
              支持字段：term（必填）、definition（必填）、category（必填）、english_term、standard_number、synonyms
            </p>
          </div>
        </div>

        <Textarea
          v-model="importText"
          :rows="12"
          placeholder='[{ "term": "术语", "definition": "定义", "category": "分类" }]'
          class="font-mono text-xs"
        />
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="importDialogVisible = false">取消</Button>
        <Button :disabled="importing || !importText.trim()" @click="handleImport">
          <Loader2 v-if="importing" class="size-4 animate-spin" :stroke-width="1.5" />
          <Upload v-else class="size-4" :stroke-width="1.5" />
          导入
        </Button>
      </div>
    </Dialog>

    <!-- 删除确认 Dialog -->
    <Dialog
      :open="deleteDialogVisible"
      title="删除术语确认"
      :description="`即将删除术语「${deleteTarget?.term}」`"
      @update:open="(v) => (deleteDialogVisible = v)"
    >
      <div v-if="deleteTarget" class="space-y-3">
        <div class="flex items-start gap-3 rounded-md border border-warning/30 bg-warning/5 p-3">
          <X class="mt-0.5 size-4 shrink-0 text-warning" :stroke-width="1.5" />
          <div class="flex-1 space-y-1 text-sm">
            <p class="text-foreground">
              即将删除术语
              <span class="font-medium">{{ deleteTarget.term }}</span>
            </p>
            <p class="text-xs text-muted-foreground">
              删除后该术语将不再用于后续解析任务的术语标准化，该操作不可恢复。
            </p>
          </div>
        </div>

        <div v-if="deleteTarget.synonyms?.length" class="space-y-1">
          <p class="text-xs font-medium text-muted-foreground">同义词：</p>
          <div class="flex flex-wrap gap-1">
            <Badge
              v-for="syn in deleteTarget.synonyms"
              :key="syn"
              variant="outline"
              class="text-[10px]"
            >
              {{ syn }}
            </Badge>
          </div>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="deleteDialogVisible = false">取消</Button>
        <Button variant="destructive" :disabled="deleting" @click="confirmDelete">
          <Trash2 class="size-4" :stroke-width="1.5" />
          确认删除
        </Button>
      </div>
    </Dialog>
  </div>
</template>
