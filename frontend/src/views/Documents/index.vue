<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  Upload,
  Search,
  Eye,
  Trash2,
  FileText,
  PlayCircle,
  Plus,
  X,
  Check,
} from 'lucide-vue-next'
import { documentApi } from '@/api/modules/document'
import { taskApi } from '@/api/modules/task'
import { schemaApi } from '@/api/modules/schema'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/ui/status-badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Tooltip } from '@/components/ui/tooltip'
import type { Document as DocType, Schema } from '@/api/types'

const router = useRouter()

// ---------- 文档列表 ----------
const loading = ref(true)
const documents = ref<DocType[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
})

async function fetchList() {
  loading.value = true
  try {
    const res = await documentApi.getList(query)
    documents.value = res.items
    total.value = res.total
  } catch {
    documents.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  query.page = 1
  fetchList()
}

function onPageChange(page: number) {
  query.page = page
  fetchList()
}

// ---------- 上传 ----------
// 后端上传端点仅接收 file 字段，filename/file_size/file_type 由后端从文件中提取
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const pendingFile = ref<File | null>(null)
const isDragOver = ref(false)

const MAX_FILE_SIZE = 50 * 1024 * 1024

function openUploadDialog() {
  uploadDialogVisible.value = true
  pendingFile.value = null
}

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) handleFile(input.files[0])
}

function onDrop(e: DragEvent) {
  isDragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

function handleFile(file: File) {
  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  if (!isPdf) {
    toast.error('格式不支持', '仅支持 PDF 格式文件')
    return
  }
  if (file.size > MAX_FILE_SIZE) {
    toast.error('文件过大', '文件大小不能超过 50MB')
    return
  }
  pendingFile.value = file
}

function removeFile() {
  pendingFile.value = null
}

async function submitUpload() {
  if (!pendingFile.value) {
    toast.warning('请选择文件', '请先添加 PDF 文件')
    return
  }
  uploading.value = true
  try {
    await documentApi.upload(pendingFile.value)
    toast.success('上传成功', '文档已添加到列表')
    uploadDialogVisible.value = false
    await fetchList()
  } catch {
    // 错误已由拦截器处理
  } finally {
    uploading.value = false
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

// ---------- 行操作 ----------
function viewDetail(doc: DocType) {
  router.push(`/parser/${doc.id}`)
}

async function handleDelete(doc: DocType) {
  if (!confirm(`确定删除文档「${doc.filename}」？\n删除后不可恢复。`)) return
  try {
    await documentApi.remove(doc.id)
    toast.success('已删除', '文档已从列表移除')
    await fetchList()
  } catch {
    // 错误已处理
  }
}

// ---------- 解析对话框 ----------
const parseDialogVisible = ref(false)
const parseDoc = ref<DocType | null>(null)
const schemaLoading = ref(false)
const schemas = ref<Schema[]>([])
const selectedSchemaId = ref<string>('')
const submittingParse = ref(false)
// 仅 OCR 解析（不依赖 Schema 进行结构化抽取）
const ocrOnly = ref(false)

const schemaOptions = computed(() =>
  schemas.value.map((s) => ({ value: String(s.id), label: s.name })),
)

async function openParseDialog(doc: DocType) {
  parseDoc.value = doc
  selectedSchemaId.value = ''
  ocrOnly.value = false
  parseDialogVisible.value = true

  schemaLoading.value = true
  try {
    // 仅加载父分类 Schema，子 Schema 由抽取页面统一合并使用
    const res = await schemaApi.getList({ only_parent: true })
    schemas.value = res.items
  } catch {
    schemas.value = []
  } finally {
    schemaLoading.value = false
  }
}

async function submitParse() {
  if (!parseDoc.value) return
  // 仅 OCR 模式下跳过 Schema 校验
  if (!ocrOnly.value && !selectedSchemaId.value) {
    toast.warning('请选择 Schema', '请先选择抽取 Schema，或勾选「仅 OCR 解析」')
    return
  }
  submittingParse.value = true
  try {
    const res = await taskApi.submit({
      document_id: String(parseDoc.value.id),
      schema_id: ocrOnly.value ? undefined : selectedSchemaId.value,
    })
    toast.success(
      '任务已提交',
      ocrOnly.value
        ? '已提交 OCR 解析任务（不进行结构化抽取）'
        : `任务 ID: ${res.task_id.slice(0, 8)}…`,
    )
    parseDialogVisible.value = false
    router.push(`/parser/${parseDoc.value.id}?task_id=${res.task_id}`)
  } catch {
    // 错误已处理
  } finally {
    submittingParse.value = false
  }
}

onMounted(fetchList)
</script>

<template>
  <div>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <PageHeader title="文档管理" description="上传技术标准文档并管理解析状态" />
      <Button class="mb-6 shrink-0 gap-2" @click="openUploadDialog">
        <Plus class="size-4" :stroke-width="1.5" />
        上传文档
      </Button>
    </div>

    <!-- 搜索栏 -->
    <Card class="mb-4">
      <CardContent class="flex items-center gap-2 p-3">
        <Search class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
        <Input
          v-model="query.keyword"
          placeholder="搜索文件名"
          class="h-8 flex-1 border-0 shadow-none focus-visible:ring-0"
          @keyup.enter="handleSearch"
        />
        <Button variant="outline" size="sm" class="h-8" @click="handleSearch">搜索</Button>
      </CardContent>
    </Card>

    <!-- 文档表格 -->
    <Card>
      <CardContent class="p-0">
        <!-- 表头 -->
        <div class="hidden grid-cols-12 gap-3 border-b border-border bg-muted/40 px-5 py-2.5 text-xs font-medium text-muted-foreground lg:grid">
          <div class="col-span-5">文件名</div>
          <div class="col-span-2">类型</div>
          <div class="col-span-2">状态</div>
          <div class="col-span-2">创建时间</div>
          <div class="col-span-1 text-right">操作</div>
        </div>

        <!-- 加载态 -->
        <div v-if="loading" class="divide-y divide-border">
          <div v-for="i in 5" :key="i" class="px-5 py-3">
            <Skeleton class="h-9 w-full" />
          </div>
        </div>

        <!-- 空态 -->
        <EmptyState
          v-else-if="documents.length === 0"
          :icon="FileText"
          title="暂无文档"
          description="点击右上角「上传文档」开始添加"
          class="py-12"
        />

        <!-- 列表 -->
        <ul v-else class="divide-y divide-border">
          <li
            v-for="doc in documents"
            :key="doc.id"
            class="grid grid-cols-1 gap-3 px-5 py-3 transition-colors hover:bg-muted/30 lg:grid-cols-12 lg:items-center"
          >
            <div class="min-w-0 lg:col-span-5">
              <button
                type="button"
                class="block w-full truncate text-left text-sm font-medium text-foreground hover:text-primary"
                @click="viewDetail(doc)"
              >
                {{ doc.filename }}
              </button>
              <div class="text-xs text-muted-foreground">{{ formatFileSize(doc.file_size) }}</div>
            </div>

            <div class="lg:col-span-2">
              <Badge v-if="doc.file_type" variant="outline" class="font-mono text-[10px] uppercase">
                {{ doc.file_type }}
              </Badge>
              <span v-else class="text-xs text-muted-foreground">-</span>
            </div>

            <div class="lg:col-span-2">
              <StatusBadge :status="doc.status" kind="document" />
            </div>

            <div class="font-mono text-xs text-muted-foreground lg:col-span-2">
              {{ formatTime(doc.created_at) }}
            </div>

            <div class="flex justify-end gap-1 lg:col-span-1">
              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="查看"
                    @click="viewDetail(doc)"
                  >
                    <Eye class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>查看详情</span>
              </Tooltip>

              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    aria-label="解析"
                    @click="openParseDialog(doc)"
                  >
                    <PlayCircle class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>开始解析</span>
              </Tooltip>

              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                    aria-label="删除"
                    @click="handleDelete(doc)"
                  >
                    <Trash2 class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>删除</span>
              </Tooltip>
            </div>
          </li>
        </ul>

        <!-- 分页 -->
        <div class="flex items-center justify-between border-t border-border px-5 py-3">
          <div class="text-xs text-muted-foreground">共 {{ total }} 条</div>
          <Pagination
            :page="query.page"
            :page-size="query.page_size"
            :total="total"
            @update:page="onPageChange"
          />
        </div>
      </CardContent>
    </Card>

    <!-- 上传对话框 -->
    <Dialog v-model:open="uploadDialogVisible" title="上传文档" description="支持 PDF 格式，最大 50MB">
      <div class="space-y-4 pt-2">
        <!-- 文件选择区 -->
        <div v-if="!pendingFile">
          <label
            class="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-8 text-center transition-colors hover:bg-muted/60 hover:border-primary"
            :class="{ 'border-primary bg-primary/5': isDragOver }"
            @dragover.prevent="isDragOver = true"
            @dragleave="isDragOver = false"
            @drop.prevent="onDrop"
          >
            <Upload class="size-7 text-muted-foreground" :stroke-width="1.5" />
            <div class="text-sm font-medium text-foreground">拖拽 PDF 文件到此处</div>
            <div class="text-xs text-muted-foreground">或点击此处选择文件</div>
            <input type="file" accept="application/pdf,.pdf" class="hidden" @change="onFileSelect" />
          </label>
        </div>

        <!-- 已选文件 -->
        <div v-else class="flex items-center gap-3 rounded-md border border-border bg-muted/30 p-3">
          <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileText class="size-4" :stroke-width="1.5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-foreground">{{ pendingFile.name }}</div>
            <div class="font-mono text-xs text-muted-foreground">{{ formatFileSize(pendingFile.size) }}</div>
          </div>
          <button
            type="button"
            class="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            @click="removeFile"
          >
            <X class="size-4" :stroke-width="1.5" />
          </button>
        </div>

        <!-- 操作按钮 -->
        <div class="flex justify-end gap-2 pt-2">
          <Button variant="outline" :disabled="uploading" @click="uploadDialogVisible = false">
            取消
          </Button>
          <Button :disabled="uploading" class="gap-2" @click="submitUpload">
            <Check v-if="!uploading" class="size-4" :stroke-width="1.5" />
            <span>{{ uploading ? '上传中...' : '确认上传' }}</span>
          </Button>
        </div>
      </div>
    </Dialog>

    <!-- 解析对话框 -->
    <Dialog v-model:open="parseDialogVisible" title="开始解析" :description="parseDoc?.filename">
      <div class="space-y-4 pt-2">
        <!-- OCR 模式开关 -->
        <label
          class="flex cursor-pointer items-start gap-2.5 rounded-md border border-border bg-muted/30 p-3 transition-colors hover:bg-muted/50"
        >
          <input
            v-model="ocrOnly"
            type="checkbox"
            class="mt-0.5 size-3.5 rounded border-border text-primary focus:ring-primary"
          />
          <div class="flex-1">
            <div class="text-sm font-medium text-foreground">仅 OCR 解析</div>
            <p class="mt-0.5 text-xs text-muted-foreground">
              仅执行 OCR 文字识别与版面分析，不依赖 Schema 进行结构化字段抽取
            </p>
          </div>
        </label>

        <div v-if="!ocrOnly" class="space-y-1.5">
          <Label>抽取 Schema <span class="text-destructive">*</span></Label>
          <Select
            v-model="selectedSchemaId"
            :options="schemaOptions"
            placeholder="请选择抽取 Schema"
          />
          <p v-if="schemaLoading" class="text-xs text-muted-foreground">加载中...</p>
          <p v-else-if="schemas.length === 0" class="text-xs text-destructive">
            暂无可用 Schema，请先到「抽取 Schema」页面创建
          </p>
        </div>

        <div class="flex justify-end gap-2 pt-2">
          <Button variant="outline" :disabled="submittingParse" @click="parseDialogVisible = false">
            取消
          </Button>
          <Button :disabled="submittingParse" class="gap-2" @click="submitParse">
            <PlayCircle v-if="!submittingParse" class="size-4" :stroke-width="1.5" />
            <span>{{ submittingParse ? '提交中...' : '提交解析' }}</span>
          </Button>
        </div>
      </div>
    </Dialog>
  </div>
</template>
