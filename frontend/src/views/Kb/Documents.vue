<script setup lang="ts">
/**
 * 知识库文档管理页
 *
 * 功能：上传/列表/下载/删除/发起解析/批量操作/文件预览/导出
 * 数据隔离：所有操作通过 /kbs/{kb_id}/documents，后端 RLS 强制隔离
 * 权限：viewer 可查看/下载/预览；editor+ 可上传/删除/解析/批量操作
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Upload,
  Download,
  Trash2,
  FileText,
  Loader2,
  RefreshCw,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  Eye,
  FileDown,
  Layers,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { useBatchSelection } from '@/composables/useBatchSelection'
import { downloadBlob, stampFilename } from '@/composables/useDownload'
import type { Document } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import BatchActionbar from '@/components/common/BatchActionbar.vue'
import DocumentPreviewDialog from '@/components/document/DocumentPreviewDialog.vue'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const loading = ref(true)
const documents = ref<Document[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref<string>('')
const uploading = ref(false)
const parseTarget = ref<Document | null>(null)
const batchLoading = ref(false)

// 预览对话框
const previewOpen = ref(false)
const previewDoc = ref<Document | null>(null)

// 批量选择
const sel = useBatchSelection<Document>({ idKey: 'id' })
const visibleIds = computed(() => documents.value.map((d) => d.id))

const statusConfig: Record<string, { color: string; icon: typeof Clock; label: string }> = {
  pending: { color: 'bg-muted text-muted-foreground', icon: Clock, label: '待处理' },
  processing: { color: 'bg-warning/10 text-warning', icon: Loader2, label: '处理中' },
  completed: { color: 'bg-success/10 text-success', icon: CheckCircle2, label: '已完成' },
  failed: { color: 'bg-danger/10 text-danger', icon: XCircle, label: '失败' },
}

async function fetchDocuments() {
  loading.value = true
  try {
    const res = await kbApi.listDocuments(kbId.value, {
      page: page.value,
      page_size: pageSize.value,
      status: statusFilter.value || undefined,
    })
    documents.value = res.items
    total.value = res.total
  } catch {
    documents.value = []
  } finally {
    loading.value = false
  }
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return
  uploading.value = true
  try {
    const files = Array.from(input.files)
    if (files.length === 1) {
      await kbApi.uploadDocument(kbId.value, files[0])
      toast.success('上传成功', files[0].name)
    } else {
      const res = await kbApi.batchUploadDocuments(kbId.value, files)
      const failList = res.results.filter(r => !r.ok)
      if (failList.length === 0) {
        toast.success('批量上传完成', `成功 ${res.success} 个文件`)
      } else {
        toast.warning('批量上传完成', `成功 ${res.success} 个，失败 ${res.failed} 个`)
        console.warn('上传失败文件:', failList)
      }
    }
    input.value = ''
    await fetchDocuments()
  } catch {
    // 错误已由拦截器提示
  } finally {
    uploading.value = false
  }
}

async function handleDownload(doc: Document) {
  try {
    const blob = await kbApi.downloadDocument(kbId.value, doc.id)
    downloadBlob(blob, doc.filename)
  } catch {
    // 错误已由拦截器提示
  }
}

async function handlePreview(doc: Document) {
  // 已完成解析的文档，跳转到全屏查看页面
  if (doc.status === 'completed') {
    router.push({ name: 'KbDocumentViewer', params: { kb_id: kbId.value, doc_id: doc.id } })
    return
  }
  // 未解析/失败/处理中的文档，使用弹窗预览
  previewDoc.value = doc
  previewOpen.value = true
}

async function handleDelete(doc: Document) {
  if (!confirm(`确定删除文档「${doc.filename}」？此操作不可恢复。`)) return
  try {
    await kbApi.deleteDocument(kbId.value, doc.id)
    toast.success('已删除', doc.filename)
    await fetchDocuments()
  } catch {
    // 错误已由拦截器提示
  }
}

async function handleParse(doc: Document) {
  parseTarget.value = doc
  try {
    await kbApi.submitParseTask(kbId.value, doc.id, {})
    toast.success('解析任务已提交', doc.filename)
    await fetchDocuments()
  } catch {
    // 错误已由拦截器提示
  } finally {
    parseTarget.value = null
  }
}

// ---------- 批量操作 ----------
async function handleBatchDelete() {
  const ids = sel.getSelectedIds()
  if (ids.length === 0) return
  if (!confirm(`确定批量删除 ${ids.length} 个文档？此操作不可恢复。`)) return
  batchLoading.value = true
  try {
    const res = await kbApi.batchDeleteDocuments(kbId.value, ids)
    toast.success('批量删除完成', `成功 ${res.success} 个，失败 ${res.failed} 个`)
    sel.clear()
    await fetchDocuments()
  } catch {
    // 错误已由拦截器提示
  } finally {
    batchLoading.value = false
  }
}

async function handleBatchParse() {
  const ids = sel.getSelectedIds()
  if (ids.length === 0) return
  batchLoading.value = true
  try {
    const res = await kbApi.batchParseDocuments(kbId.value, ids)
    toast.success('批量解析已提交', `成功 ${res.success} 个，失败 ${res.failed} 个`)
    sel.clear()
    await fetchDocuments()
  } catch {
    // 错误已由拦截器提示
  } finally {
    batchLoading.value = false
  }
}

async function handleExport(format: 'excel' | 'csv' | 'json') {
  try {
    const blob = await kbApi.exportDocuments(kbId.value, {
      format,
      status: statusFilter.value || undefined,
    })
    downloadBlob(blob, stampFilename('documents', format === 'excel' ? 'xlsx' : format))
    toast.success('导出成功')
  } catch {
    // 错误已由拦截器提示
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(value: string | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

onMounted(fetchDocuments)
</script>

<template>
  <div>
    <PageHeader title="文档管理" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="fetchDocuments">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button variant="outline" @click="handleExport('excel')">
          <FileDown class="size-4" :stroke-width="1.5" />
          导出
        </Button>
        <label v-if="isEditor">
          <input
            type="file"
            multiple
            class="hidden"
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp"
            @change="handleUpload"
          />
          <Button :disabled="uploading" as="span" class="cursor-pointer">
            <Loader2 v-if="uploading" class="size-4 animate-spin" :stroke-width="1.5" />
            <Upload v-else class="size-4" :stroke-width="1.5" />
            {{ uploading ? '上传中...' : '上传文档' }}
          </Button>
        </label>
      </template>
    </PageHeader>

    <!-- 状态过滤 -->
    <div class="mb-4 flex items-center gap-2">
      <Button
        v-for="s in ['', 'pending', 'processing', 'completed', 'failed']"
        :key="s"
        :variant="statusFilter === s ? 'default' : 'outline'"
        size="sm"
        @click="statusFilter = s; page = 1; fetchDocuments()"
      >
        {{ s ? (statusConfig[s]?.label || s) : '全部' }}
      </Button>
    </div>

    <!-- 批量操作栏 -->
    <BatchActionbar
      v-if="isEditor"
      :selected-count="sel.selectedCount.value"
      :loading="batchLoading"
      @clear="sel.clear"
    >
      <Button variant="outline" size="sm" :disabled="batchLoading" @click="handleBatchParse">
        <Layers class="size-4" :stroke-width="1.5" />
        批量解析
      </Button>
      <Button variant="outline" size="sm" :disabled="batchLoading" @click="handleBatchDelete">
        <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
        批量删除
      </Button>
    </BatchActionbar>

    <!-- 加载态 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 5" :key="i" class="h-16 w-full" />
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="documents.length === 0"
      :icon="FileText"
      title="暂无文档"
      description="上传文档后将自动进行 OCR 解析与结构化抽取"
      class="py-12"
    >
      <template v-if="isEditor" #actions>
        <label>
          <input type="file" multiple class="hidden" accept=".pdf,.png,.jpg,.jpeg" @change="handleUpload" />
          <Button as="span" class="cursor-pointer">
            <Upload class="size-4" :stroke-width="1.5" />
            上传文档
          </Button>
        </label>
      </template>
    </EmptyState>

    <!-- 文档列表 -->
    <div v-else class="space-y-2">
      <!-- 表头（含全选） -->
      <div v-if="isEditor" class="flex items-center gap-3 px-3 py-1 text-xs text-muted-foreground">
        <Checkbox
          :model-value="sel.isAllSelected(visibleIds)"
          :indeterminate="sel.isIndeterminate(visibleIds)"
          @update:checked="(v) => sel.selectAll(visibleIds, v === true)"
        />
        <span>全选当前页（已选 {{ sel.selectedCount.value }}）</span>
      </div>

      <Card v-for="doc in documents" :key="doc.id">
        <CardContent class="flex items-center gap-3 p-3">
          <!-- 批量选择 -->
          <Checkbox
            v-if="isEditor"
            :model-value="sel.isSelected(doc.id)"
            @update:checked="(v) => sel.setSelected(doc.id, v === true)"
          />

          <!-- 文件图标 -->
          <div class="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileText class="size-5" :stroke-width="1.5" />
          </div>

          <!-- 文件信息 -->
          <div class="min-w-0 flex-1">
            <p class="truncate font-medium text-foreground" :title="doc.filename">{{ doc.filename }}</p>
            <div class="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
              <span>{{ formatSize(doc.file_size) }}</span>
              <span>·</span>
              <span>{{ formatTime(doc.created_at) }}</span>
            </div>
          </div>

          <!-- 状态 -->
          <Badge
            v-if="doc.status && statusConfig[doc.status]"
            variant="secondary"
            :class="statusConfig[doc.status].color"
            class="shrink-0"
          >
            <component :is="statusConfig[doc.status].icon" class="mr-1 size-3" :stroke-width="1.5" />
            {{ statusConfig[doc.status].label }}
          </Badge>

          <!-- 操作 -->
          <div class="flex shrink-0 items-center gap-1">
            <Button variant="ghost" size="sm" title="预览" @click="handlePreview(doc)">
              <Eye class="size-4" :stroke-width="1.5" />
            </Button>
            <Button variant="ghost" size="sm" title="下载" @click="handleDownload(doc)">
              <Download class="size-4" :stroke-width="1.5" />
            </Button>
            <Button
              v-if="isEditor && doc.status === 'pending'"
              variant="ghost"
              size="sm"
              title="解析"
              :disabled="parseTarget?.id === doc.id"
              @click="handleParse(doc)"
            >
              <Loader2 v-if="parseTarget?.id === doc.id" class="size-4 animate-spin" :stroke-width="1.5" />
              <Play v-else class="size-4" :stroke-width="1.5" />
            </Button>
            <Button v-if="isEditor" variant="ghost" size="sm" title="删除" @click="handleDelete(doc)">
              <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 预览对话框 -->
    <DocumentPreviewDialog
      v-if="previewDoc"
      v-model:open="previewOpen"
      :kb-id="kbId"
      :document-id="previewDoc.id"
      :filename="previewDoc.filename"
    />
  </div>
</template>
