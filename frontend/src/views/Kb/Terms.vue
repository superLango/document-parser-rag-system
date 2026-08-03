<script setup lang="ts">
/**
 * 知识库术语库管理
 *
 * 功能：术语列表/创建/编辑/删除/批量导入/审核/分类过滤/导出
 * 数据隔离：/kbs/{kb_id}/terms，后端 RLS 强制
 * 权限：viewer 可查看；editor+ 可管理
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  BookMarked,
  Plus,
  RefreshCw,
  Loader2,
  Trash2,
  Search,
  Upload,
  Download,
  CheckCircle2,
  XCircle,
  Clock,
  Pencil,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'

interface TermItem {
  id: string
  term: string
  english_term?: string
  definition?: string
  category?: string
  standard_number?: string
  synonyms?: string[]
  status?: string
  created_at: string
  updated_at?: string
}

const route = useRoute()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const loading = ref(true)
const terms = ref<TermItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const statusFilter = ref('')
const categoryFilter = ref('')
const categories = ref<string[]>([])

// 编辑对话框
const dialogOpen = ref(false)
const editingTerm = ref<TermItem | null>(null)
const submitting = ref(false)
const form = ref({
  term: '',
  english_term: '',
  definition: '',
  category: '',
  standard_number: '',
  synonyms: [] as string[],
})
const synonymInput = ref('')

// 批量导入对话框
const importDialogOpen = ref(false)
const importText = ref('')
const importing = ref(false)

const statusConfig: Record<string, { label: string; color: string; icon: typeof Clock }> = {
  pending: { label: '待审核', color: 'bg-warning/10 text-warning', icon: Clock },
  approved: { label: '已审核', color: 'bg-success/10 text-success', icon: CheckCircle2 },
  rejected: { label: '已拒绝', color: 'bg-danger/10 text-danger', icon: XCircle },
}

async function fetchTerms() {
  loading.value = true
  try {
    const res = await kbApi.listTerms(kbId.value, {
      page: page.value,
      page_size: pageSize.value,
      status: statusFilter.value || undefined,
      category: categoryFilter.value || undefined,
      keyword: keyword.value || undefined,
    })
    terms.value = (res.items as unknown as TermItem[]) || []
    total.value = res.total
  } catch {
    terms.value = []
  } finally {
    loading.value = false
  }
}

async function fetchCategories() {
  try {
    categories.value = await kbApi.listTermCategories(kbId.value)
  } catch {
    categories.value = []
  }
}

function openCreate() {
  editingTerm.value = null
  form.value = {
    term: '',
    english_term: '',
    definition: '',
    category: '',
    standard_number: '',
    synonyms: [],
  }
  synonymInput.value = ''
  dialogOpen.value = true
}

function openEdit(term: TermItem) {
  editingTerm.value = term
  form.value = {
    term: term.term,
    english_term: term.english_term || '',
    definition: term.definition || '',
    category: term.category || '',
    standard_number: term.standard_number || '',
    synonyms: term.synonyms || [],
  }
  synonymInput.value = ''
  dialogOpen.value = true
}

function addSynonym() {
  const val = synonymInput.value.trim()
  if (val && !form.value.synonyms.includes(val)) {
    form.value.synonyms.push(val)
    synonymInput.value = ''
  }
}

function removeSynonym(idx: number) {
  form.value.synonyms.splice(idx, 1)
}

async function submitForm() {
  if (!form.value.term) {
    toast.warning('请填写术语名称')
    return
  }
  submitting.value = true
  try {
    if (editingTerm.value) {
      await kbApi.updateTerm(kbId.value, editingTerm.value.id, { ...form.value })
      toast.success('术语已更新', form.value.term)
    } else {
      await kbApi.createTerm(kbId.value, { ...form.value })
      toast.success('术语已创建', form.value.term)
    }
    dialogOpen.value = false
    await fetchTerms()
    await fetchCategories()
  } catch {
    // 错误已由拦截器提示
  } finally {
    submitting.value = false
  }
}

async function reviewTerm(term: TermItem, action: 'approve' | 'reject') {
  try {
    await kbApi.reviewTerm(kbId.value, term.id, action)
    toast.success(action === 'approve' ? '已审核通过' : '已拒绝', term.term)
    await fetchTerms()
  } catch {
    // 错误已由拦截器提示
  }
}

async function deleteTerm(term: TermItem) {
  if (!confirm(`确定删除术语「${term.term}」？`)) return
  try {
    await kbApi.deleteTerm(kbId.value, term.id)
    toast.success('已删除', term.term)
    await fetchTerms()
  } catch {
    // 错误已由拦截器提示
  }
}

function openImport() {
  importText.value = ''
  importDialogOpen.value = true
}

async function submitImport() {
  let data: Array<{ term: string; english_term?: string; definition?: string; category?: string; standard_number?: string; synonyms?: string[] }>
  try {
    data = JSON.parse(importText.value)
    if (!Array.isArray(data)) throw new Error('not array')
  } catch {
    toast.error('格式错误', '请输入合法的 JSON 数组')
    return
  }
  importing.value = true
  try {
    const res = await kbApi.batchImportTerms(kbId.value, data)
    toast.success('批量导入完成', `共导入 ${res.imported} 条`)
    importDialogOpen.value = false
    await fetchTerms()
    await fetchCategories()
  } catch {
    // 错误已由拦截器提示
  } finally {
    importing.value = false
  }
}

async function exportTerms() {
  try {
    const res = await kbApi.exportTerms(kbId.value)
    const blob = new Blob([JSON.stringify(res.items, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `terms_${kbId.value}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('已导出', `${res.total} 条术语`)
  } catch {
    // 错误已由拦截器提示
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

onMounted(() => {
  fetchCategories()
  fetchTerms()
})
</script>

<template>
  <div>
    <PageHeader title="术语库" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="fetchTerms">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button variant="outline" @click="exportTerms">
          <Download class="size-4" :stroke-width="1.5" />
          导出
        </Button>
        <Button v-if="isEditor" variant="outline" @click="openImport">
          <Upload class="size-4" :stroke-width="1.5" />
          批量导入
        </Button>
        <Button v-if="isEditor" @click="openCreate">
          <Plus class="size-4" :stroke-width="1.5" />
          新建术语
        </Button>
      </template>
    </PageHeader>

    <!-- 过滤栏 -->
    <Card class="mb-4">
      <CardContent class="flex flex-wrap items-center gap-3 p-3">
        <div class="relative min-w-[200px] flex-1">
          <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
          <Input v-model="keyword" placeholder="搜索术语 / 英文 / 定义" class="pl-8" @keyup.enter="handleSearch" />
        </div>
        <Select
          :model-value="statusFilter"
          :options="[
            { value: '', label: '全部状态' },
            { value: 'pending', label: '待审核' },
            { value: 'approved', label: '已审核' },
            { value: 'rejected', label: '已拒绝' },
          ]"
          class="w-32"
          @update:model-value="(v: string) => { statusFilter = v; handleSearch() }"
        />
        <Select
          :model-value="categoryFilter"
          :options="[
            { value: '', label: '全部分类' },
            ...categories.map((c) => ({ value: c, label: c })),
          ]"
          class="w-40"
          @update:model-value="(v: string) => { categoryFilter = v; handleSearch() }"
        />
        <Button variant="outline" size="sm" @click="handleSearch">
          <Search class="size-4" :stroke-width="1.5" />
          搜索
        </Button>
      </CardContent>
    </Card>

    <!-- 列表 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 5" :key="i" class="h-16 w-full" />
    </div>

    <EmptyState
      v-else-if="terms.length === 0"
      :icon="BookMarked"
      title="暂无术语"
      description="添加领域术语以提升 OCR 识别与抽取准确率"
      class="py-12"
    >
      <template v-if="isEditor" #actions>
        <Button @click="openCreate">
          <Plus class="size-4" :stroke-width="1.5" />
          新建术语
        </Button>
      </template>
    </EmptyState>

    <div v-else class="space-y-2">
      <Card v-for="term in terms" :key="term.id">
        <CardContent class="p-3">
          <div class="flex items-start gap-3">
            <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <BookMarked class="size-4" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <p class="font-medium text-foreground">{{ term.term }}</p>
                <span v-if="term.english_term" class="text-sm text-muted-foreground">{{ term.english_term }}</span>
                <Badge v-if="term.category" variant="outline" class="text-[10px]">{{ term.category }}</Badge>
                <Badge
                  v-if="term.status && statusConfig[term.status]"
                  variant="secondary"
                  :class="statusConfig[term.status].color"
                  class="text-[10px]"
                >
                  <component :is="statusConfig[term.status].icon" class="mr-0.5 size-3" :stroke-width="1.5" />
                  {{ statusConfig[term.status].label }}
                </Badge>
              </div>
              <p v-if="term.definition" class="mt-1 text-sm text-muted-foreground">{{ term.definition }}</p>
              <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <span v-if="term.standard_number">标准号: {{ term.standard_number }}</span>
                <span v-if="term.synonyms?.length">· 同义词: {{ term.synonyms.join('、') }}</span>
              </div>
            </div>
            <div v-if="isEditor" class="flex shrink-0 items-center gap-1">
              <Button v-if="term.status === 'pending'" variant="ghost" size="sm" title="审核通过" @click="reviewTerm(term, 'approve')">
                <CheckCircle2 class="size-4 text-success" :stroke-width="1.5" />
              </Button>
              <Button v-if="term.status === 'pending'" variant="ghost" size="sm" title="拒绝" @click="reviewTerm(term, 'reject')">
                <XCircle class="size-4 text-danger" :stroke-width="1.5" />
              </Button>
              <Button variant="ghost" size="sm" title="编辑" @click="openEdit(term)">
                <Pencil class="size-4" :stroke-width="1.5" />
              </Button>
              <Button variant="ghost" size="sm" title="删除" @click="deleteTerm(term)">
                <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="mt-4 flex justify-center">
      <Pagination :page="page" :page-size="pageSize" :total="total" @change="(p: number) => handlePageChange(p)" />
    </div>

    <!-- 创建/编辑对话框 -->
    <Dialog
      :open="dialogOpen"
      :title="editingTerm ? `编辑术语 · ${editingTerm.term}` : '新建术语'"
      class="max-w-xl"
      @update:open="(v: boolean) => (dialogOpen = v)"
    >
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label>术语名称 *</Label>
            <Input v-model="form.term" placeholder="中文术语" />
          </div>
          <div class="space-y-1.5">
            <Label>英文术语</Label>
            <Input v-model="form.english_term" placeholder="English term" />
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>定义</Label>
          <Textarea v-model="form.definition" placeholder="术语定义与说明" rows="2" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label>分类</Label>
            <Input v-model="form.category" placeholder="如：材料 / 性能 / 工艺" />
          </div>
          <div class="space-y-1.5">
            <Label>标准号</Label>
            <Input v-model="form.standard_number" placeholder="如：GB/T 1220" />
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>同义词</Label>
          <div class="flex gap-2">
            <Input v-model="synonymInput" placeholder="输入同义词后回车" @keyup.enter="addSynonym" />
            <Button variant="outline" size="sm" @click="addSynonym">添加</Button>
          </div>
          <div v-if="form.synonyms.length" class="flex flex-wrap gap-1.5">
            <Badge
              v-for="(s, i) in form.synonyms"
              :key="i"
              variant="secondary"
              class="cursor-pointer"
              @click="removeSynonym(i)"
            >
              {{ s }} ×
            </Badge>
          </div>
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="dialogOpen = false">取消</Button>
        <Button :disabled="submitting" @click="submitForm">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ editingTerm ? '保存' : '创建' }}
        </Button>
      </div>
    </Dialog>

    <!-- 批量导入对话框 -->
    <Dialog
      :open="importDialogOpen"
      title="批量导入术语"
      description="粘贴 JSON 数组，每项包含 term（必填）/ english_term / definition / category / standard_number / synonyms"
      class="max-w-2xl"
      @update:open="(v: boolean) => (importDialogOpen = v)"
    >
      <div class="space-y-3">
        <Textarea
          v-model="importText"
          placeholder='[{"term":"抗拉强度","english_term":"Tensile strength","category":"力学性能"}]'
          rows="10"
          class="font-mono text-xs"
        />
        <p class="text-xs text-muted-foreground">提示：可先导出现有术语作为模板，修改后导入。</p>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="importDialogOpen = false">取消</Button>
        <Button :disabled="importing" @click="submitImport">
          <Loader2 v-if="importing" class="size-4 animate-spin" :stroke-width="1.5" />
          导入
        </Button>
      </div>
    </Dialog>
  </div>
</template>
