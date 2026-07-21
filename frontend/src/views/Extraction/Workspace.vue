<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Play,
  Loader2,
  FileText,
  AlignLeft,
  Table as TableIcon,
  Braces,
  CheckCircle2,
  AlertCircle,
  StopCircle,
  Copy,
  Check,
} from 'lucide-vue-next'
import { documentApi } from '@/api/modules/document'
import {
  extractionApi,
  type ExtractableDocument,
  type ExtractionSchema,
} from '@/api/modules/extraction'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Tooltip } from '@/components/ui/tooltip'
import PdfViewer from '@/components/PdfViewer.vue'
import type { Document } from '@/api/types'

const route = useRoute()
const router = useRouter()
const docId = String(route.params.id)

// ---------- 数据加载 ----------
const loading = ref(true)
const document = ref<Document | null>(null)
const schemas = ref<ExtractionSchema[]>([])
const schemasLoading = ref(true)

async function fetchData() {
  loading.value = true
  try {
    document.value = await documentApi.getDetail(docId)
  } catch {
    document.value = null
  } finally {
    loading.value = false
  }

  schemasLoading.value = true
  try {
    schemas.value = await extractionApi.listSchemas()
  } catch {
    schemas.value = []
  } finally {
    schemasLoading.value = false
  }
}

// ---------- Schema 选择 ----------
const selectedSchemaId = ref<string>('')
const schemaOptions = computed(() =>
  schemas.value.map((s) => ({
    value: s.id,
    label: `${s.name}（${s.children_count} 个子 Schema）`,
  })),
)

watch(
  schemas,
  (list) => {
    if (list.length > 0 && !selectedSchemaId.value) {
      selectedSchemaId.value = list[0].id
    }
  },
  { immediate: true },
)

// ---------- 抽取状态 ----------
type ExtractionStatus = 'idle' | 'running' | 'completed' | 'failed'
const extractionStatus = ref<ExtractionStatus>('idle')
const progress = ref(0)
const progressMessage = ref('')
const chunkIndex = ref(0)
const totalChunks = ref(0)
const schemaInfo = ref<{
  schema_name: string
  schema_description: string
  field_count: number
  has_samples: boolean
} | null>(null)
// 累积的抽取结果（实时更新）
const mergedResult = ref<Record<string, unknown>>({})
// 单块结果日志
const chunkLogs = ref<
  Array<{ index: number; status: 'success' | 'error'; message: string; data?: Record<string, unknown> }>
>([])
// 缺失字段
const missingFields = ref<string[]>([])

const isRunning = computed(() => extractionStatus.value === 'running')

// ---------- 启动抽取 ----------
let abortController: AbortController | null = null

async function startExtraction() {
  if (!document.value) {
    toast.warning('文档未加载', '请等待文档加载完成')
    return
  }
  if (!selectedSchemaId.value) {
    toast.warning('请选择 Schema', '需要选择父分类 Schema 才能开始抽取')
    return
  }
  if (document.value.status !== 'completed') {
    toast.warning('文档未完成解析', '请先在文档管理中完成 OCR 解析')
    return
  }

  // 重置状态
  extractionStatus.value = 'running'
  progress.value = 0
  progressMessage.value = '准备开始抽取…'
  chunkIndex.value = 0
  totalChunks.value = 0
  schemaInfo.value = null
  mergedResult.value = {}
  chunkLogs.value = []
  missingFields.value = []

  await extractionApi.extractStream(
    {
      document_id: docId,
      schema_id: selectedSchemaId.value,
    },
    {
      onSchemaInfo: (info) => {
        schemaInfo.value = info
        progressMessage.value = `使用 Schema「${info.schema_name}」抽取（${info.field_count} 个字段）`
      },
      onProgress: (data) => {
        progress.value = data.progress
        progressMessage.value = data.message
        chunkIndex.value = data.chunk_index
        totalChunks.value = data.total_chunks
      },
      onChunkResult: (data) => {
        // 合并增量结果
        for (const [k, v] of Object.entries(data.data)) {
          if (v !== null && v !== '' && v !== undefined) {
            mergedResult.value[k] = v
          } else if (!(k in mergedResult.value)) {
            mergedResult.value[k] = v
          }
        }
        // 触发响应式更新
        mergedResult.value = { ...mergedResult.value }
        chunkLogs.value.push({
          index: data.chunk_index,
          status: 'success',
          message: data.message,
          data: data.data,
        })
        progress.value = data.progress
        progressMessage.value = data.message
      },
      onChunkError: (data) => {
        chunkLogs.value.push({
          index: data.chunk_index,
          status: 'error',
          message: data.message,
        })
        toast.warning(`第 ${data.chunk_index + 1} 块抽取失败`, data.error)
      },
      onDone: (data) => {
        mergedResult.value = data.data
        missingFields.value = data.missing || []
        progress.value = 100
        progressMessage.value = data.message
        extractionStatus.value = 'completed'
        toast.success(
          '抽取完成',
          `共抽取 ${Object.keys(data.data).length} 个字段${data.missing.length > 0 ? `，缺失 ${data.missing.length} 个必填字段` : ''}`,
        )
      },
      onWarning: (data) => {
        toast.warning('警告', data.message)
      },
      onError: (message) => {
        extractionStatus.value = 'failed'
        progressMessage.value = `抽取失败：${message}`
        toast.error('抽取失败', message)
      },
    },
  )
}

function cancelExtraction() {
  // 注意：当前 fetch 流式请求无法主动中断（需后端配合），
  // 仅切换 UI 状态以停止接收事件
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  extractionStatus.value = 'idle'
  progressMessage.value = '已取消抽取'
  toast.info('已取消', '抽取已中断')
}

// ---------- 结果视图切换 ----------
type ResultView = 'table' | 'json'
const resultView = ref<ResultView>('table')

// 表格行数据
interface ResultRow {
  key: string
  value: string
  status: 'ok' | 'missing' | 'empty'
}

const resultRows = computed<ResultRow[]>(() => {
  const rows: ResultRow[] = []
  const merged = mergedResult.value
  for (const [k, v] of Object.entries(merged)) {
    let valueStr: string
    let status: ResultRow['status'] = 'ok'
    if (v === null || v === undefined) {
      valueStr = '(空)'
      status = 'empty'
    } else if (typeof v === 'string') {
      valueStr = v
    } else {
      try {
        valueStr = JSON.stringify(v, null, 2)
      } catch {
        valueStr = String(v)
      }
    }
    if (missingFields.value.includes(k)) {
      status = 'missing'
    }
    rows.push({ key: k, value: valueStr, status })
  }
  // 按 missing 优先排序
  rows.sort((a, b) => {
    if (a.status === 'missing' && b.status !== 'missing') return -1
    if (b.status === 'missing' && a.status !== 'missing') return 1
    return 0
  })
  return rows
})

// JSON 字符串（带格式化）
const resultJson = computed(() => {
  try {
    return JSON.stringify(mergedResult.value, null, 2)
  } catch {
    return '{}'
  }
})

// ---------- 复制结果 ----------
const copied = ref(false)
async function copyResult() {
  try {
    await navigator.clipboard.writeText(resultJson.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
    toast.success('已复制', '抽取结果已复制到剪贴板')
  } catch {
    toast.error('复制失败', '请手动复制')
  }
}

// ---------- 文档内容 Tab ----------
const docTab = ref<'pdf' | 'ocr'>('ocr')
const pdfUrl = computed(() =>
  document.value ? `/api/v1/documents/${document.value.id}/download` : '',
)

// ---------- 格式化 ----------
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

const hasResult = computed(() => Object.keys(mergedResult.value).length > 0)

onMounted(fetchData)
</script>

<template>
  <div class="flex h-full flex-col gap-3">
    <!-- 顶部操作栏 -->
    <Card>
      <CardContent class="flex flex-col gap-3 p-4">
        <div class="flex items-center gap-3">
          <Tooltip :side="'bottom'">
            <template #trigger>
              <Button
                variant="ghost"
                size="icon"
                class="size-8 shrink-0"
                @click="router.push('/extraction')"
              >
                <ArrowLeft class="size-4" :stroke-width="1.5" />
              </Button>
            </template>
            <span>返回文档列表</span>
          </Tooltip>

          <div class="min-w-0 flex-1">
            <h2 class="truncate text-base font-medium text-foreground" :title="document?.filename">
              {{ document?.filename || '加载中…' }}
            </h2>
            <p class="mt-0.5 truncate text-xs text-muted-foreground">
              <span v-if="document">{{ formatFileSize(document.file_size) }} · 创建于 {{ formatTime(document.created_at) }}</span>
              <span v-else>正在加载文档信息…</span>
            </p>
          </div>

          <!-- Schema 选择器 -->
          <div class="flex shrink-0 items-center gap-2">
            <span class="text-xs text-muted-foreground">Schema:</span>
            <Select
              v-model="selectedSchemaId"
              :options="schemaOptions"
              :disabled="isRunning || schemasLoading"
              class="min-w-[200px]"
            />
          </div>

          <!-- 开始/取消按钮 -->
          <Button
            v-if="!isRunning"
            :disabled="!selectedSchemaId || loading"
            class="shrink-0 gap-2"
            @click="startExtraction"
          >
            <Play class="size-4" :stroke-width="1.5" />
            开始抽取
          </Button>
          <Button
            v-else
            variant="destructive"
            class="shrink-0 gap-2"
            @click="cancelExtraction"
          >
            <StopCircle class="size-4" :stroke-width="1.5" />
            取消
          </Button>
        </div>

        <!-- 进度条 -->
        <div v-if="extractionStatus !== 'idle'" class="space-y-1.5">
          <div class="flex items-center justify-between text-xs">
            <span class="flex items-center gap-1.5 text-muted-foreground">
              <Loader2 v-if="isRunning" class="size-3 animate-spin" :stroke-width="2" />
              <CheckCircle2 v-else-if="extractionStatus === 'completed'" class="size-3 text-success" :stroke-width="2" />
              <AlertCircle v-else class="size-3 text-danger" :stroke-width="2" />
              {{ progressMessage }}
            </span>
            <span class="font-mono text-muted-foreground">
              {{ progress }}%
              <span v-if="totalChunks > 0">
                · {{ Math.min(chunkIndex + 1, totalChunks) }}/{{ totalChunks }}
              </span>
            </span>
          </div>
          <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              class="h-full transition-all duration-300"
              :class="[
                extractionStatus === 'failed' ? 'bg-danger' :
                extractionStatus === 'completed' ? 'bg-success' : 'bg-primary',
              ]"
              :style="{ width: `${progress}%` }"
            />
          </div>
          <!-- Schema 信息提示 -->
          <div v-if="schemaInfo" class="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
            <Badge variant="secondary" class="gap-1 text-[10px]">
              {{ schemaInfo.schema_name }}
            </Badge>
            <Badge variant="outline" class="text-[10px]">
              {{ schemaInfo.field_count }} 字段
            </Badge>
            <Badge v-if="schemaInfo.has_samples" variant="success" class="text-[10px]">
              含示例
            </Badge>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 加载态 -->
    <div v-if="loading" class="grid flex-1 grid-cols-2 gap-3">
      <Skeleton class="h-full w-full" />
      <Skeleton class="h-full w-full" />
    </div>

    <!-- 主内容：左右分栏 -->
    <div v-else class="grid flex-1 grid-cols-1 gap-3 lg:grid-cols-2" style="min-height: 0">
      <!-- 左侧：文档内容 -->
      <Card class="flex h-full flex-col overflow-hidden">
        <CardContent class="flex h-full flex-col gap-2 p-3" style="min-height: 0">
          <Tabs v-model="docTab" class="flex h-full flex-col">
            <TabsList class="grid w-full grid-cols-2">
              <TabsTrigger value="ocr" class="gap-1.5">
                <AlignLeft class="size-3.5" :stroke-width="1.5" />
                OCR 文本
              </TabsTrigger>
              <TabsTrigger value="pdf" class="gap-1.5">
                <FileText class="size-3.5" :stroke-width="1.5" />
                原文档
              </TabsTrigger>
            </TabsList>

            <TabsContent value="ocr" class="mt-2 flex-1 overflow-hidden" style="min-height: 0">
              <div class="h-full overflow-auto rounded-md border border-border bg-muted/20 p-4">
                <pre v-if="document?.parsed_text" class="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">{{ document.parsed_text }}</pre>
                <EmptyState
                  v-else
                  :icon="AlignLeft"
                  title="暂无 OCR 文本"
                  description="文档尚未完成 OCR 解析"
                  class="py-8"
                />
              </div>
            </TabsContent>

            <TabsContent value="pdf" class="mt-2 flex-1 overflow-hidden" style="min-height: 0">
              <div v-if="pdfUrl" class="h-full overflow-auto">
                <PdfViewer :src="pdfUrl" :scale="1.0" />
              </div>
              <EmptyState
                v-else
                :icon="FileText"
                title="无法预览原文档"
                description="文档未关联原始 PDF 文件"
                class="py-8"
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <!-- 右侧：抽取结果 -->
      <Card class="flex h-full flex-col overflow-hidden">
        <CardContent class="flex h-full flex-col gap-2 p-3" style="min-height: 0">
          <div class="flex items-center justify-between gap-2">
            <Tabs v-model="resultView" class="flex-1">
              <TabsList class="grid w-full grid-cols-2">
                <TabsTrigger value="table" class="gap-1.5">
                  <TableIcon class="size-3.5" :stroke-width="1.5" />
                  表格视图
                </TabsTrigger>
                <TabsTrigger value="json" class="gap-1.5">
                  <Braces class="size-3.5" :stroke-width="1.5" />
                  JSON 视图
                </TabsTrigger>
              </TabsList>
            </Tabs>

            <Tooltip :side="'left'">
              <template #trigger>
                <Button
                  variant="outline"
                  size="icon"
                  class="size-8 shrink-0"
                  :disabled="!hasResult"
                  @click="copyResult"
                >
                  <Check v-if="copied" class="size-3.5 text-success" :stroke-width="1.5" />
                  <Copy v-else class="size-3.5" :stroke-width="1.5" />
                </Button>
              </template>
              <span>{{ copied ? '已复制' : '复制 JSON 结果' }}</span>
            </Tooltip>
          </div>

          <!-- 表格视图 -->
          <div v-if="resultView === 'table'" class="flex-1 overflow-auto" style="min-height: 0">
            <EmptyState
              v-if="!hasResult && !isRunning"
              :icon="TableIcon"
              title="暂无抽取结果"
              description="选择 Schema 后点击「开始抽取」"
              class="py-12"
            />

            <div v-else-if="!hasResult && isRunning" class="flex h-full items-center justify-center py-12">
              <div class="flex flex-col items-center gap-2 text-muted-foreground">
                <Loader2 class="size-6 animate-spin text-primary" :stroke-width="1.5" />
                <p class="text-xs">{{ progressMessage || '正在抽取…' }}</p>
              </div>
            </div>

            <div v-else class="overflow-hidden rounded-md border border-border">
              <table class="w-full text-sm">
                <thead class="sticky top-0 z-10 bg-muted/60 backdrop-blur">
                  <tr class="border-b border-border text-left text-xs text-muted-foreground">
                    <th class="px-3 py-2 font-medium">字段名</th>
                    <th class="px-3 py-2 font-medium">值</th>
                    <th class="px-3 py-2 font-medium text-center">状态</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-border">
                  <tr
                    v-for="row in resultRows"
                    :key="row.key"
                    class="transition-colors hover:bg-muted/30"
                    :class="{ 'bg-warning/5': row.status === 'missing' }"
                  >
                    <td class="whitespace-nowrap px-3 py-2 font-mono text-xs text-foreground">
                      {{ row.key }}
                      <span v-if="missingFields.includes(row.key)" class="text-danger">*</span>
                    </td>
                    <td class="max-w-[300px] break-words px-3 py-2 text-xs text-foreground">
                      <pre v-if="row.value.includes('\n')" class="whitespace-pre-wrap break-words font-mono text-xs">{{ row.value }}</pre>
                      <span v-else>{{ row.value }}</span>
                    </td>
                    <td class="px-3 py-2 text-center">
                      <Badge
                        v-if="row.status === 'missing'"
                        variant="danger"
                        class="text-[10px]"
                      >
                        缺失
                      </Badge>
                      <Badge v-else-if="row.status === 'empty'" variant="secondary" class="text-[10px]">
                        空
                      </Badge>
                      <Badge v-else variant="success" class="text-[10px]">
                        <CheckCircle2 class="mr-0.5 size-2.5" :stroke-width="2" />
                        已抽取
                      </Badge>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- JSON 视图 -->
          <div v-else class="flex-1 overflow-auto" style="min-height: 0">
            <EmptyState
              v-if="!hasResult && !isRunning"
              :icon="Braces"
              title="暂无抽取结果"
              description="选择 Schema 后点击「开始抽取」"
              class="py-12"
            />

            <div v-else-if="!hasResult && isRunning" class="flex h-full items-center justify-center py-12">
              <div class="flex flex-col items-center gap-2 text-muted-foreground">
                <Loader2 class="size-6 animate-spin text-primary" :stroke-width="1.5" />
                <p class="text-xs">{{ progressMessage || '正在抽取…' }}</p>
              </div>
            </div>

            <pre v-else class="h-full overflow-auto rounded-md border border-border bg-muted/20 p-3 font-mono text-xs leading-relaxed text-foreground">{{ resultJson }}</pre>
          </div>

          <!-- 抽取日志（运行中显示） -->
          <div
            v-if="chunkLogs.length > 0 && (isRunning || extractionStatus === 'completed')"
            class="max-h-32 shrink-0 overflow-auto rounded-md border border-border bg-muted/10 p-2"
          >
            <p class="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              抽取日志 ({{ chunkLogs.length }})
            </p>
            <ul class="space-y-0.5 text-[10px]">
              <li
                v-for="log in chunkLogs"
                :key="log.index"
                class="flex items-center gap-2"
              >
                <CheckCircle2 v-if="log.status === 'success'" class="size-3 shrink-0 text-success" :stroke-width="2" />
                <AlertCircle v-else class="size-3 shrink-0 text-danger" :stroke-width="2" />
                <span class="font-mono text-muted-foreground">[{{ log.index + 1 }}]</span>
                <span class="text-muted-foreground">{{ log.message }}</span>
              </li>
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
