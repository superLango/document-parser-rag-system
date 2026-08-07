<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Play,
  Loader2,
  FileText,
  CheckCircle2,
  AlertCircle,
  Braces,
  History,
  Clock,
  ChevronRight,
  Sparkles,
  Database,
  FileSearch,
  Zap,
} from 'lucide-vue-next'
import { kbApi, type KbExtractionSchema } from '@/api/modules/kb'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { Dialog } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { toast } from '@/components/ui/toast'
import PdfViewer from '@/components/PdfViewer.vue'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => route.params.kb_id as string)
const docId = computed(() => route.params.doc_id as string)

const schemasLoading = ref(true)
const schemas = ref<KbExtractionSchema[]>([])
const selectedSchemaId = ref<string>('')
const docInfo = ref<{ filename: string; file_type: string; status: string } | null>(null)

const pdfSrc = computed(() => `/api/v1/kbs/${kbId.value}/documents/${docId.value}/preview`)
const isPdf = computed(() => {
  if (!docInfo.value?.file_type) return true
  return docInfo.value.file_type.toLowerCase() === 'pdf'
})

type ExtractionStatus = 'idle' | 'running' | 'completed' | 'failed'
const extractionStatus = ref<ExtractionStatus>('idle')
const progress = ref(0)
const progressMessage = ref('')
const schemaInfo = ref<{
  schema_name: string
  schema_description: string
  field_count: number
} | null>(null)
const extractionResult = ref<Record<string, unknown>>({})
const missingFields = ref<string[]>([])
const isRunning = computed(() => extractionStatus.value === 'running')

const currentStep = computed(() => {
  if (extractionStatus.value === 'idle') return 0
  if (extractionStatus.value === 'running') {
    if (progress.value < 30) return 1
    if (progress.value < 70) return 2
    if (progress.value < 100) return 3
    return 4
  }
  if (extractionStatus.value === 'completed') return 4
  if (extractionStatus.value === 'failed') return 4
  return 0
})

const steps = [
  { id: 1, label: '初始化', icon: Sparkles },
  { id: 2, label: '解析文档', icon: FileSearch },
  { id: 3, label: '抽取字段', icon: Database },
  { id: 4, label: '完成', icon: CheckCircle2 },
]

const historyDialogOpen = ref(false)
const historyLoading = ref(false)
const historyItems = ref<Array<{
  schema_name: string | null
  extracted_at: string | null
  is_latest: boolean
  result: Record<string, unknown>
}>>([])
const viewingHistoryItem = ref<(typeof historyItems.value)[0] | null>(null)

const selectedSchema = computed(() =>
  schemas.value.find((s) => s.id === selectedSchemaId.value),
)

async function loadData() {
  schemasLoading.value = true
  try {
    const [schemasRes, docRes] = await Promise.all([
      kbApi.listExtractionSchemas(kbId.value),
      kbApi.getDocument(kbId.value, docId.value).catch(() => null),
    ])
    schemas.value = schemasRes
    if (docRes) {
      docInfo.value = {
        filename: docRes.filename,
        file_type: docRes.file_type || 'pdf',
        status: docRes.status,
      }
    }
    if (schemas.value.length > 0) {
      selectedSchemaId.value = schemas.value[0].id
    }

    try {
      const resultRes = await kbApi.getExtractionResults(kbId.value, docId.value)
      if (resultRes.latest_result) {
        extractionResult.value = resultRes.latest_result
        extractionStatus.value = 'completed'
        progress.value = 100
        if (resultRes.latest_schema_id) {
          selectedSchemaId.value = resultRes.latest_schema_id
        }
        schemaInfo.value = resultRes.latest_schema_name ? {
          schema_name: resultRes.latest_schema_name,
          schema_description: '',
          field_count: Object.keys(resultRes.latest_result).length,
        } : null
      }
    } catch {
    }
  } catch {
    schemas.value = []
    toast.error('加载失败', '无法加载Schema列表')
  } finally {
    schemasLoading.value = false
  }
}

function handleBack() {
  router.push({ name: 'KbExtraction', params: { kb_id: kbId.value } })
}

async function startExtraction() {
  if (!selectedSchemaId.value) {
    toast.warning('请选择Schema', '需要选择抽取Schema才能开始')
    return
  }

  extractionStatus.value = 'running'
  progress.value = 0
  progressMessage.value = '正在初始化抽取...'
  schemaInfo.value = null
  extractionResult.value = {}
  missingFields.value = []

  await kbApi.extractStream(
    kbId.value,
    {
      document_id: docId.value,
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
      },
      onChunkResult: (data) => {
        for (const [k, v] of Object.entries(data.data)) {
          if (v !== null && v !== '' && v !== undefined) {
            extractionResult.value[k] = v
          } else if (!(k in extractionResult.value)) {
            extractionResult.value[k] = v
          }
        }
        extractionResult.value = { ...extractionResult.value }
      },
      onDone: (data) => {
        extractionResult.value = { ...data.data }
        missingFields.value = data.missing || []
        progress.value = 100
        progressMessage.value = data.message || '抽取完成'
        extractionStatus.value = 'completed'
        toast.success('抽取完成', '结果已保存')
      },
      onError: (msg) => {
        extractionStatus.value = 'failed'
        progressMessage.value = `抽取失败：${msg}`
        toast.error('抽取失败', msg)
      },
    },
  )
}

async function loadHistory() {
  historyDialogOpen.value = true
  historyLoading.value = true
  viewingHistoryItem.value = null
  try {
    const res = await kbApi.getExtractionHistory(kbId.value, docId.value)
    historyItems.value = res.items
  } catch {
    historyItems.value = []
  } finally {
    historyLoading.value = false
  }
}

function viewHistoryItem(item: (typeof historyItems.value)[0]) {
  viewingHistoryItem.value = item
  extractionResult.value = { ...item.result }
  extractionStatus.value = 'completed'
  progress.value = 100
  schemaInfo.value = item.schema_name ? {
    schema_name: item.schema_name,
    schema_description: '(历史版本)',
    field_count: Object.keys(item.result).length,
  } : null
  historyDialogOpen.value = false
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'object') return JSON.stringify(v, null, 2)
  return String(v)
}

function selectSchema(schema: KbExtractionSchema) {
  if (isRunning.value) return
  selectedSchemaId.value = schema.id
}

onMounted(() => {
  loadData()
})

onUnmounted(() => {
})
</script>

<template>
  <div class="flex h-screen flex-col bg-background bg-subtle-gradient">
    <header class="glass sticky top-0 z-10 flex items-center justify-between border-b border-border/50 px-4 py-3 backdrop-blur-xl">
      <div class="flex items-center gap-3">
        <Button variant="ghost" size="sm" @click="handleBack" class="gap-1.5 rounded-lg transition-all hover:bg-primary/10 hover:text-primary">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回列表
        </Button>
        <div class="h-5 w-px bg-border/60" />
        <div>
          <h1 class="flex items-center gap-2 text-sm font-medium text-foreground">
            <FileText class="size-4 text-primary/70" :stroke-width="1.5" />
            <span class="truncate max-w-[300px]">{{ docInfo?.filename || '加载中...' }}</span>
          </h1>
          <div class="mt-0.5 flex items-center gap-2">
            <Badge
              v-if="docInfo?.status"
              variant="secondary"
              :class="docInfo.status === 'completed' ? 'bg-success/10 text-success border-success/30 shadow-[0_0_12px_rgba(46,160,93,0.2)]' : 'bg-warning/10 text-warning border-warning/30 shadow-[0_0_12px_rgba(179,142,36,0.2)]'"
              class="gap-1 border px-2 py-0 text-[10px] font-medium"
            >
              <CheckCircle2 v-if="docInfo.status === 'completed'" class="size-2.5" :stroke-width="2.5" />
              <Loader2 v-else class="size-2.5 animate-spin" :stroke-width="2" />
              {{ docInfo.status === 'completed' ? '已解析' : docInfo.status }}
            </Badge>
            <Badge v-if="viewingHistoryItem" variant="outline" class="gap-1 text-[10px] text-info border-info/30 bg-info/5">
              <History class="size-2.5" :stroke-width="2" />
              历史版本
            </Badge>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="isRunning" @click="loadHistory" class="gap-1.5 rounded-lg transition-all hover:border-primary/30 hover:bg-primary/5 disabled:opacity-50">
          <History class="size-3.5" :stroke-width="1.5" />
          历史记录
        </Button>
      </div>
    </header>

    <div class="flex flex-1 overflow-hidden">
      <div class="flex w-1/2 flex-col border-r border-border/50">
        <div class="border-b border-border/50 px-4 py-2.5 bg-gradient-to-r from-muted/50 to-transparent">
          <span class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <FileText class="size-3.5" :stroke-width="1.5" />
            原始文档预览
          </span>
        </div>
        <div class="flex-1 overflow-auto bg-muted/10">
          <div v-if="schemasLoading" class="space-y-3 p-4">
            <Skeleton class="h-4 w-3/4 skeleton-shimmer" />
            <Skeleton class="h-4 w-full skeleton-shimmer" />
            <Skeleton class="h-64 w-full rounded-xl skeleton-shimmer" />
          </div>
          <div v-else-if="isPdf" class="h-full">
            <PdfViewer :src="pdfSrc" />
          </div>
          <div v-else class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
            <div class="flex size-16 items-center justify-center rounded-2xl bg-muted/50">
              <FileText class="size-8 opacity-50" :stroke-width="1" />
            </div>
            <p class="text-sm">该文件类型暂不支持在线预览</p>
          </div>
        </div>
      </div>

      <div class="flex w-1/2 flex-col overflow-hidden">
        <div class="border-b border-border/50 p-4 bg-gradient-to-b from-card/50 to-transparent">
          <div class="mb-4">
            <label class="mb-3 flex items-center gap-2 text-sm font-medium text-foreground">
              <Braces class="size-4 text-primary" :stroke-width="1.5" />
              选择抽取 Schema
            </label>

            <div v-if="schemasLoading" class="grid grid-cols-2 gap-3">
              <Skeleton v-for="i in 2" :key="i" class="h-24 rounded-xl skeleton-shimmer" />
            </div>

            <div v-else-if="schemas.length === 0" class="rounded-xl border border-dashed border-border p-6 text-center">
              <EmptyState
                :icon="Braces"
                title="暂无可用 Schema"
                description="请先创建抽取 Schema"
                class="py-4"
              />
            </div>

            <div v-else class="grid grid-cols-2 gap-3">
              <div
                v-for="schema in schemas"
                :key="schema.id"
                @click="selectSchema(schema)"
                class="group relative cursor-pointer overflow-hidden rounded-xl border-2 p-3.5 transition-all duration-300"
                :class="[
                  selectedSchemaId === schema.id
                    ? 'border-primary bg-gradient-to-br from-primary/10 to-primary/[0.02] shadow-primary/20 shadow-md'
                    : 'border-border/60 bg-card/50 hover:border-primary/40 hover:from-primary/5 hover:to-transparent hover:shadow-sm'
                ]"
              >
                <div
                  v-if="selectedSchemaId === schema.id"
                  class="absolute right-2 top-2 flex size-5 items-center justify-center rounded-full bg-gradient-to-br from-primary to-primary/80 shadow-primary/30 shadow-sm"
                >
                  <CheckCircle2 class="size-3.5 text-primary-foreground" :stroke-width="2.5" />
                </div>

                <div class="flex items-start gap-2.5">
                  <div
                    class="flex size-9 shrink-0 items-center justify-center rounded-lg transition-all duration-300 group-hover:scale-105"
                    :class="selectedSchemaId === schema.id ? 'bg-primary/20 text-primary shadow-primary/20 shadow-sm' : 'bg-muted text-muted-foreground'"
                  >
                    <Braces class="size-4.5" :stroke-width="1.5" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium" :title="schema.name">{{ schema.name }}</p>
                    <div class="mt-1.5 flex flex-wrap gap-1.5">
                      <Badge variant="secondary" class="text-[10px] bg-muted/80">
                        {{ schema.field_count }} 字段
                      </Badge>
                      <Badge v-if="schema.children_count" variant="secondary" class="text-[10px] bg-muted/80">
                        {{ schema.children_count }} 子分类
                      </Badge>
                    </div>
                  </div>
                </div>

                <p v-if="schema.description" class="mt-2 line-clamp-2 text-xs text-muted-foreground">
                  {{ schema.description }}
                </p>

                <div
                  v-if="selectedSchemaId === schema.id"
                  class="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-transparent opacity-50"
                />
              </div>
            </div>
          </div>

          <Button
            class="group w-full gap-2 rounded-xl shadow-primary/20 shadow-sm transition-all hover:shadow-primary hover:-translate-y-0.5"
            :disabled="!selectedSchemaId || isRunning || schemasLoading"
            @click="startExtraction"
          >
            <div class="relative">
              <Loader2 v-if="isRunning" class="size-4 animate-spin" :stroke-width="1.5" />
              <Zap v-else class="size-4 transition-transform group-hover:scale-110" :stroke-width="1.5" />
            </div>
            <span class="font-medium">{{ isRunning ? '抽取中...' : '开始抽取' }}</span>
            <ChevronRight v-if="!isRunning" class="size-4 ml-auto opacity-0 -translate-x-2 transition-all group-hover:opacity-100 group-hover:translate-x-0" :stroke-width="1.5" />
          </Button>
        </div>

        <div class="flex-1 overflow-auto p-4 space-y-4">
          <div v-if="extractionStatus !== 'idle'" class="overflow-hidden rounded-xl border border-border/60 bg-gradient-to-br from-card to-card/50 shadow-sm">
            <div class="relative p-4">
              <div class="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/30 to-transparent" />

              <div class="mb-4 flex items-center justify-between">
                <div class="flex items-center gap-2.5">
                  <div
                    class="flex size-8 items-center justify-center rounded-lg transition-all"
                    :class="{
                      'bg-primary/15 text-primary animate-pulse': isRunning,
                      'bg-success/15 text-success': extractionStatus === 'completed',
                      'bg-danger/15 text-danger': extractionStatus === 'failed',
                    }"
                  >
                    <Loader2
                      v-if="isRunning"
                      class="size-4 animate-spin"
                      :stroke-width="1.5"
                    />
                    <CheckCircle2
                      v-else-if="extractionStatus === 'completed'"
                      class="size-4"
                      :stroke-width="2"
                    />
                    <AlertCircle
                      v-else-if="extractionStatus === 'failed'"
                      class="size-4"
                      :stroke-width="2"
                    />
                  </div>
                  <div>
                    <span class="text-sm font-medium">{{ progressMessage }}</span>
                    <p v-if="schemaInfo" class="text-xs text-muted-foreground">
                      {{ schemaInfo.schema_name }} · {{ schemaInfo.field_count }} 个字段
                    </p>
                  </div>
                </div>
                <span
                  class="rounded-lg px-2 py-1 text-sm font-semibold tabular-nums"
                  :class="{
                    'bg-primary/10 text-primary': isRunning,
                    'bg-success/10 text-success': extractionStatus === 'completed',
                    'bg-danger/10 text-danger': extractionStatus === 'failed',
                  }"
                >
                  {{ progress }}%
                </span>
              </div>

              <div class="mb-4">
                <Progress
                  :value="progress"
                  class="h-2 rounded-full bg-muted/80"
                  :indicatorClass="extractionStatus === 'failed' ? 'bg-gradient-to-r from-danger to-danger/70' : 'bg-gradient-to-r from-primary to-primary/80 shadow-primary/30 shadow-sm'"
                />
              </div>

              <div class="flex items-center justify-between">
                <template v-for="(step, idx) in steps" :key="step.id">
                  <div class="flex flex-col items-center gap-1.5">
                    <div
                      class="flex size-7 items-center justify-center rounded-full border-2 transition-all duration-500"
                      :class="{
                        'border-primary bg-primary text-primary-foreground shadow-primary/30 shadow-sm scale-110': currentStep >= step.id,
                        'border-muted bg-muted/50 text-muted-foreground': currentStep < step.id,
                        'animate-pulse': currentStep === step.id && isRunning,
                      }"
                    >
                      <CheckCircle2 v-if="currentStep > step.id" class="size-3.5" :stroke-width="2.5" />
                      <component v-else :is="step.icon" class="size-3.5" :stroke-width="2" />
                    </div>
                    <span
                      class="text-[10px] font-medium transition-colors"
                      :class="currentStep >= step.id ? 'text-foreground' : 'text-muted-foreground'"
                    >
                      {{ step.label }}
                    </span>
                  </div>
                  <div
                    v-if="idx < steps.length - 1"
                    class="mx-1 h-0.5 flex-1 rounded-full transition-all duration-500"
                    :class="currentStep > step.id ? 'bg-gradient-to-r from-primary to-primary/60' : 'bg-muted'"
                  />
                </template>
              </div>
            </div>
          </div>

          <Card class="overflow-hidden border-border/60 shadow-sm transition-all hover:shadow-md">
            <CardHeader class="pb-3 bg-gradient-to-r from-muted/30 to-transparent border-b border-border/40">
              <CardTitle class="flex items-center gap-2 text-sm">
                <div class="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
                  <Braces class="size-3.5" :stroke-width="1.5" />
                </div>
                抽取结果
                <Badge v-if="Object.keys(extractionResult).length" variant="secondary" class="ml-auto gap-1 text-[10px] bg-primary/10 text-primary border-primary/20">
                  <Database class="size-3" :stroke-width="2" />
                  {{ Object.keys(extractionResult).length }} 字段
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent class="p-4">
              <EmptyState
                v-if="Object.keys(extractionResult).length === 0 && !isRunning"
                :icon="Braces"
                title="暂无抽取结果"
                description="选择 Schema 后点击「开始抽取」"
                class="py-12"
              />

              <div v-if="isRunning && Object.keys(extractionResult).length === 0" class="flex flex-col items-center gap-3 py-12 text-muted-foreground">
                <div class="relative">
                  <div class="absolute inset-0 animate-ping rounded-full bg-primary/20" />
                  <div class="relative flex size-12 items-center justify-center rounded-full bg-primary/15 text-primary">
                    <Loader2 class="size-6 animate-spin" :stroke-width="1.5" />
                  </div>
                </div>
                <p class="text-sm font-medium">正在抽取，请稍候...</p>
                <p class="text-xs text-muted-foreground">AI 正在分析文档并提取结构化数据</p>
              </div>

              <div v-if="Object.keys(extractionResult).length > 0" class="space-y-2">
                <div
                  v-for="[k, v] in Object.entries(extractionResult)"
                  :key="k"
                  class="group grid grid-cols-[140px_1fr] gap-3 rounded-xl border border-border/50 px-3.5 py-3 transition-all duration-300 hover:border-primary/30 hover:bg-gradient-to-r hover:from-primary/[0.02] hover:to-transparent"
                >
                  <div class="min-w-0">
                    <p class="truncate text-xs font-semibold text-foreground/90 transition-colors group-hover:text-foreground" :title="k">{{ k }}</p>
                    <Badge
                      v-if="missingFields.includes(k)"
                      variant="outline"
                      class="mt-1.5 gap-1 text-[10px] text-warning border-warning/30 bg-warning/5"
                    >
                      <AlertCircle class="size-2.5" :stroke-width="2.5" />
                      缺失
                    </Badge>
                  </div>
                  <pre class="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted/50 p-2.5 text-xs text-foreground/90 font-mono transition-colors group-hover:bg-muted/70">{{ formatValue(v) }}</pre>
                </div>
              </div>

              <div
                v-if="missingFields.length > 0"
                class="mt-4 overflow-hidden rounded-xl border border-warning/30 bg-gradient-to-br from-warning/5 to-transparent"
              >
                <div class="flex items-center gap-2 border-b border-warning/10 px-3.5 py-2.5">
                  <div class="flex size-6 items-center justify-center rounded-md bg-warning/15 text-warning">
                    <AlertCircle class="size-3.5" :stroke-width="2" />
                  </div>
                  <span class="text-xs font-semibold text-warning">
                    缺失字段提示（{{ missingFields.length }}）
                  </span>
                </div>
                <div class="p-3.5">
                  <div class="flex flex-wrap gap-1.5">
                    <Badge
                      v-for="f in missingFields"
                      :key="f"
                      variant="outline"
                      class="gap-1 text-[10px] text-warning border-warning/30 bg-warning/5 transition-all hover:bg-warning/10"
                    >
                      {{ f }}
                    </Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>

    <Dialog
      :open="historyDialogOpen"
      title="抽取历史记录"
      class="max-w-2xl"
      @update:open="(v: boolean) => (historyDialogOpen = v)"
    >
      <div v-if="historyLoading" class="space-y-3">
        <Skeleton v-for="i in 3" :key="i" class="h-16 w-full rounded-xl skeleton-shimmer" />
      </div>

      <EmptyState
        v-else-if="historyItems.length === 0"
        :icon="Clock"
        title="暂无抽取记录"
        description="该文档尚未进行过抽取"
        class="py-12"
      />

      <div v-else class="max-h-96 space-y-2 overflow-y-auto pr-1">
        <div
          v-for="(item, idx) in historyItems"
          :key="idx"
          class="group cursor-pointer overflow-hidden rounded-xl border transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
          :class="item.is_latest ? 'border-primary/30 bg-gradient-to-br from-primary/5 to-transparent hover:border-primary/50 hover:shadow-primary/20' : 'border-border/60 bg-card/50 hover:border-border'"
          @click="viewHistoryItem(item)"
        >
          <div class="flex items-center justify-between p-3.5">
            <div class="flex items-center gap-2.5">
              <div
                class="flex size-9 items-center justify-center rounded-lg transition-all duration-300 group-hover:scale-105"
                :class="item.is_latest ? 'bg-primary/15 text-primary shadow-primary/20 shadow-sm' : 'bg-muted text-muted-foreground'"
              >
                <Braces class="size-4" :stroke-width="1.5" />
              </div>
              <div>
                <span class="text-sm font-medium flex items-center gap-2">
                  {{ item.schema_name || '未知 Schema' }}
                  <Badge v-if="item.is_latest" class="gap-1 border-0 bg-gradient-to-r from-primary to-primary/80 px-1.5 py-0 text-[10px] text-primary-foreground shadow-primary/30 shadow-sm">
                    <CheckCircle2 class="size-2.5" :stroke-width="2.5" />
                    最新
                  </Badge>
                </span>
                <p class="mt-0.5 text-xs text-muted-foreground flex items-center gap-1.5">
                  <Database class="size-3" :stroke-width="1.5" />
                  {{ Object.keys(item.result).length }} 个字段
                  <span class="opacity-50">·</span>
                  点击查看此版本结果
                </p>
              </div>
            </div>
            <span class="text-xs tabular-nums text-muted-foreground transition-colors group-hover:text-foreground/70 flex items-center gap-1">
              <Clock class="size-3" :stroke-width="1.5" />
              {{ formatDate(item.extracted_at) }}
            </span>
          </div>
        </div>
      </div>
    </Dialog>
  </div>
</template>
