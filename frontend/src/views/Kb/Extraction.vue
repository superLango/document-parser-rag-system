<script setup lang="ts">
/**
 * 知识库内结构化抽取页
 *
 * 功能：选择 KB 内文档 + 父分类 Schema → 流式抽取 → 实时展示增量结果
 * 数据隔离：所有操作通过 /kbs/{kb_id}/extraction/*，后端 RLS 按 kb_id
 *           强制隔离 Document 与 SchemaConfig
 * 权限：viewer+ 可查看；editor+ 可执行抽取（后端 require_role 守卫）
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Play,
  Loader2,
  FileText,
  CheckCircle2,
  AlertCircle,
  Braces,
  RefreshCw,
  StopCircle,
  ShieldCheck,
} from 'lucide-vue-next'
import { kbApi, type KbExtractableDocument, type KbExtractionSchema } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'

const route = useRoute()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

// ---------- 数据加载 ----------
const docsLoading = ref(true)
const documents = ref<KbExtractableDocument[]>([])
const schemasLoading = ref(true)
const schemas = ref<KbExtractionSchema[]>([])
const selectedDocId = ref<string>('')
const selectedSchemaId = ref<string>('')

async function fetchDocuments() {
  docsLoading.value = true
  try {
    const res = await kbApi.listExtractableDocuments(kbId.value)
    documents.value = res.items
    if (documents.value.length > 0 && !selectedDocId.value) {
      selectedDocId.value = documents.value[0].id
    }
  } catch {
    documents.value = []
  } finally {
    docsLoading.value = false
  }
}

async function fetchSchemas() {
  schemasLoading.value = true
  try {
    schemas.value = await kbApi.listExtractionSchemas(kbId.value)
    if (schemas.value.length > 0 && !selectedSchemaId.value) {
      selectedSchemaId.value = schemas.value[0].id
    }
  } catch {
    schemas.value = []
  } finally {
    schemasLoading.value = false
  }
}

const docOptions = computed(() =>
  documents.value.map((d) => ({
    value: d.id,
    label: `${d.filename}${d.has_extraction ? ' · 已抽取' : ''}`,
  })),
)
const schemaOptions = computed(() =>
  schemas.value.map((s) => ({
    value: s.id,
    label: `${s.name}（${s.children_count} 子 Schema）`,
  })),
)

const selectedDoc = computed(() =>
  documents.value.find((d) => d.id === selectedDocId.value),
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
const mergedResult = ref<Record<string, unknown>>({})
const chunkLogs = ref<
  Array<{ index: number; status: 'success' | 'error'; message: string }>
>([])
const missingFields = ref<string[]>([])
const isRunning = computed(() => extractionStatus.value === 'running')

async function startExtraction() {
  if (!selectedDocId.value) {
    toast.warning('请选择文档', '需要选择待抽取的文档')
    return
  }
  if (!selectedSchemaId.value) {
    toast.warning('请选择 Schema', '需要选择父分类 Schema 才能开始抽取')
    return
  }
  if (!isEditor.value) {
    toast.warning('权限不足', '需要 editor 及以上角色才能执行抽取')
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

  await kbApi.extractStream(
    kbId.value,
    {
      document_id: selectedDocId.value,
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
        for (const [k, v] of Object.entries(data.data)) {
          if (v !== null && v !== '' && v !== undefined) {
            mergedResult.value[k] = v
          } else if (!(k in mergedResult.value)) {
            mergedResult.value[k] = v
          }
        }
        mergedResult.value = { ...mergedResult.value }
        chunkLogs.value.push({
          index: data.chunk_index,
          status: 'success',
          message: data.message,
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
      },
      onDone: (data) => {
        mergedResult.value = { ...data.data }
        missingFields.value = data.missing || []
        progress.value = 100
        progressMessage.value = data.message || '抽取完成'
        extractionStatus.value = 'completed'
        toast.success('抽取完成', `已保存到文档结构化数据`)
      },
      onWarning: (data) => {
        toast.warning('抽取警告', data.message)
      },
      onError: (msg) => {
        extractionStatus.value = 'failed'
        progressMessage.value = `抽取失败：${msg}`
        toast.error('抽取失败', msg)
      },
    },
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'object') return JSON.stringify(v, null, 2)
  return String(v)
}

onMounted(() => {
  fetchDocuments()
  fetchSchemas()
})
</script>

<template>
  <div>
    <PageHeader title="结构化抽取" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Badge variant="secondary" class="gap-1">
          <ShieldCheck class="size-3" :stroke-width="1.5" />
          RLS 隔离
        </Badge>
        <Button variant="outline" @click="fetchDocuments">
          <RefreshCw class="size-4" :class="{ 'animate-spin': docsLoading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <div class="grid gap-4 lg:grid-cols-[320px_1fr]">
      <!-- 左侧：文档与 Schema 选择 -->
      <div class="space-y-4">
        <!-- 文档列表 -->
        <Card>
          <CardContent class="p-4">
            <div class="mb-3 flex items-center gap-2">
              <FileText class="size-4 text-primary" :stroke-width="1.5" />
              <h3 class="text-sm font-semibold text-foreground">待抽取文档</h3>
              <Badge variant="secondary" class="ml-auto text-[10px]">
                {{ documents.length }}
              </Badge>
            </div>

            <div v-if="docsLoading" class="space-y-2">
              <Skeleton v-for="i in 3" :key="i" class="h-12 w-full" />
            </div>

            <EmptyState
              v-else-if="documents.length === 0"
              :icon="FileText"
              title="无可抽取文档"
              description="请先上传文档并完成 OCR 解析"
              class="py-8"
            />

            <div v-else class="max-h-80 space-y-1 overflow-y-auto">
              <button
                v-for="doc in documents"
                :key="doc.id"
                class="flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors"
                :class="
                  selectedDocId === doc.id
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:bg-muted'
                "
                @click="selectedDocId = doc.id"
              >
                <FileText class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-xs font-medium text-foreground" :title="doc.filename">
                    {{ doc.filename }}
                  </p>
                  <p class="text-[10px] text-muted-foreground">
                    {{ formatSize(doc.file_size) }} · {{ doc.text_length }} 字符
                  </p>
                </div>
                <CheckCircle2
                  v-if="doc.has_extraction"
                  class="size-3.5 shrink-0 text-success"
                  :stroke-width="1.5"
                />
              </button>
            </div>
          </CardContent>
        </Card>

        <!-- Schema 选择 -->
        <Card>
          <CardContent class="space-y-3 p-4">
            <div class="flex items-center gap-2">
              <Braces class="size-4 text-primary" :stroke-width="1.5" />
              <h3 class="text-sm font-semibold text-foreground">抽取 Schema</h3>
            </div>

            <div v-if="schemasLoading">
              <Skeleton class="h-9 w-full" />
            </div>
            <Select
              v-else
              v-model="selectedSchemaId"
              :options="schemaOptions"
              placeholder="选择父分类 Schema"
            />

            <div v-if="schemaInfo" class="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
              <p class="font-medium text-foreground">{{ schemaInfo.schema_name }}</p>
              <p v-if="schemaInfo.schema_description" class="mt-0.5">
                {{ schemaInfo.schema_description }}
              </p>
              <p class="mt-0.5">字段数：{{ schemaInfo.field_count }}</p>
            </div>

            <Button
              class="w-full"
              :disabled="!selectedDocId || !selectedSchemaId || isRunning || !isEditor"
              @click="startExtraction"
            >
              <Loader2 v-if="isRunning" class="size-4 animate-spin" :stroke-width="1.5" />
              <Play v-else class="size-4" :stroke-width="1.5" />
              {{ isRunning ? '抽取中...' : '开始抽取' }}
            </Button>
            <p v-if="!isEditor" class="text-center text-[10px] text-muted-foreground">
              需要 editor 及以上角色才能执行抽取
            </p>
          </CardContent>
        </Card>
      </div>

      <!-- 右侧：进度与结果 -->
      <div class="space-y-4">
        <!-- 进度卡片 -->
        <Card v-if="extractionStatus !== 'idle'">
          <CardContent class="p-4">
            <div class="mb-2 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Loader2
                  v-if="isRunning"
                  class="size-4 animate-spin text-primary"
                  :stroke-width="1.5"
                />
                <CheckCircle2
                  v-else-if="extractionStatus === 'completed'"
                  class="size-4 text-success"
                  :stroke-width="1.5"
                />
                <AlertCircle
                  v-else
                  class="size-4 text-danger"
                  :stroke-width="1.5"
                />
                <span class="text-sm font-medium text-foreground">{{ progressMessage }}</span>
              </div>
              <span class="text-xs text-muted-foreground">{{ progress }}%</span>
            </div>

            <!-- 进度条 -->
            <div class="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                class="h-full rounded-full bg-primary transition-all duration-300"
                :class="{ 'bg-danger': extractionStatus === 'failed' }"
                :style="{ width: `${progress}%` }"
              />
            </div>

            <div v-if="totalChunks > 0" class="mt-2 text-[10px] text-muted-foreground">
              分块 {{ chunkIndex }} / {{ totalChunks }}
            </div>
          </CardContent>
        </Card>

        <!-- 抽取结果 -->
        <Card>
          <CardContent class="p-4">
            <div class="mb-3 flex items-center gap-2">
              <Braces class="size-4 text-primary" :stroke-width="1.5" />
              <h3 class="text-sm font-semibold text-foreground">抽取结果</h3>
              <Badge v-if="Object.keys(mergedResult).length" variant="secondary" class="ml-auto text-[10px]">
                {{ Object.keys(mergedResult).length }} 字段
              </Badge>
            </div>

            <EmptyState
              v-if="Object.keys(mergedResult).length === 0"
              :icon="Braces"
              title="暂无抽取结果"
              description="选择文档与 Schema 后点击「开始抽取」"
              class="py-12"
            />

            <div v-else class="space-y-2">
              <div
                v-for="[k, v] in Object.entries(mergedResult)"
                :key="k"
                class="grid grid-cols-[160px_1fr] gap-3 rounded-md border border-border px-3 py-2"
              >
                <div class="min-w-0">
                  <p class="truncate text-xs font-medium text-foreground" :title="k">{{ k }}</p>
                  <Badge
                    v-if="missingFields.includes(k)"
                    variant="outline"
                    class="mt-1 text-[10px] text-warning"
                  >
                    缺失
                  </Badge>
                </div>
                <pre class="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/30 p-2 text-xs text-foreground">{{ formatValue(v) }}</pre>
              </div>
            </div>

            <!-- 缺失字段汇总 -->
            <div
              v-if="missingFields.length > 0"
              class="mt-3 rounded-md border border-warning/30 bg-warning/5 p-3"
            >
              <div class="flex items-center gap-2">
                <AlertCircle class="size-3.5 text-warning" :stroke-width="1.5" />
                <span class="text-xs font-medium text-warning">
                  缺失字段（{{ missingFields.length }}）
                </span>
              </div>
              <div class="mt-1.5 flex flex-wrap gap-1">
                <Badge
                  v-for="f in missingFields"
                  :key="f"
                  variant="outline"
                  class="text-[10px] text-warning"
                >
                  {{ f }}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 分块日志 -->
        <Card v-if="chunkLogs.length > 0">
          <CardContent class="p-4">
            <h3 class="mb-2 text-sm font-semibold text-foreground">分块处理日志</h3>
            <div class="max-h-60 space-y-1 overflow-y-auto">
              <div
                v-for="(log, i) in chunkLogs"
                :key="i"
                class="flex items-center gap-2 rounded px-2 py-1 text-xs"
                :class="log.status === 'error' ? 'bg-danger/5' : 'bg-muted/30'"
              >
                <AlertCircle
                  v-if="log.status === 'error'"
                  class="size-3 shrink-0 text-danger"
                  :stroke-width="1.5"
                />
                <CheckCircle2
                  v-else
                  class="size-3 shrink-0 text-success"
                  :stroke-width="1.5"
                />
                <span class="shrink-0 font-mono text-muted-foreground">#{{ log.index }}</span>
                <span class="truncate text-foreground">{{ log.message }}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>
