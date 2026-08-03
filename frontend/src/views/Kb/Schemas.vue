<script setup lang="ts">
/**
 * 知识库 Schema 管理
 *
 * 功能：父子层级 Schema 管理（父分类 + 子 Schema）/ 创建/编辑/删除/启停/复制
 * 数据隔离：/kbs/{kb_id}/schemas，后端 RLS 强制
 * 权限：viewer 可查看；editor+ 可管理
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Database,
  Plus,
  RefreshCw,
  Loader2,
  Trash2,
  Copy,
  ChevronRight,
  ChevronDown,
  FolderTree,
  FileBox,
  Power,
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
import { Switch } from '@/components/ui/switch'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'

interface SchemaItem {
  id: string
  parent_id: string | null
  name: string
  description: string
  doc_type?: string
  fields?: Record<string, unknown>[]
  sample_fields?: Record<string, unknown>
  is_active: boolean
  sort_order: number
  is_parent: boolean
  children_count?: number
  created_at: string
  updated_at: string
}

const route = useRoute()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const loading = ref(true)
const categories = ref<SchemaItem[]>([])
const expandedIds = ref<Set<string>>(new Set())
const childrenMap = ref<Record<string, SchemaItem[]>>({})

// 对话框
const dialogOpen = ref(false)
const dialogMode = ref<'create_category' | 'create_schema' | 'edit'>('create_category')
const editingItem = ref<SchemaItem | null>(null)
const parentItem = ref<SchemaItem | null>(null)
const submitting = ref(false)
const form = ref({
  name: '',
  description: '',
  doc_type: '',
  is_active: true,
  sort_order: 0,
})

// 复制对话框
const copyDialogOpen = ref(false)
const copySource = ref<SchemaItem | null>(null)
const copyName = ref('')

async function fetchCategories() {
  loading.value = true
  try {
    const res = await kbApi.listSchemas(kbId.value, { only_parent: true })
    categories.value = (res.items as unknown as SchemaItem[]) || []
    // 自动展开第一个
    if (categories.value.length > 0) {
      expandedIds.value.add(categories.value[0].id)
      await loadChildren(categories.value[0].id)
    }
  } catch {
    categories.value = []
  } finally {
    loading.value = false
  }
}

async function loadChildren(parentId: string) {
  if (childrenMap.value[parentId]) return
  try {
    const children = await kbApi.listSchemaChildren(kbId.value, parentId)
    childrenMap.value[parentId] = (children as unknown as SchemaItem[]) || []
  } catch {
    childrenMap.value[parentId] = []
  }
}

function toggleExpand(item: SchemaItem) {
  if (expandedIds.value.has(item.id)) {
    expandedIds.value.delete(item.id)
  } else {
    expandedIds.value.add(item.id)
    loadChildren(item.id)
  }
}

function openCreateCategory() {
  dialogMode.value = 'create_category'
  editingItem.value = null
  parentItem.value = null
  form.value = { name: '', description: '', doc_type: '', is_active: true, sort_order: 0 }
  dialogOpen.value = true
}

function openCreateSchema(parent: SchemaItem) {
  dialogMode.value = 'create_schema'
  editingItem.value = null
  parentItem.value = parent
  form.value = { name: '', description: '', doc_type: '', is_active: true, sort_order: 0 }
  dialogOpen.value = true
}

function openEdit(item: SchemaItem, parent: SchemaItem | null) {
  dialogMode.value = 'edit'
  editingItem.value = item
  parentItem.value = parent
  form.value = {
    name: item.name,
    description: item.description || '',
    doc_type: item.doc_type || '',
    is_active: item.is_active,
    sort_order: item.sort_order,
  }
  dialogOpen.value = true
}

async function submitForm() {
  if (!form.value.name) {
    toast.warning('请填写名称')
    return
  }
  submitting.value = true
  try {
    if (dialogMode.value === 'create_category') {
      await kbApi.createSchema(kbId.value, {
        name: form.value.name,
        description: form.value.description || undefined,
        is_active: form.value.is_active,
        sort_order: form.value.sort_order,
      })
      toast.success('父分类已创建', form.value.name)
    } else if (dialogMode.value === 'create_schema' && parentItem.value) {
      await kbApi.createSchema(kbId.value, {
        name: form.value.name,
        description: form.value.description || undefined,
        doc_type: form.value.doc_type || undefined,
        parent_id: parentItem.value.id,
        is_active: form.value.is_active,
        sort_order: form.value.sort_order,
      })
      toast.success('子 Schema 已创建', form.value.name)
      // 刷新子列表
      delete childrenMap.value[parentItem.value.id]
      expandedIds.value.add(parentItem.value.id)
      await loadChildren(parentItem.value.id)
    } else if (dialogMode.value === 'edit' && editingItem.value) {
      await kbApi.updateSchema(kbId.value, editingItem.value.id, {
        name: form.value.name,
        description: form.value.description,
        doc_type: form.value.doc_type,
        is_active: form.value.is_active,
        sort_order: form.value.sort_order,
      })
      toast.success('已更新', form.value.name)
    }
    dialogOpen.value = false
    await fetchCategories()
  } catch {
    // 错误已由拦截器提示
  } finally {
    submitting.value = false
  }
}

async function toggleActive(item: SchemaItem) {
  try {
    await kbApi.toggleSchemaActive(kbId.value, item.id, !item.is_active)
    toast.success(item.is_active ? '已停用' : '已启用', item.name)
    await fetchCategories()
    // 清理子缓存
    if (childrenMap.value[item.id]) delete childrenMap.value[item.id]
  } catch {
    // 错误已由拦截器提示
  }
}

function openCopy(item: SchemaItem) {
  copySource.value = item
  copyName.value = `${item.name} 副本`
  copyDialogOpen.value = true
}

async function submitCopy() {
  if (!copySource.value || !copyName.value) {
    toast.warning('请填写新名称')
    return
  }
  submitting.value = true
  try {
    await kbApi.copySchema(kbId.value, copySource.value.id, copyName.value)
    toast.success('已复制', copyName.value)
    copyDialogOpen.value = false
    await fetchCategories()
  } catch {
    // 错误已由拦截器提示
  } finally {
    submitting.value = false
  }
}

async function deleteItem(item: SchemaItem) {
  if (!confirm(`确定删除「${item.name}」？${item.is_parent ? '其下所有子 Schema 也将被删除。' : ''}`)) return
  try {
    await kbApi.deleteSchema(kbId.value, item.id)
    toast.success('已删除', item.name)
    await fetchCategories()
    if (childrenMap.value[item.id]) delete childrenMap.value[item.id]
  } catch {
    // 错误已由拦截器提示
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

onMounted(fetchCategories)
</script>

<template>
  <div>
    <PageHeader title="Schema 管理" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="fetchCategories">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button v-if="isEditor" @click="openCreateCategory">
          <Plus class="size-4" :stroke-width="1.5" />
          新建分类
        </Button>
      </template>
    </PageHeader>

    <!-- 说明 -->
    <Card class="mb-4">
      <CardContent class="p-4 text-sm text-muted-foreground">
        <div class="flex items-start gap-2">
          <FolderTree class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
          <div>
            <p>Schema 采用父子层级结构：<strong class="text-foreground">父分类</strong>定义文档类别（如「拉伸试验」），<strong class="text-foreground">子 Schema</strong>定义具体字段抽取规则。</p>
            <p class="mt-1 text-xs">抽取时按父分类合并所有子 Schema 字段，实现多分类联合抽取。</p>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 加载态 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 3" :key="i" class="h-16 w-full" />
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="categories.length === 0"
      :icon="Database"
      title="暂无 Schema"
      description="创建父分类后即可添加子 Schema 字段定义"
      class="py-12"
    >
      <template v-if="isEditor" #actions>
        <Button @click="openCreateCategory">
          <Plus class="size-4" :stroke-width="1.5" />
          新建分类
        </Button>
      </template>
    </EmptyState>

    <!-- Schema 树 -->
    <div v-else class="space-y-2">
      <template v-for="cat in categories" :key="cat.id">
        <!-- 父分类 -->
        <Card>
          <CardContent class="flex items-center gap-3 p-3">
            <button
              class="flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted"
              @click="toggleExpand(cat)"
            >
              <ChevronDown v-if="expandedIds.has(cat.id)" class="size-4" :stroke-width="1.5" />
              <ChevronRight v-else class="size-4" :stroke-width="1.5" />
            </button>
            <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <FolderTree class="size-4" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <p class="font-medium text-foreground">{{ cat.name }}</p>
                <Badge variant="secondary" class="text-[10px]">{{ cat.children_count || 0 }} 子 Schema</Badge>
                <Badge
                  v-if="!cat.is_active"
                  variant="secondary"
                  class="bg-danger/10 text-danger text-[10px]"
                >
                  已停用
                </Badge>
              </div>
              <p v-if="cat.description" class="mt-0.5 truncate text-xs text-muted-foreground">{{ cat.description }}</p>
            </div>
            <div v-if="isEditor" class="flex shrink-0 items-center gap-1">
              <Button variant="ghost" size="sm" title="添加子 Schema" @click="openCreateSchema(cat)">
                <Plus class="size-4" :stroke-width="1.5" />
              </Button>
              <Button variant="ghost" size="sm" title="复制" @click="openCopy(cat)">
                <Copy class="size-4" :stroke-width="1.5" />
              </Button>
              <Button variant="ghost" size="sm" :title="cat.is_active ? '停用' : '启用'" @click="toggleActive(cat)">
                <Power class="size-4" :class="{ 'text-danger': cat.is_active }" :stroke-width="1.5" />
              </Button>
              <Button variant="ghost" size="sm" title="编辑" @click="openEdit(cat, null)">
                <FileBox class="size-4" :stroke-width="1.5" />
              </Button>
              <Button variant="ghost" size="sm" title="删除" @click="deleteItem(cat)">
                <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
              </Button>
            </div>
          </CardContent>
        </Card>

        <!-- 子 Schema 列表 -->
        <div v-if="expandedIds.has(cat.id)" class="ml-6 space-y-2 border-l border-border pl-3">
          <div v-if="childrenMap[cat.id] === undefined" class="py-2 text-center text-xs text-muted-foreground">
            <Loader2 class="inline size-3 animate-spin" :stroke-width="1.5" /> 加载中...
          </div>
          <div v-else-if="childrenMap[cat.id]?.length === 0" class="py-2 text-center text-xs text-muted-foreground">
            暂无子 Schema
          </div>
          <Card
            v-for="child in childrenMap[cat.id]"
            v-else
            :key="child.id"
            class="bg-muted/20"
          >
            <CardContent class="flex items-center gap-3 p-2.5">
              <div class="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                <FileBox class="size-4" :stroke-width="1.5" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <p class="text-sm font-medium text-foreground">{{ child.name }}</p>
                  <Badge v-if="child.doc_type" variant="outline" class="text-[10px]">{{ child.doc_type }}</Badge>
                  <Badge
                    v-if="!child.is_active"
                    variant="secondary"
                    class="bg-danger/10 text-danger text-[10px]"
                  >
                    已停用
                  </Badge>
                </div>
                <p v-if="child.description" class="mt-0.5 truncate text-xs text-muted-foreground">{{ child.description }}</p>
              </div>
              <div v-if="isEditor" class="flex shrink-0 items-center gap-1">
                <Button variant="ghost" size="sm" :title="child.is_active ? '停用' : '启用'" @click="toggleActive(child)">
                  <Power class="size-3.5" :class="{ 'text-danger': child.is_active }" :stroke-width="1.5" />
                </Button>
                <Button variant="ghost" size="sm" title="编辑" @click="openEdit(child, cat)">
                  <FileBox class="size-3.5" :stroke-width="1.5" />
                </Button>
                <Button variant="ghost" size="sm" title="删除" @click="deleteItem(child)">
                  <Trash2 class="size-3.5 text-danger" :stroke-width="1.5" />
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </template>
    </div>

    <!-- 创建/编辑对话框 -->
    <Dialog
      :open="dialogOpen"
      :title="dialogMode === 'create_category' ? '新建父分类' : dialogMode === 'create_schema' ? `新建子 Schema · ${parentItem?.name}` : `编辑 · ${editingItem?.name}`"
      @update:open="(v: boolean) => (dialogOpen = v)"
    >
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>名称 *</Label>
          <Input v-model="form.name" placeholder="Schema 名称" />
        </div>
        <div class="space-y-1.5">
          <Label>描述</Label>
          <Textarea v-model="form.description" placeholder="Schema 用途说明" rows="2" />
        </div>
        <div v-if="dialogMode !== 'create_category'" class="space-y-1.5">
          <Label>文档类型</Label>
          <Input v-model="form.doc_type" placeholder="如：试验报告 / 质保书" />
        </div>
        <div class="flex items-center gap-6">
          <label class="flex items-center gap-2 text-sm">
            <Switch :model-value="form.is_active" @update:model-value="(v: boolean) => (form.is_active = v)" />
            启用
          </label>
          <div class="flex items-center gap-2 text-sm">
            <Label class="m-0">排序</Label>
            <Input v-model.number="form.sort_order" type="number" class="w-20" />
          </div>
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="dialogOpen = false">取消</Button>
        <Button :disabled="submitting" @click="submitForm">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ dialogMode === 'edit' ? '保存' : '创建' }}
        </Button>
      </div>
    </Dialog>

    <!-- 复制对话框 -->
    <Dialog
      :open="copyDialogOpen"
      title="复制 Schema"
      :description="`复制「${copySource?.name}」为新 Schema`"
      @update:open="(v: boolean) => (copyDialogOpen = v)"
    >
      <div class="space-y-3">
        <div class="space-y-1.5">
          <Label>新名称</Label>
          <Input v-model="copyName" placeholder="新 Schema 名称" />
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="copyDialogOpen = false">取消</Button>
        <Button :disabled="submitting" @click="submitCopy">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          复制
        </Button>
      </div>
    </Dialog>
  </div>
</template>
