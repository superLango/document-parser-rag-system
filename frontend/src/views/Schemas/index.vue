<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import {
  Plus,
  Pencil,
  Trash2,
  Braces,
  Eye,
  Loader2,
  X,
  ChevronRight,
  FolderPlus,
  Folder,
  Code2,
  Layers,
} from 'lucide-vue-next'
import { schemaApi } from '@/api/modules/schema'
import type { Schema, SchemaField, SchemaCreate } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Tooltip } from '@/components/ui/tooltip'

// ---------- 父分类列表 ----------
const loading = ref(true)
const categories = ref<Schema[]>([])
// 当前展开的父分类 ID
const expandedCategoryId = ref<string | null>(null)
// 各父分类下的子 Schema 缓存
const childrenMap = ref<Record<string, Schema[]>>({})
// 子 Schema 加载状态
const loadingChildren = ref<Record<string, boolean>>({})

async function fetchCategories() {
  loading.value = true
  try {
    const data = await schemaApi.listCategories()
    categories.value = data
    // 自动展开第一个父分类
    if (data.length > 0 && !expandedCategoryId.value) {
      await toggleCategory(data[0].id)
    }
  } catch {
    categories.value = []
  } finally {
    loading.value = false
  }
}

async function toggleCategory(categoryId: string) {
  if (expandedCategoryId.value === categoryId) {
    expandedCategoryId.value = null
    return
  }
  expandedCategoryId.value = categoryId
  // 加载子 Schema（如果尚未加载）
  if (!childrenMap.value[categoryId]) {
    loadingChildren.value[categoryId] = true
    try {
      const children = await schemaApi.listChildren(categoryId)
      childrenMap.value[categoryId] = children
    } catch {
      childrenMap.value[categoryId] = []
    } finally {
      loadingChildren.value[categoryId] = false
    }
  }
}

async function refreshChildren(categoryId: string) {
  loadingChildren.value[categoryId] = true
  try {
    const children = await schemaApi.listChildren(categoryId)
    childrenMap.value[categoryId] = children
    // 同时刷新父分类的 children_count
    const cat = categories.value.find((c) => c.id === categoryId)
    if (cat) {
      cat.children_count = children.length
    }
  } catch {
    // 错误已处理
  } finally {
    loadingChildren.value[categoryId] = false
  }
}

// 当前展开父分类的子 Schema 列表
const currentChildren = computed(() => {
  if (!expandedCategoryId.value) return []
  return childrenMap.value[expandedCategoryId.value] || []
})

// ---------- 字段类型选项 ----------
const fieldTypeOptions = [
  { value: 'string', label: '字符串' },
  { value: 'number', label: '数字' },
  { value: 'boolean', label: '布尔' },
  { value: 'date', label: '日期' },
  { value: 'enum', label: '枚举' },
  { value: 'array', label: '数组' },
]

// ---------- 新建/编辑对话框 ----------
const dialogVisible = ref(false)
const submitting = ref(false)
// dialogMode: 'create_category' | 'create_schema' | 'edit'
const dialogMode = ref<'create_category' | 'create_schema' | 'edit'>('create_schema')
const editingSchema = ref<Schema | null>(null)
// 当前对话框所属的父分类 ID（用于创建子 Schema）
const currentParentId = ref<string | null>(null)

const form = reactive<{
  name: string
  description: string
  doc_type: string
  parent_id: string | null
  fields: SchemaField[]
  sample_fields_text: string
  is_active: boolean
  sort_order: number
}>({
  name: '',
  description: '',
  doc_type: '',
  parent_id: null,
  fields: [{ name: '', description: '', field_type: 'string', required: true }],
  sample_fields_text: '',
  is_active: true,
  sort_order: 0,
})

function openCreateCategory() {
  dialogMode.value = 'create_category'
  editingSchema.value = null
  currentParentId.value = null
  form.name = ''
  form.description = ''
  form.doc_type = ''
  form.parent_id = null
  form.fields = []
  form.sample_fields_text = ''
  form.is_active = true
  form.sort_order = 0
  dialogVisible.value = true
}

function openCreateSchema(parentId: string) {
  dialogMode.value = 'create_schema'
  editingSchema.value = null
  currentParentId.value = parentId
  form.name = ''
  form.description = ''
  form.doc_type = ''
  form.parent_id = parentId
  form.fields = [{ name: '', description: '', field_type: 'string', required: true }]
  form.sample_fields_text = ''
  form.is_active = true
  form.sort_order = 0
  dialogVisible.value = true
}

async function openEdit(schema: Schema) {
  try {
    const detail = await schemaApi.getDetail(schema.id)
    editingSchema.value = detail
    dialogMode.value = 'edit'
    currentParentId.value = detail.parent_id
    form.name = detail.name
    form.description = detail.description
    form.doc_type = detail.doc_type
    form.parent_id = detail.parent_id
    form.fields = detail.fields.length
      ? detail.fields.map((f) => ({ ...f }))
      : [{ name: '', description: '', field_type: 'string', required: false }]
    // sample_fields 序列化为可编辑 JSON 文本
    try {
      form.sample_fields_text =
        Object.keys(detail.sample_fields || {}).length > 0
          ? JSON.stringify(detail.sample_fields, null, 2)
          : ''
    } catch {
      form.sample_fields_text = ''
    }
    form.is_active = detail.is_active
    form.sort_order = detail.sort_order || 0
    dialogVisible.value = true
  } catch {
    // 错误已处理
  }
}

function addField() {
  form.fields.push({ name: '', description: '', field_type: 'string', required: false })
}

function removeField(index: number) {
  if (form.fields.length <= 1) return
  form.fields.splice(index, 1)
}

// 父分类选项（用于编辑时切换所属分类）
const parentCategoryOptions = computed(() => [
  { value: '', label: '（作为父分类）' },
  ...categories.value.map((c) => ({ value: c.id, label: c.name })),
])

// 当前对话框是否为父分类模式
const isCategoryMode = computed(
  () => dialogMode.value === 'create_category' ||
    (dialogMode.value === 'edit' && editingSchema.value?.is_parent),
)

async function submit() {
  if (!form.name.trim()) {
    toast.warning('请填写名称', '名称不能为空')
    return
  }

  // 父分类不需要字段定义
  if (!isCategoryMode.value) {
    if (!form.fields.length || !form.fields.some((f) => f.name.trim())) {
      toast.warning('请添加至少一个字段', '需要至少一个有效字段')
      return
    }
  }

  // 解析 sample_fields
  let sample_fields: Record<string, string | string[]> = {}
  if (form.sample_fields_text.trim()) {
    try {
      const parsed = JSON.parse(form.sample_fields_text)
      if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
        sample_fields = parsed
      } else {
        throw new Error('示例字段必须是 JSON 对象')
      }
    } catch (err) {
      toast.warning('示例字段格式错误', err instanceof Error ? err.message : '请检查 JSON 格式')
      return
    }
  }

  const payload: SchemaCreate = {
    name: form.name.trim(),
    description: form.description.trim(),
    doc_type: form.doc_type.trim(),
    fields: isCategoryMode.value
      ? []
      : form.fields
          .filter((f) => f.name.trim())
          .map((f) => ({
            name: f.name.trim(),
            description: f.description?.trim() || '',
            field_type: f.field_type,
            required: f.required,
          })),
    sample_fields,
    parent_id: form.parent_id || null,
    is_active: form.is_active,
    sort_order: form.sort_order,
  }

  submitting.value = true
  try {
    if (editingSchema.value) {
      await schemaApi.update(editingSchema.value.id, payload)
      toast.success('已更新', `「${payload.name}」已保存`)
      // 刷新所属父分类的子 Schema 列表
      if (editingSchema.value.parent_id) {
        await refreshChildren(editingSchema.value.parent_id)
      } else {
        // 父分类本身修改，刷新父分类列表
        await fetchCategories()
      }
    } else {
      await schemaApi.create(payload)
      toast.success('已创建', `「${payload.name}」已添加`)
      // 刷新对应列表
      if (payload.parent_id) {
        await refreshChildren(payload.parent_id)
      } else {
        await fetchCategories()
      }
    }
    dialogVisible.value = false
  } catch {
    // 错误已处理
  } finally {
    submitting.value = false
  }
}

// ---------- 删除 ----------
const deleteDialogVisible = ref(false)
const deleteTarget = ref<Schema | null>(null)
const deleting = ref(false)

function openDeleteDialog(schema: Schema) {
  deleteTarget.value = schema
  deleteDialogVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await schemaApi.remove(deleteTarget.value.id)
    toast.success('已删除', `「${deleteTarget.value.name}」已移除`)
    deleteDialogVisible.value = false
    // 刷新对应列表
    if (deleteTarget.value.parent_id) {
      await refreshChildren(deleteTarget.value.parent_id)
    } else {
      await fetchCategories()
    }
  } catch {
    // 错误已处理
  } finally {
    deleting.value = false
  }
}

// ---------- 启用/停用 ----------
async function handleToggleActive(schema: Schema, active: boolean) {
  try {
    await schemaApi.toggleActive(schema.id, active)
    schema.is_active = active
    toast.success(active ? '已启用' : '已停用', `「${schema.name}」状态已更新`)
  } catch {
    // 错误已处理
  }
}

// ---------- 详情对话框 ----------
const detailDialogVisible = ref(false)
const detailSchema = ref<Schema | null>(null)

function openDetail(schema: Schema) {
  detailSchema.value = schema
  detailDialogVisible.value = true
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

onMounted(fetchCategories)
</script>

<template>
  <div>
    <PageHeader
      title="抽取 Schema"
      description="父子层级管理 Schema 分类与字段定义，作为 LangExtract 抽取依据"
    >
      <template #actions>
        <Button variant="outline" @click="openCreateCategory">
          <FolderPlus class="size-4" :stroke-width="1.5" />
          新建分类
        </Button>
        <Button
          :disabled="!expandedCategoryId"
          @click="expandedCategoryId && openCreateSchema(expandedCategoryId)"
        >
          <Plus class="size-4" :stroke-width="1.5" />
          新建 Schema
        </Button>
      </template>
    </PageHeader>

    <!-- 加载态 -->
    <div v-if="loading" class="space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-20 w-full" />
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="categories.length === 0"
      :icon="Braces"
      title="暂无 Schema 分类"
      description="点击右上角「新建分类」开始定义 Schema 父分类"
      class="py-16"
    >
      <Button size="sm" class="mt-2" @click="openCreateCategory">
        <FolderPlus class="size-3.5" :stroke-width="1.5" />
        新建分类
      </Button>
    </EmptyState>

    <!-- 父分类列表 -->
    <div v-else class="space-y-3">
      <Card
        v-for="category in categories"
        :key="category.id"
        :class="[
          'overflow-hidden transition-colors',
          expandedCategoryId === category.id ? 'border-primary/40' : '',
        ]"
      >
        <!-- 父分类头部 -->
        <CardContent class="flex items-center gap-3 p-4">
          <button
            type="button"
            class="flex min-w-0 flex-1 items-center gap-3 text-left"
            @click="toggleCategory(category.id)"
          >
            <div
              :class="[
                'flex size-9 shrink-0 items-center justify-center rounded-md transition-colors',
                expandedCategoryId === category.id
                  ? 'bg-primary/15 text-primary'
                  : 'bg-muted text-muted-foreground',
              ]"
            >
              <Folder class="size-4" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-base font-medium text-foreground">{{ category.name }}</span>
                <Badge variant="secondary" class="gap-1 text-[10px]">
                  <Layers class="size-3" :stroke-width="1.5" />
                  {{ category.children_count || 0 }} Schema
                </Badge>
                <Badge
                  v-if="category.is_active"
                  variant="success"
                  class="text-[10px]"
                >
                  启用
                </Badge>
                <Badge v-else variant="secondary" class="text-[10px]">停用</Badge>
              </div>
              <p class="mt-0.5 truncate text-xs text-muted-foreground">
                {{ category.description || '暂无描述' }}
              </p>
            </div>
          </button>

          <!-- 父分类操作 -->
          <div class="flex items-center gap-1">
            <Tooltip :side="'top'">
              <template #trigger>
                <button
                  type="button"
                  class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                  aria-label="添加子 Schema"
                  @click="openCreateSchema(category.id)"
                >
                  <Plus class="size-3.5" :stroke-width="1.5" />
                </button>
              </template>
              <span>添加子 Schema</span>
            </Tooltip>

            <Tooltip :side="'top'">
              <template #trigger>
                <button
                  type="button"
                  class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  aria-label="编辑分类"
                  @click="openEdit(category)"
                >
                  <Pencil class="size-3.5" :stroke-width="1.5" />
                </button>
              </template>
              <span>编辑分类</span>
            </Tooltip>

            <Tooltip :side="'top'">
              <template #trigger>
                <button
                  type="button"
                  class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                  aria-label="删除分类"
                  @click="openDeleteDialog(category)"
                >
                  <Trash2 class="size-3.5" :stroke-width="1.5" />
                </button>
              </template>
              <span>删除分类</span>
            </Tooltip>

            <Switch
              :checked="category.is_active"
              @update:checked="(val) => handleToggleActive(category, val)"
            />
          </div>
        </CardContent>

        <!-- 子 Schema 列表（展开时显示） -->
        <div
          v-if="expandedCategoryId === category.id"
          class="border-t border-border bg-muted/10 p-3"
        >
          <!-- 加载中 -->
          <div v-if="loadingChildren[category.id]" class="space-y-2 py-2">
            <Skeleton v-for="i in 2" :key="i" class="h-16 w-full" />
          </div>

          <!-- 子 Schema 空态 -->
          <EmptyState
            v-else-if="!currentChildren.length"
            :icon="Braces"
            title="该分类下暂无子 Schema"
            description="点击「添加子 Schema」按钮开始定义字段"
            class="py-8"
          >
            <Button size="sm" variant="outline" @click="openCreateSchema(category.id)">
              <Plus class="size-3.5" :stroke-width="1.5" />
              添加子 Schema
            </Button>
          </EmptyState>

          <!-- 子 Schema 卡片网格 -->
          <div v-else class="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
            <div
              v-for="child in currentChildren"
              :key="child.id"
              class="group flex items-start gap-3 rounded-md border border-border bg-card p-3 transition-colors hover:border-primary/40"
            >
              <!-- 字段图标 -->
              <div class="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Code2 class="size-4" :stroke-width="1.5" />
              </div>

              <!-- 主要信息 -->
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    class="truncate text-left text-sm font-medium text-foreground hover:text-primary"
                    @click="openDetail(child)"
                  >
                    {{ child.name }}
                  </button>
                  <Badge variant="outline" class="text-[10px]">
                    {{ child.fields.length }} 字段
                  </Badge>
                  <Badge
                    v-if="child.is_active"
                    variant="success"
                    class="text-[10px]"
                  >
                    启用
                  </Badge>
                  <Badge v-else variant="secondary" class="text-[10px]">停用</Badge>
                </div>
                <p class="mt-0.5 truncate text-xs text-muted-foreground">
                  {{ child.description || '暂无描述' }}
                </p>
                <!-- 字段标签预览 -->
                <div v-if="child.fields.length" class="mt-1.5 flex flex-wrap gap-1">
                  <span
                    v-for="f in child.fields.slice(0, 4)"
                    :key="f.name"
                    class="inline-flex items-center rounded bg-muted/60 px-1 py-0.5 font-mono text-[10px] text-muted-foreground"
                  >
                    {{ f.name }}
                    <span v-if="f.required" class="ml-0.5 text-danger">*</span>
                  </span>
                  <span
                    v-if="child.fields.length > 4"
                    class="inline-flex items-center px-1 text-[10px] text-muted-foreground/70"
                  >
                    +{{ child.fields.length - 4 }}
                  </span>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="flex items-center gap-0.5">
                <Tooltip :side="'top'">
                  <template #trigger>
                    <button
                      type="button"
                      class="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      aria-label="查看详情"
                      @click="openDetail(child)"
                    >
                      <Eye class="size-3" :stroke-width="1.5" />
                    </button>
                  </template>
                  <span>查看详情</span>
                </Tooltip>

                <Tooltip :side="'top'">
                  <template #trigger>
                    <button
                      type="button"
                      class="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                      aria-label="编辑"
                      @click="openEdit(child)"
                    >
                      <Pencil class="size-3" :stroke-width="1.5" />
                    </button>
                  </template>
                  <span>编辑 Schema</span>
                </Tooltip>

                <Tooltip :side="'top'">
                  <template #trigger>
                    <button
                      type="button"
                      class="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                      aria-label="删除"
                      @click="openDeleteDialog(child)"
                    >
                      <Trash2 class="size-3" :stroke-width="1.5" />
                    </button>
                  </template>
                  <span>删除 Schema</span>
                </Tooltip>

                <Switch
                  :checked="child.is_active"
                  @update:checked="(val) => handleToggleActive(child, val)"
                />
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>

    <!-- 新建/编辑对话框 -->
    <Dialog
      :open="dialogVisible"
      :title="
        dialogMode === 'create_category'
          ? '新建分类'
          : dialogMode === 'create_schema'
            ? '新建子 Schema'
            : '编辑'
      "
      :description="
        dialogMode === 'create_category'
          ? '创建一个 Schema 分类容器，子 Schema 将归属此分类'
          : dialogMode === 'create_schema'
            ? `在当前分类下添加子 Schema，定义字段规则与示例`
            : '修改 Schema 的字段定义或所属分类'
      "
      class="max-w-3xl"
      @update:open="(v) => (dialogVisible = v)"
    >
      <div class="space-y-4">
        <!-- 基本信息 -->
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label for="schema-name">名称 <span class="text-danger">*</span></Label>
            <Input
              id="schema-name"
              v-model="form.name"
              :placeholder="isCategoryMode ? '如：GB/T 标准字段' : '如：化学成分分析'"
            />
          </div>
          <div class="space-y-1.5">
            <Label for="schema-doc-type">文档类型</Label>
            <Input
              id="schema-doc-type"
              v-model="form.doc_type"
              placeholder="如：gbt_standard"
              class="font-mono"
              :disabled="isCategoryMode"
            />
            <p v-if="isCategoryMode" class="text-[10px] text-muted-foreground">
              父分类不需要文档类型
            </p>
          </div>
        </div>

        <div class="space-y-1.5">
          <Label for="schema-desc">描述</Label>
          <Textarea
            id="schema-desc"
            v-model="form.description"
            :rows="2"
            placeholder="简要描述用途"
          />
        </div>

        <!-- 所属分类选择（仅编辑模式可选） -->
        <div v-if="dialogMode === 'edit'" class="grid grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <Label for="schema-parent">所属分类</Label>
            <Select
              v-model="form.parent_id"
              :options="parentCategoryOptions"
              class="h-9"
            />
            <p class="text-[10px] text-muted-foreground">
              留空表示这是一个父分类节点
            </p>
          </div>
          <div class="space-y-1.5">
            <Label for="schema-sort">排序权重</Label>
            <Input
              id="schema-sort"
              v-model.number="form.sort_order"
              type="number"
              placeholder="0"
              class="font-mono"
            />
          </div>
        </div>

        <!-- 启用开关 -->
        <div class="flex items-center gap-3">
          <Switch
            :checked="form.is_active"
            @update:checked="(val) => (form.is_active = val)"
          />
          <Label class="cursor-pointer text-sm">
            启用此 Schema
            <span class="ml-1 text-xs text-muted-foreground">
              （停用后不会被 LangExtract 抽取使用）
            </span>
          </Label>
        </div>

        <!-- 字段构建器（仅子 Schema 模式显示） -->
        <div v-if="!isCategoryMode" class="space-y-2">
          <div class="flex items-center justify-between">
            <Label>字段定义 <span class="text-danger">*</span></Label>
            <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="addField">
              <Plus class="size-3.5" :stroke-width="1.5" />
              添加字段
            </Button>
          </div>

          <div class="space-y-2">
            <div
              v-for="(field, idx) in form.fields"
              :key="idx"
              class="grid grid-cols-12 items-end gap-2 rounded-md border border-border bg-muted/20 p-3"
            >
              <!-- 字段名 -->
              <div class="col-span-12 space-y-1.5 sm:col-span-4">
                <Label class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  字段名
                </Label>
                <Input
                  v-model="field.name"
                  placeholder="如：standard_number"
                  class="h-8 font-mono text-xs"
                />
              </div>

              <!-- 类型 -->
              <div class="col-span-6 space-y-1.5 sm:col-span-3">
                <Label class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  类型
                </Label>
                <Select
                  v-model="field.field_type"
                  :options="fieldTypeOptions"
                  class="h-8"
                />
              </div>

              <!-- 必填 -->
              <div class="col-span-6 space-y-1.5 sm:col-span-2">
                <Label class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  必填
                </Label>
                <div class="flex h-8 items-center gap-2">
                  <Switch
                    :checked="field.required"
                    @update:checked="(val) => (field.required = val)"
                  />
                  <span class="text-xs text-muted-foreground">
                    {{ field.required ? '是' : '否' }}
                  </span>
                </div>
              </div>

              <!-- 删除按钮 -->
              <div class="col-span-12 flex items-end justify-end sm:col-span-3">
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-8 w-full gap-1.5 text-muted-foreground hover:text-danger"
                  :disabled="form.fields.length <= 1"
                  @click="removeField(idx)"
                >
                  <Trash2 class="size-3.5" :stroke-width="1.5" />
                  移除
                </Button>
              </div>

              <!-- 描述（整行） -->
              <div class="col-span-12 space-y-1.5">
                <Label class="text-[10px] uppercase tracking-wide text-muted-foreground">
                  描述
                </Label>
                <Input
                  v-model="field.description"
                  placeholder="字段说明"
                  class="h-8 text-xs"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 抽取示例（仅子 Schema 模式显示） -->
        <div v-if="!isCategoryMode" class="space-y-1.5">
          <div class="flex items-center justify-between">
            <Label for="schema-sample">抽取示例</Label>
            <Tooltip :side="'left'">
              <template #trigger>
                <span class="text-[10px] text-muted-foreground">使用说明</span>
              </template>
              <span class="block max-w-xs text-xs">
                JSON 对象格式，作为 LangExtract 的抽取依据，<br />
                例如：<code>{ "standard_number": "GB/T 1220-2007" }</code>
              </span>
            </Tooltip>
          </div>
          <Textarea
            id="schema-sample"
            v-model="form.sample_fields_text"
            :rows="5"
            placeholder='{ "standard_number": "GB/T 1220-2007", "chemical_composition": "C: ≤0.08%" }'
            class="font-mono text-xs"
          />
          <p class="text-[10px] text-muted-foreground">
            可选。填写后会被合并到父分类的整体 Schema 中作为 LangExtract 抽取依据
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="dialogVisible = false">取消</Button>
        <Button :disabled="submitting" @click="submit">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ editingSchema ? '保存修改' : (isCategoryMode ? '创建分类' : '创建 Schema') }}
        </Button>
      </div>
    </Dialog>

    <!-- 详情对话框 -->
    <Dialog
      :open="detailDialogVisible"
      :title="detailSchema?.name || 'Schema 详情'"
      :description="detailSchema?.description || '查看 Schema 详细信息'"
      class="max-w-2xl"
      @update:open="(v) => (detailDialogVisible = v)"
    >
      <div v-if="detailSchema" class="space-y-4">
        <!-- 元信息 -->
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1 rounded-md border border-border bg-muted/20 p-3">
            <p class="text-[10px] uppercase tracking-wide text-muted-foreground">类型</p>
            <div class="flex items-center gap-2">
              <Badge :variant="detailSchema.is_parent ? 'default' : 'secondary'" class="text-[10px]">
                {{ detailSchema.is_parent ? '父分类' : '子 Schema' }}
              </Badge>
            </div>
          </div>
          <div class="space-y-1 rounded-md border border-border bg-muted/20 p-3">
            <p class="text-[10px] uppercase tracking-wide text-muted-foreground">状态</p>
            <div class="flex items-center gap-2">
              <Badge :variant="detailSchema.is_active ? 'success' : 'secondary'" class="text-[10px]">
                {{ detailSchema.is_active ? '启用' : '停用' }}
              </Badge>
            </div>
          </div>
          <div class="space-y-1 rounded-md border border-border bg-muted/20 p-3">
            <p class="text-[10px] uppercase tracking-wide text-muted-foreground">创建时间</p>
            <p class="text-xs text-foreground">{{ formatTime(detailSchema.created_at) }}</p>
          </div>
          <div class="space-y-1 rounded-md border border-border bg-muted/20 p-3">
            <p class="text-[10px] uppercase tracking-wide text-muted-foreground">更新时间</p>
            <p class="text-xs text-foreground">{{ formatTime(detailSchema.updated_at) }}</p>
          </div>
        </div>

        <!-- 字段列表（子 Schema 才显示） -->
        <div v-if="!detailSchema.is_parent && detailSchema.fields.length" class="space-y-2">
          <div class="flex items-center justify-between">
            <h4 class="text-sm font-medium text-foreground">字段列表</h4>
            <Badge variant="secondary" class="text-[10px]">
              共 {{ detailSchema.fields.length }} 个字段
            </Badge>
          </div>

          <div class="overflow-hidden rounded-md border border-border">
            <table class="w-full text-sm">
              <thead class="bg-muted/40 text-left text-xs text-muted-foreground">
                <tr>
                  <th class="px-3 py-2 font-medium">字段名</th>
                  <th class="px-3 py-2 font-medium">类型</th>
                  <th class="px-3 py-2 font-medium">必填</th>
                  <th class="px-3 py-2 font-medium">描述</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr
                  v-for="field in detailSchema.fields"
                  :key="field.name"
                  class="transition-colors hover:bg-muted/30"
                >
                  <td class="px-3 py-2 font-mono text-xs text-foreground">
                    {{ field.name }}
                    <span v-if="field.required" class="text-danger">*</span>
                  </td>
                  <td class="px-3 py-2">
                    <Badge variant="outline" class="font-mono text-[10px]">
                      {{ field.field_type }}
                    </Badge>
                  </td>
                  <td class="px-3 py-2">
                    <Badge
                      :variant="field.required ? 'danger' : 'secondary'"
                      class="text-[10px]"
                    >
                      {{ field.required ? '是' : '否' }}
                    </Badge>
                  </td>
                  <td class="max-w-[200px] truncate px-3 py-2 text-xs text-muted-foreground" :title="field.description">
                    {{ field.description || '-' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 抽取示例 -->
        <div v-if="!detailSchema.is_parent && detailSchema.sample_fields && Object.keys(detailSchema.sample_fields).length" class="space-y-1.5">
          <h4 class="text-sm font-medium text-foreground">抽取示例</h4>
          <pre class="overflow-x-auto rounded-md border border-border bg-muted/20 p-3 font-mono text-xs text-foreground">{{ JSON.stringify(detailSchema.sample_fields, null, 2) }}</pre>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="detailDialogVisible = false">关闭</Button>
        <Button
          v-if="detailSchema"
          @click="detailDialogVisible = false; openEdit(detailSchema)"
        >
          <Pencil class="size-4" :stroke-width="1.5" />
          编辑
        </Button>
      </div>
    </Dialog>

    <!-- 删除确认对话框 -->
    <Dialog
      :open="deleteDialogVisible"
      :title="deleteTarget?.is_parent ? '删除分类确认' : '删除 Schema 确认'"
      :description="`即将删除「${deleteTarget?.name}」`"
      @update:open="(v) => (deleteDialogVisible = v)"
    >
      <div v-if="deleteTarget" class="space-y-3">
        <div class="flex items-start gap-3 rounded-md border border-warning/30 bg-warning/5 p-3">
          <X class="mt-0.5 size-4 shrink-0 text-warning" :stroke-width="1.5" />
          <div class="flex-1 space-y-1 text-sm">
            <p class="text-foreground">
              即将删除
              <span class="font-mono text-xs font-medium">{{ deleteTarget.name }}</span>
            </p>
            <p v-if="deleteTarget.is_parent" class="text-xs text-muted-foreground">
              父分类下若仍有子 Schema，将无法删除。请先删除子 Schema 或迁移到其他分类。
            </p>
            <p v-else class="text-xs text-muted-foreground">
              删除后该 Schema 将无法用于新文档的抽取任务，但已抽取的文档数据不受影响。该操作不可恢复。
            </p>
          </div>
        </div>
        <div v-if="!deleteTarget.is_parent && deleteTarget.fields.length" class="space-y-1">
          <p class="text-xs font-medium text-muted-foreground">将影响以下字段：</p>
          <div class="flex flex-wrap gap-1">
            <Badge
              v-for="field in deleteTarget.fields.slice(0, 8)"
              :key="field.name"
              variant="outline"
              class="font-mono text-[10px]"
            >
              {{ field.name }}
            </Badge>
            <span v-if="deleteTarget.fields.length > 8" class="text-[10px] text-muted-foreground">
              +{{ deleteTarget.fields.length - 8 }}
            </span>
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
