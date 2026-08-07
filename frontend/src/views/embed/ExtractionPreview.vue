<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileText,
  ChevronRight,
  Braces,
  Table,
  Clock,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-vue-next'
import { publicApi, type ProcessStatus, type ResultCategory, type ResultData } from '@/api/modules/public'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'

const route = useRoute()
const taskId = computed(() => route.params.task_id as string)

const loading = ref(true)
const processStatus = ref<ProcessStatus>('queued')
const progress = ref(0)
const message = ref('')
const filename = ref('')
const result = ref<ResultData | null>(null)
const errorMsg = ref('')

const viewMode = ref<'table' | 'json'>('table')
const expandedCats = ref<Set<string>>(new Set())
const showPdf = ref(true)

let pollTimer: number | null = null

/** PDF 预览地址（公开接口，文件上传后立即可用） */
const pdfSrc = computed(() => `/api/v1/public/extraction/${taskId.value}/preview`)

const resultCategories = computed<ResultCategory[]>(() => {
  const cats = result.value?.result?.categories
  return Array.isArray(cats) ? cats : []
})

const resultTotalRecords = computed(() =>
  resultCategories.value.reduce((sum, c) => sum + ((c.records as any[])?.length || 0), 0),
)

const isTerminal = computed(() => ['completed', 'failed'].includes(processStatus.value))
const isFailed = computed(() => processStatus.value === 'failed')
const isCompleted = computed(() => processStatus.value === 'completed')

function toggleCat(feature: string | undefined) {
  if (!feature) return
  const s = new Set(expandedCats.value)
  if (s.has(feature)) s.delete(feature)
  else s.add(feature)
  expandedCats.value = s
}

/** 动态表头：取该类目全部记录的字段并集（剔除内部 _ 字段） */
function recordHeaders(cat: Record<string, any>): string[] {
  const headers: string[] = []
  const seen = new Set<string>()
  for (const r of (cat.records || []) as any[]) {
    for (const k of Object.keys(r)) {
      if (k.startsWith('_')) continue
      if (!seen.has(k)) {
        seen.add(k)
        headers.push(k)
      }
    }
  }
  return headers
}

function cellValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// 处理步骤
const steps = [
  { id: 1, label: '排队' },
  { id: 2, label: 'OCR 解析' },
  { id: 3, label: '结构化抽取' },
  { id: 4, label: '完成' },
]

const currentStep = computed(() => {
  if (processStatus.value === 'queued') return 0
  if (processStatus.value === 'ocr_processing' || processStatus.value === 'ocr_done') return 1
  if (processStatus.value === 'extracting') return 2
  if (processStatus.value === 'completed') return 3
  return -1 // failed
})

async function fetchStatus() {
  try {
    const s = await publicApi.getStatus(taskId.value)
    processStatus.value = s.process_status
    progress.value = s.progress
    message.value = s.message
    filename.value = s.filename
    if (s.is_terminal && s.process_status === 'completed') {
      await fetchResult()
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || '查询状态失败'
    processStatus.value = 'failed'
    stopPolling()
  }
}

async function fetchResult() {
  try {
    const r = await publicApi.getResult(taskId.value)
    result.value = r
    stopPolling()
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || '获取结果失败'
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    await fetchStatus()
    if (isTerminal.value) stopPolling()
  }, 2000)
}

onMounted(async () => {
  await fetchStatus()
  loading.value = false
  if (!isTerminal.value) startPolling()
})

onUnmounted(() => stopPolling())
</script>

<template>
  <div class="flex h-screen flex-col bg-background text-foreground">
    <!-- 顶部状态栏 -->
    <header class="flex shrink-0 items-center gap-3 border-b border-border/60 bg-card/80 px-4 py-2.5 backdrop-blur-xl">
      <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
        <FileText class="size-4" :stroke-width="1.5" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-semibold">{{ filename || '文档抽取结果预览' }}</p>
        <p class="text-[11px] text-muted-foreground">
          任务 ID: <span class="font-mono">{{ taskId }}</span>
        </p>
      </div>
      <Badge
        v-if="isCompleted"
        variant="secondary"
        class="gap-1 bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
      >
        <CheckCircle2 class="size-3" :stroke-width="2" />
        已完成
      </Badge>
      <Badge
        v-else-if="isFailed"
        variant="secondary"
        class="gap-1 bg-destructive/15 text-destructive border-destructive/30"
      >
        <AlertCircle class="size-3" :stroke-width="2" />
        失败
      </Badge>
      <Badge
        v-else
        variant="secondary"
        class="gap-1 bg-primary/15 text-primary border-primary/30"
      >
        <Loader2 class="size-3 animate-spin" :stroke-width="2" />
        处理中
      </Badge>
      <!-- 折叠/展开左侧 PDF -->
      <Button
        variant="ghost"
        size="sm"
        class="ml-1 gap-1.5"
        @click="showPdf = !showPdf"
      >
        <PanelLeftClose v-if="showPdf" class="size-4" :stroke-width="1.5" />
        <PanelLeftOpen v-else class="size-4" :stroke-width="1.5" />
        {{ showPdf ? '隐藏源文件' : '显示源文件' }}
      </Button>
    </header>

    <!-- 主体：左右分栏 -->
    <div class="flex min-h-0 flex-1">
      <!-- 左侧：PDF 源文件 -->
      <div
        v-if="showPdf"
        class="flex w-1/2 flex-col border-r border-border/60 bg-muted/20"
      >
        <div class="flex shrink-0 items-center gap-2 border-b border-border/40 px-3 py-2">
          <FileText class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
          <span class="text-xs font-medium text-muted-foreground">源文件</span>
        </div>
        <div class="min-h-0 flex-1">
          <iframe
            :src="pdfSrc"
            class="h-full w-full border-0"
            :title="filename || 'PDF 预览'"
          />
        </div>
      </div>

      <!-- 右侧：抽取结果 -->
      <div class="min-w-0 flex-1 overflow-y-auto">
        <div class="p-4">
          <!-- 加载中 -->
          <div v-if="loading" class="space-y-3">
            <Skeleton class="h-16 w-full rounded-xl" />
            <Skeleton class="h-64 w-full rounded-xl" />
          </div>

          <template v-else>
            <!-- 失败状态 -->
            <div v-if="isFailed" class="flex flex-col items-center gap-3 py-16 text-center">
              <div class="flex size-14 items-center justify-center rounded-full bg-destructive/15 text-destructive">
                <AlertCircle class="size-7" :stroke-width="1.5" />
              </div>
              <p class="text-base font-semibold">处理失败</p>
              <p class="max-w-md text-sm text-muted-foreground">{{ errorMsg || message || '文档处理过程中发生错误' }}</p>
            </div>

            <!-- 处理中 / 完成状态 -->
            <template v-else>
              <!-- 步骤进度条（处理中显示） -->
              <div v-if="!isCompleted" class="mb-5 rounded-xl border border-border/60 bg-card/50 p-5">
                <div class="mb-4 flex items-center justify-between">
                  <span class="text-sm font-medium">{{ message || '处理中...' }}</span>
                  <span class="text-sm text-muted-foreground">{{ progress }}%</span>
                </div>
                <Progress :model-value="progress" class="mb-5 h-2" />
                <div class="flex items-center justify-between">
                  <div
                    v-for="(step, idx) in steps"
                    :key="step.id"
                    class="flex flex-1 flex-col items-center gap-1.5"
                  >
                    <div
                      class="flex size-8 items-center justify-center rounded-full border-2 transition-all duration-300"
                      :class="[
                        idx < currentStep
                          ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-400'
                          : idx === currentStep
                            ? 'border-primary/50 bg-primary/15 text-primary'
                            : 'border-border/60 bg-muted/40 text-muted-foreground',
                      ]"
                    >
                      <Loader2 v-if="idx === currentStep" class="size-3.5 animate-spin" :stroke-width="2" />
                      <CheckCircle2 v-else-if="idx < currentStep" class="size-3.5" :stroke-width="2" />
                      <span v-else class="text-xs font-semibold">{{ idx + 1 }}</span>
                    </div>
                    <span
                      class="text-xs"
                      :class="idx <= currentStep ? 'font-medium text-foreground' : 'text-muted-foreground'"
                    >
                      {{ step.label }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- 结果展示（完成状态） -->
              <div v-if="isCompleted && result">
                <!-- 概要信息 -->
                <div class="mb-4 rounded-xl border border-border/60 bg-card/50 p-4">
                  <div class="mb-3 flex items-center gap-2">
                    <FileText class="size-4 text-primary" :stroke-width="1.5" />
                    <span class="text-sm font-semibold">抽取概要</span>
                  </div>
                  <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div>
                      <p class="text-xs text-muted-foreground">类别数</p>
                      <p class="text-lg font-semibold text-primary">{{ resultCategories.length }}</p>
                    </div>
                    <div>
                      <p class="text-xs text-muted-foreground">记录总数</p>
                      <p class="text-lg font-semibold text-primary">{{ resultTotalRecords }}</p>
                    </div>
                    <div>
                      <p class="text-xs text-muted-foreground">Schema</p>
                      <p class="truncate text-sm font-medium" :title="result.schema_name || '-'">{{ result.schema_name || '-' }}</p>
                    </div>
                    <div>
                      <p class="text-xs text-muted-foreground">抽取时间</p>
                      <p class="flex items-center gap-1 text-sm font-medium">
                        <Clock class="size-3 text-muted-foreground" :stroke-width="1.5" />
                        {{ result.extracted_at ? new Date(result.extracted_at).toLocaleString('zh-CN') : '-' }}
                      </p>
                    </div>
                  </div>
                </div>

                <!-- 结果详情 -->
                <div class="rounded-xl border border-border/60 bg-card/50">
                  <div class="flex items-center gap-2 border-b border-border/40 px-4 py-3">
                    <span class="text-sm font-semibold">抽取结果</span>
                    <Badge v-if="resultCategories.length" variant="secondary" class="ml-auto gap-1 text-[10px] bg-primary/10 text-primary border-primary/20">
                      {{ resultCategories.length }} 类别 · {{ resultTotalRecords }} 记录
                    </Badge>
                  </div>
                  <div class="p-4">
                    <!-- 视图切换 -->
                    <div v-if="resultCategories.length > 0" class="mb-3 flex items-center justify-end gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        :class="viewMode === 'table' ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border/60 bg-muted/40 text-muted-foreground hover:border-primary/30 hover:text-foreground'"
                        @click="viewMode = 'table'"
                      >
                        <Table class="mr-1 size-3.5" :stroke-width="1.5" />
                        表格
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        :class="viewMode === 'json' ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border/60 bg-muted/40 text-muted-foreground hover:border-primary/30 hover:text-foreground'"
                        @click="viewMode = 'json'"
                      >
                        <Braces class="mr-1 size-3.5" :stroke-width="1.5" />
                        JSON
                      </Button>
                    </div>

                    <!-- 表格视图 -->
                    <div v-if="viewMode === 'table' && resultCategories.length > 0" class="space-y-2">
                      <div
                        v-for="cat in resultCategories"
                        :key="cat.feature"
                        class="overflow-hidden rounded-lg border border-border/60 bg-card/40"
                      >
                        <button
                          class="group flex w-full items-center gap-3 px-3 py-2.5 text-left transition-all hover:bg-muted/40"
                          @click="toggleCat(cat.feature)"
                        >
                          <div class="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary transition-all group-hover:scale-105">
                            <ChevronRight class="size-3.5 transition-transform duration-300" :class="expandedCats.has(cat.feature!) ? 'rotate-90' : ''" :stroke-width="1.5" />
                          </div>
                          <div class="min-w-0 flex-1">
                            <p class="truncate text-sm font-semibold text-foreground" :title="cat.feature">{{ cat.feature }}</p>
                            <p class="text-xs text-muted-foreground">{{ (cat.records || []).length }} 条记录</p>
                          </div>
                          <Badge variant="secondary" class="text-[10px] bg-muted/80">
                            {{ recordHeaders(cat).length }} 字段
                          </Badge>
                        </button>
                        <div
                          v-if="expandedCats.has(cat.feature!)"
                          class="overflow-x-auto border-t border-border/50"
                        >
                          <table class="w-full min-w-max border-collapse text-xs">
                            <thead>
                              <tr class="bg-muted/50">
                                <th
                                  v-for="h in recordHeaders(cat)"
                                  :key="h"
                                  class="whitespace-nowrap border-b border-border/40 px-3 py-2 text-left font-semibold text-muted-foreground"
                                >
                                  {{ h }}
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr
                                v-for="(rec, ri) in cat.records"
                                :key="ri"
                                class="transition-colors hover:bg-primary/[0.03]"
                              >
                                <td
                                  v-for="h in recordHeaders(cat)"
                                  :key="h"
                                  class="border-b border-border/30 px-3 py-2 align-top text-foreground/90"
                                >
                                  {{ cellValue(rec[h]) }}
                                </td>
                              </tr>
                              <tr v-if="!(cat.records || []).length">
                                <td class="px-3 py-6 text-center text-muted-foreground">该类别无记录</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>

                    <!-- JSON 视图 -->
                    <div v-if="viewMode === 'json' && resultCategories.length > 0">
                      <pre class="max-h-[500px] overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/50 bg-muted/40 p-4 text-xs font-mono text-foreground/90">{{ JSON.stringify(result.result, null, 2) }}</pre>
                    </div>

                    <!-- 无结果 -->
                    <div v-if="resultCategories.length === 0" class="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
                      <FileText class="size-8 opacity-50" :stroke-width="1.5" />
                      <p class="text-sm">本次抽取未产生记录</p>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
