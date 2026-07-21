<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Play,
  Copy,
  FileText,
  Braces,
  AlignLeft,
  FileQuestion,
  Loader2,
  MapPin,
  Search,
} from 'lucide-vue-next'
import { documentApi } from '@/api/modules/document'
import { taskApi } from '@/api/modules/task'
import { useTaskProgress } from '@/composables/useTaskProgress'
import PdfViewer from '@/components/PdfViewer.vue'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/ui/status-badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Input } from '@/components/ui/input'
import type { Document, LayoutRegion } from '@/api/types'

const route = useRoute()
const router = useRouter()
const docId = String(route.params.id)
const taskIdFromUrl = route.query.task_id ? String(route.query.task_id) : ''

const loading = ref(true)
const document = ref<Document | null>(null)
const activeTab = ref('ocr')

// ---------- 任务进度 ----------
const { progress, status: taskStatus, message: taskMessage, startProgress } =
  useTaskProgress()

// ---------- PDF 预览状态 ----------
const currentPage = ref(1)
const totalPages = ref(0)
// PdfViewer 暴露的 canvas 尺寸（用于精确计算 bbox 位置）
const canvasWidth = ref(0)
const canvasHeight = ref(0)
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const pdfViewerRef = ref<InstanceType<typeof PdfViewer> | null>(null)

// ---------- 数据加载 ----------
async function fetchDocument() {
  loading.value = true
  try {
    document.value = await documentApi.getDetail(docId)
  } catch {
    document.value = null
  } finally {
    loading.value = false
  }
}

// ---------- 提交解析 ----------
async function submitParse() {
  if (!document.value) return
  try {
    // OCR-only 模式：不传 schema_id，仅执行 OCR + 版面分析 + 术语标准化
    const res = await taskApi.submit({ document_id: String(document.value.id) })
    router.replace({ query: { ...route.query, task_id: res.task_id } })
    startProgress(res.task_id)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

// 任务完成后自动刷新文档详情
watch(taskStatus, (val) => {
  if (val === 'completed') {
    fetchDocument()
  }
})

// ---------- PDF URL ----------
const pdfUrl = computed(() =>
  document.value ? `/api/v1/documents/${document.value.id}/download` : '',
)

// ---------- 文档状态 ----------
const showStartButton = computed(() => {
  if (!document.value) return false
  if (taskStatus.value === 'running' || taskStatus.value === 'queued') return false
  return (
    document.value.status === 'pending' || document.value.status === 'failed'
  )
})

const showProgress = computed(() => taskStatus.value !== 'idle')

const progressIndicatorClass = computed(() => {
  if (taskStatus.value === 'completed') return 'bg-success'
  if (taskStatus.value === 'failed') return 'bg-danger'
  return 'bg-primary'
})

// ---------- BoundingBox ----------
// 区域类型颜色映射（与 Steel Teal 主题协调）
const REGION_COLORS: Record<string, string> = {
  text: '#0d9488', // teal-600
  table: '#16a34a', // green-600
  figure: '#d97706', // amber-600
  title: '#dc2626', // red-600
  header: '#64748b', // slate-500
  footer: '#64748b',
}

const REGION_LABELS: Record<string, string> = {
  text: '文本',
  table: '表格',
  figure: '图片',
  title: '标题',
  header: '页眉',
  footer: '页脚',
}

const regions = computed<LayoutRegion[]>(() => {
  const merged = document.value?.layout_data?.merged
  return Array.isArray(merged) ? merged : []
})

const regionStats = computed(() => {
  const stats: Record<string, number> = {}
  for (const r of regions.value) {
    stats[r.type] = (stats[r.type] || 0) + 1
  }
  return stats
})

/**
 * 将 PDF 原始坐标的 bbox 转换为 canvas 像素坐标的矩形
 */
function bboxRects(
  naturalW: number,
  naturalH: number,
  canvasW: number,
  canvasH: number,
  pageNumber: number,
) {
  if (!naturalW || !naturalH) return []
  const ratioX = canvasW / naturalW
  const ratioY = canvasH / naturalH
  return regions.value
    .filter((r) => {
      // 若区域携带 page 字段则按页过滤，否则视为当前页
      if (r.page !== undefined && r.page !== null) return r.page === pageNumber
      return true
    })
    .map((r, idx) => {
      const [x1, y1, x2, y2] = r.bbox
      const key = `region-${idx}-${r.type}-${x1}-${y1}-${x2}-${y2}-${r.page ?? pageNumber}`
      return {
        key,
        idx,
        type: r.type,
        label: REGION_LABELS[r.type] || r.type,
        confidence: r.confidence,
        text: r.text,
        page: r.page ?? pageNumber,
        x: x1 * ratioX,
        y: y1 * ratioY,
        w: (x2 - x1) * ratioX,
        h: (y2 - y1) * ratioY,
        color: REGION_COLORS[r.type] || '#64748b',
        selected: selectedRegionKey.value === key,
      }
    })
}

// ---------- OCR 文本块（右侧列表） ----------
interface OcrTextBlock {
  key: string
  idx: number
  type: string
  typeLabel: string
  color: string
  text: string
  page: number
  bbox: [number, number, number, number]
  confidence?: number | null
}

const ocrBlocks = computed<OcrTextBlock[]>(() => {
  return regions.value.map((r, idx) => {
    const [x1, y1, x2, y2] = r.bbox
    const key = `region-${idx}-${r.type}-${x1}-${y1}-${x2}-${y2}-${r.page ?? 1}`
    return {
      key,
      idx,
      type: r.type,
      typeLabel: REGION_LABELS[r.type] || r.type,
      color: REGION_COLORS[r.type] || '#64748b',
      text: r.text || '',
      page: r.page ?? 1,
      bbox: r.bbox,
      confidence: r.confidence,
    }
  })
})

// 按页分组
const ocrBlocksByPage = computed(() => {
  const map = new Map<number, OcrTextBlock[]>()
  for (const block of ocrBlocks.value) {
    if (!map.has(block.page)) map.set(block.page, [])
    map.get(block.page)!.push(block)
  }
  return Array.from(map.entries()).sort((a, b) => a[0] - b[0])
})

// ---------- 文本搜索 ----------
const searchKeyword = ref('')
const searchResults = computed<OcrTextBlock[]>(() => {
  if (!searchKeyword.value.trim()) return []
  const kw = searchKeyword.value.trim().toLowerCase()
  return ocrBlocks.value.filter((b) => b.text.toLowerCase().includes(kw))
})

// ---------- 高亮定位（双向） ----------
const selectedRegionKey = ref<string>('')
const selectedRegionRef = ref<HTMLElement | null>(null)

/**
 * 点击右侧 OCR 文本块 → 高亮左侧 PDF bbox 并切到对应页
 */
async function locateInPdf(block: OcrTextBlock) {
  selectedRegionKey.value = block.key
  // 切换到对应页
  if (block.page !== currentPage.value) {
    currentPage.value = block.page
    // 等待 PdfViewer 重新渲染后再次确保选中状态
    await nextTick()
    await nextTick()
  }
  // 让 PdfViewer 内部容器滚动到 bbox 位置（通过事件或 ref 暴露）
  // PdfViewer 自身没暴露 scrollIntoView，但我们可以滚动外层容器
  // 这里通过设置 selectedRegionKey 后 SVG 选中矩形会高亮，并提供视觉反馈
}

/**
 * 点击左侧 PDF bbox → 高亮右侧文本块并滚动到位置
 */
async function locateInTextList(rect: { key: string }) {
  selectedRegionKey.value = rect.key
  // 切到 OCR Tab
  activeTab.value = 'ocr'
  await nextTick()
  await nextTick()
  // 滚动到右侧列表对应项
  const el = window.document.querySelector(`[data-block-key="${rect.key}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    selectedRegionRef.value = el as HTMLElement
  }
}

// ---------- 原始文本（全文） ----------
const parsedText = computed(() => document.value?.parsed_text || '')

async function copyText() {
  if (!parsedText.value) return
  try {
    await navigator.clipboard.writeText(parsedText.value)
    toast.success('已复制全文', '解析文本已复制到剪贴板')
  } catch {
    toast.error('复制失败', '请检查浏览器剪贴板权限')
  }
}

// ---------- 结构化数据 ----------
const structuredEntries = computed<[string, unknown][]>(() => {
  const sd = document.value?.structured_data
  if (!sd || typeof sd !== 'object') return []
  return Object.entries(sd)
})

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// ---------- 抽取数据 ----------
function inferType(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (Array.isArray(v)) return 'array'
  if (typeof v === 'object') return 'object'
  return typeof v
}

interface ExtractionRow {
  name: string
  value: string
  type: string
}

const extractionRows = computed<ExtractionRow[]>(() => {
  const rows: ExtractionRow[] = []
  const doc = document.value
  if (!doc) return rows

  // 文档元信息（仅展示后端实际存在的字段）
  const meta: Record<string, unknown> = {
    filename: doc.filename,
    file_type: doc.file_type,
    file_size: doc.file_size,
  }
  for (const [k, v] of Object.entries(meta)) {
    if (v !== undefined && v !== null && v !== '') {
      rows.push({ name: k, value: String(v), type: 'string' })
    }
  }

  // 结构化抽取字段
  const sd = doc.structured_data
  if (sd && typeof sd === 'object') {
    for (const [k, v] of Object.entries(sd)) {
      rows.push({
        name: k,
        value: formatValue(v) || '-',
        type: inferType(v),
      })
    }
  }

  return rows
})

// ---------- 页码变更 ----------
function onPageChange(page: number) {
  currentPage.value = page
}

function onPageRendered(info: {
  pageNumber: number
  width: number
  height: number
  naturalWidth: number
  naturalHeight: number
}) {
  canvasWidth.value = info.width
  canvasHeight.value = info.height
  naturalWidth.value = info.naturalWidth
  naturalHeight.value = info.naturalHeight
}

// ---------- 生命周期 ----------
onMounted(async () => {
  await fetchDocument()
  if (taskIdFromUrl) {
    startProgress(taskIdFromUrl)
  }
})
</script>

<template>
  <div class="flex h-full flex-col gap-4">
    <!-- 页头 -->
    <PageHeader
      :title="document?.filename || '解析查看'"
      :description="document ? `DOC-${document.id.slice(0, 8)}` : '加载中…'"
    >
      <template #actions>
        <div class="flex items-center gap-2">
          <StatusBadge v-if="document" :status="document.status" kind="document" />
          <Button
            v-if="showStartButton"
            :disabled="taskStatus === 'queued'"
            @click="submitParse"
          >
            <template v-if="taskStatus === 'queued'">
              <Loader2 class="size-4 animate-spin" :stroke-width="1.5" />
              提交中
            </template>
            <template v-else>
              <Play class="size-4" :stroke-width="1.5" />
              开始 OCR 解析
            </template>
          </Button>
        </div>
      </template>
    </PageHeader>

    <!-- 进度条 -->
    <Card v-if="showProgress" class="bg-muted/30">
      <CardContent class="flex items-center gap-4 p-4">
        <div class="flex-1 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">
              {{ taskMessage || '任务处理中…' }}
            </span>
            <span class="font-mono text-xs text-muted-foreground">{{ progress }}%</span>
          </div>
          <Progress
            :value="progress"
            :indicator-class="progressIndicatorClass"
            class="h-1.5"
          />
        </div>
      </CardContent>
    </Card>

    <!-- 加载态 -->
    <div v-if="loading" class="grid min-h-[400px] grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardContent class="p-4">
          <Skeleton class="h-[420px] w-full" />
        </CardContent>
      </Card>
      <Card>
        <CardContent class="space-y-3 p-4">
          <Skeleton class="h-6 w-32" />
          <Skeleton class="h-4 w-full" />
          <Skeleton class="h-4 w-full" />
          <Skeleton class="h-4 w-2/3" />
        </CardContent>
      </Card>
    </div>

    <!-- 加载失败 -->
    <EmptyState
      v-else-if="!document"
      :icon="FileQuestion"
      title="无法加载文档"
      description="文档可能已被删除或暂时无法访问"
      class="min-h-[400px]"
    />

    <!-- 双栏布局：左 PDF 原文 / 右 OCR 文本 -->
    <div v-else class="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
      <!-- 左栏：PDF 预览 + BoundingBox -->
      <Card class="flex min-h-0 flex-col overflow-hidden">
        <div class="flex shrink-0 items-center justify-between border-b border-border px-4 py-2.5">
          <div class="flex items-center gap-2">
            <FileText class="size-4 text-muted-foreground" :stroke-width="1.5" />
            <span class="text-sm font-medium text-foreground">原文档</span>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="totalPages" class="font-mono text-xs text-muted-foreground">
              {{ totalPages }} 页
            </span>
            <div v-if="regions.length" class="flex items-center gap-1">
              <Badge variant="secondary" class="text-[10px]">
                {{ regions.length }} 区域
              </Badge>
            </div>
          </div>
        </div>
        <div class="min-h-0 flex-1">
          <PdfViewer
            ref="pdfViewerRef"
            :src="pdfUrl"
            :page="currentPage"
            :scale="1.2"
            @page-change="onPageChange"
            @total-pages-change="totalPages = $event"
            @page-rendered="onPageRendered"
          >
            <template #default="{ width, height, naturalWidth: nW, naturalHeight: nH, pageNumber }">
              <svg
                v-if="regions.length && width > 0"
                class="pointer-events-none absolute left-0 top-0"
                :width="width"
                :height="height"
                :viewBox="`0 0 ${width} ${height}`"
              >
                <g
                  v-for="rect in bboxRects(nW, nH, width, height, pageNumber)"
                  :key="rect.key"
                >
                  <!-- 选中状态：填充半透明 + 粗描边 + 脉动动画 -->
                  <rect
                    v-if="rect.selected"
                    :x="rect.x - 2"
                    :y="rect.y - 2"
                    :width="rect.w + 4"
                    :height="rect.h + 4"
                    :fill="rect.color"
                    fill-opacity="0.25"
                    :stroke="rect.color"
                    stroke-width="3"
                    style="pointer-events: all; animation: pulse 1.5s ease-in-out infinite"
                    @click.stop="locateInTextList(rect)"
                  >
                    <title>
                      {{ rect.label }} · 已选中（点击定位文本）
                    </title>
                  </rect>
                  <!-- 普通状态：透明填充 + 细描边 -->
                  <rect
                    v-else
                    :x="rect.x"
                    :y="rect.y"
                    :width="rect.w"
                    :height="rect.h"
                    fill="transparent"
                    :stroke="rect.color"
                    stroke-width="1.5"
                    style="pointer-events: all; cursor: pointer"
                    @click.stop="locateInTextList(rect)"
                  >
                    <title>
                      {{ rect.label }} · 置信度 {{ rect.confidence ?? '-' }}（点击定位文本）
                    </title>
                  </rect>
                </g>
              </svg>
            </template>
          </PdfViewer>
        </div>
        <!-- 区域图例 -->
        <div v-if="regions.length" class="flex shrink-0 flex-wrap items-center gap-3 border-t border-border px-4 py-2">
          <span class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">区域类型</span>
          <div
            v-for="(count, type) in regionStats"
            :key="type"
            class="flex items-center gap-1.5"
          >
            <span
              class="inline-block size-2 rounded-full"
              :style="{ backgroundColor: REGION_COLORS[type] || '#64748b' }"
            />
            <span class="text-xs text-muted-foreground">{{ REGION_LABELS[type] || type }}</span>
            <span class="font-mono text-[10px] text-muted-foreground/70">{{ count }}</span>
          </div>
          <div class="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground">
            <MapPin class="size-3" :stroke-width="1.5" />
            点击区域可在右侧定位
          </div>
        </div>
      </Card>

      <!-- 右栏：OCR 文本 / 抽取数据 / 结构化 -->
      <Card class="flex min-h-0 flex-col overflow-hidden">
        <Tabs v-model="activeTab" class="flex h-full flex-col">
          <div class="shrink-0 border-b border-border px-3 pt-3">
            <TabsList class="bg-transparent p-0 shadow-none">
              <TabsTrigger
                value="ocr"
                class="data-[state=active]:bg-muted/60 data-[state=active]:shadow-none"
              >
                <AlignLeft class="size-3.5" :stroke-width="1.5" />
                OCR 文本
                <Badge v-if="ocrBlocks.length" variant="secondary" class="ml-1 text-[10px]">
                  {{ ocrBlocks.length }}
                </Badge>
              </TabsTrigger>
              <TabsTrigger
                value="extraction"
                class="data-[state=active]:bg-muted/60 data-[state=active]:shadow-none"
              >
                <Braces class="size-3.5" :stroke-width="1.5" />
                抽取数据
              </TabsTrigger>
              <TabsTrigger
                value="structured"
                class="data-[state=active]:bg-muted/60 data-[state=active]:shadow-none"
              >
                <FileText class="size-3.5" :stroke-width="1.5" />
                结构化
              </TabsTrigger>
            </TabsList>
          </div>

          <div class="min-h-0 flex-1 overflow-hidden">
            <!-- OCR 文本（可点击定位） -->
            <TabsContent v-if="activeTab === 'ocr'" value="ocr" class="m-0 mt-0 h-full">
              <div v-if="ocrBlocks.length" class="flex h-full flex-col">
                <!-- 工具栏 -->
                <div class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
                  <div class="relative flex-1">
                    <Search class="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
                    <Input
                      v-model="searchKeyword"
                      placeholder="搜索 OCR 文本…"
                      class="h-7 pl-7 text-xs"
                    />
                  </div>
                  <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="copyText">
                    <Copy class="size-3.5" :stroke-width="1.5" />
                    复制全文
                  </Button>
                </div>

                <!-- 块列表（按页分组） -->
                <div class="min-h-0 flex-1 overflow-auto p-3">
                  <!-- 搜索结果模式 -->
                  <div v-if="searchKeyword.trim()" class="space-y-2">
                    <div class="mb-2 text-xs text-muted-foreground">
                      匹配 {{ searchResults.length }} 个区域
                    </div>
                    <button
                      v-for="block in searchResults"
                      :key="block.key"
                      type="button"
                      :data-block-key="block.key"
                      class="block w-full rounded-md border border-border bg-background p-3 text-left transition-colors hover:border-primary hover:bg-primary/5"
                      :class="{ 'border-primary bg-primary/10 ring-1 ring-primary': selectedRegionKey === block.key }"
                      @click="locateInPdf(block)"
                    >
                      <div class="mb-1 flex items-center gap-2">
                        <span
                          class="inline-block size-2 rounded-full"
                          :style="{ backgroundColor: block.color }"
                        />
                        <span class="text-[10px] font-medium text-muted-foreground">{{ block.typeLabel }}</span>
                        <span class="font-mono text-[10px] text-muted-foreground">P{{ block.page }}</span>
                      </div>
                      <p class="line-clamp-3 whitespace-pre-wrap break-words text-xs text-foreground">
                        {{ block.text || '(空)' }}
                      </p>
                    </button>
                  </div>

                  <!-- 全量模式：按页分组 -->
                  <div v-else class="space-y-4">
                    <div
                      v-for="[page, blocks] in ocrBlocksByPage"
                      :key="page"
                      class="space-y-2"
                    >
                      <div class="sticky top-0 z-10 flex items-center gap-2 bg-background/80 px-2 py-1 backdrop-blur">
                        <span class="text-xs font-medium text-muted-foreground">第 {{ page }} 页</span>
                        <Badge variant="outline" class="text-[10px]">{{ blocks.length }} 块</Badge>
                        <div class="ml-auto h-px flex-1 bg-border" />
                      </div>
                      <button
                        v-for="block in blocks"
                        :key="block.key"
                        type="button"
                        :data-block-key="block.key"
                        class="block w-full rounded-md border border-border bg-background p-3 text-left transition-colors hover:border-primary hover:bg-primary/5"
                        :class="{ 'border-primary bg-primary/10 ring-1 ring-primary': selectedRegionKey === block.key }"
                        @click="locateInPdf(block)"
                      >
                        <div class="mb-1 flex items-center gap-2">
                          <span
                            class="inline-block size-2 rounded-full"
                            :style="{ backgroundColor: block.color }"
                          />
                          <span class="text-[10px] font-medium text-muted-foreground">{{ block.typeLabel }}</span>
                          <span
                            v-if="block.confidence !== undefined && block.confidence !== null"
                            class="font-mono text-[10px] text-muted-foreground/70"
                          >
                            置信度 {{ Math.round((block.confidence as number) * 100) }}%
                          </span>
                          <MapPin
                            v-if="selectedRegionKey === block.key"
                            class="ml-auto size-3 text-primary"
                            :stroke-width="2"
                          />
                        </div>
                        <p class="whitespace-pre-wrap break-words text-xs leading-relaxed text-foreground">
                          {{ block.text || '(空文本)' }}
                        </p>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <EmptyState
                v-else
                :icon="AlignLeft"
                title="文档尚未解析"
                description="OCR 解析完成后将在此显示按区域切分的文本内容"
                class="py-12"
              />
            </TabsContent>

            <!-- 抽取数据 -->
            <TabsContent v-else-if="activeTab === 'extraction'" value="extraction" class="m-0 mt-0">
              <EmptyState
                v-if="extractionRows.length === 0"
                :icon="Braces"
                title="文档尚未解析"
                description="点击右上角「开始 OCR 解析」以启动抽取任务"
                class="py-12"
              />
              <table v-else class="w-full text-sm">
                <thead class="sticky top-0 z-10 bg-muted/60 backdrop-blur">
                  <tr class="border-b border-border text-left text-xs text-muted-foreground">
                    <th class="px-4 py-2 font-medium">字段名</th>
                    <th class="px-4 py-2 font-medium">字段值</th>
                    <th class="w-24 px-4 py-2 font-medium">类型</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-border">
                  <tr
                    v-for="row in extractionRows"
                    :key="row.name"
                    class="transition-colors hover:bg-muted/30"
                  >
                    <td class="px-4 py-2.5 font-mono text-xs text-foreground">{{ row.name }}</td>
                    <td class="max-w-[300px] truncate px-4 py-2.5 text-foreground" :title="row.value">
                      {{ row.value }}
                    </td>
                    <td class="px-4 py-2.5">
                      <Badge variant="outline" class="font-mono text-[10px]">{{ row.type }}</Badge>
                    </td>
                  </tr>
                </tbody>
              </table>
            </TabsContent>

            <!-- 结构化 -->
            <TabsContent v-else value="structured" class="m-0 mt-0">
              <EmptyState
                v-if="structuredEntries.length === 0"
                :icon="FileText"
                title="文档尚未解析"
                description="结构化数据将在解析完成后显示"
                class="py-12"
              />
              <dl v-else class="divide-y divide-border">
                <div
                  v-for="[key, val] in structuredEntries"
                  :key="key"
                  class="grid grid-cols-3 gap-3 px-4 py-3 transition-colors hover:bg-muted/30"
                >
                  <dt class="font-mono text-xs text-muted-foreground">{{ key }}</dt>
                  <dd class="col-span-2 break-words text-sm text-foreground">
                    {{ formatValue(val) || '-' }}
                  </dd>
                </div>
              </dl>
            </TabsContent>
          </div>
        </Tabs>
      </Card>
    </div>
  </div>
</template>

<style scoped>
@keyframes pulse {
  0%,
  100% {
    fill-opacity: 0.25;
  }
  50% {
    fill-opacity: 0.45;
  }
}
</style>
