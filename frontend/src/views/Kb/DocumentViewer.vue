<script setup lang="ts">
/**
 * 文档查看页面（解析结果查看器）
 *
 * 布局：左右分栏
 * - 左侧：原文档预览（图片/PDF）
 * - 右侧：按钮切换查看
 *   - BBox：在原图上叠加版面检测框，下方显示块列表
 *   - MD：Markdown 格式的 OCR 解析文本
 *   - JSON：结构化抽取结果（JSON 格式）
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Download,
  Layers,
  FileText,
  Braces,
  Loader2,
  AlertCircle,
  ZoomIn,
  ZoomOut,
  RotateCcw,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { downloadBlob } from '@/composables/useDownload'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import PdfViewer from '@/components/PdfViewer.vue'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => route.params.kb_id as string)
const documentId = computed(() => route.params.doc_id as string)

// 数据状态
const loading = ref(true)
const error = ref<string | null>(null)
const docData = ref<{
  document_id: string
  filename: string
  parsed_text: string
  layout_data: any
  structured_data: Record<string, any> | null
  status: string
  file_type: string
} | null>(null)

// 原文档预览
const imageUrl = ref<string | null>(null)
const pdfSrc = computed(() => `/api/v1/kbs/${kbId.value}/documents/${documentId.value}/preview`)

// 图片缩放
const scale = ref(1)

// 右侧当前激活的 tab
const activeTab = ref<'bbox' | 'md' | 'json'>('md')

const ext = computed(() => {
  if (!docData.value) return ''
  const idx = docData.value.filename.lastIndexOf('.')
  return idx >= 0 ? docData.value.filename.slice(idx).toLowerCase() : ''
})

const isImage = computed(() => ['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.webp'].includes(ext.value))
const isPdf = computed(() => ext.value === '.pdf')

// bbox 颜色映射
const bboxColors = [
  '#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899',
]

function getBboxColor(type: string, idx: number): string {
  const typeHash = type.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  return bboxColors[typeHash % bboxColors.length]
}

function getBboxLabel(type: string): string {
  const labels: Record<string, string> = {
    title: '标题', text: '正文', table: '表格', figure: '图片',
    formula: '公式', header: '页眉', footer: '页脚', list: '列表',
    caption: '图注', reference: '参考文献', abstract: '摘要',
  }
  return labels[type] || type
}

async function loadDocument() {
  loading.value = true
  error.value = null
  try {
    const data = await kbApi.getOcrText(kbId.value, documentId.value)
    docData.value = data

    if (isImage.value) {
      const blob = await kbApi.previewDocument(kbId.value, documentId.value)
      if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
      imageUrl.value = URL.createObjectURL(blob)
    }
  } catch (err: any) {
    error.value = err?.message || '加载文档失败'
  } finally {
    loading.value = false
  }
}

function handleBack() {
  router.push(`/kbs/${kbId.value}/documents`)
}

async function handleDownload() {
  if (!docData.value) return
  try {
    const blob = await kbApi.downloadDocument(kbId.value, documentId.value)
    downloadBlob(blob, docData.value.filename)
  } catch {
    // 错误由拦截器提示
  }
}

function zoomIn() {
  scale.value = Math.min(scale.value + 0.2, 3)
}

function zoomOut() {
  scale.value = Math.max(scale.value - 0.2, 0.3)
}

function resetZoom() {
  scale.value = 1
}

// BBox 数据规范化
// 后端 layout_data 结构：{ ocr_layout, merged, ocr_json, total_pages, ... }
// 每个块字段：block_content, page_index, block_type, block_id, bbox([x1,y1,x2,y2])
const normalizedBboxes = computed(() => {
  if (!docData.value?.layout_data) return []
  const raw = docData.value.layout_data
  // 优先取 merged（清洗后的版面块），其次 ocr_layout（原始 OCR 版面块）
  let blocks: any[] = []
  if (Array.isArray(raw)) {
    blocks = raw
  } else if (Array.isArray(raw.merged) && raw.merged.length > 0) {
    blocks = raw.merged
  } else if (Array.isArray(raw.ocr_layout)) {
    blocks = raw.ocr_layout
  } else if (raw.pages) {
    blocks = raw.pages.flatMap((p: any) => p.blocks || p.elements || [])
  } else if (raw.blocks) {
    blocks = raw.blocks
  }
  return blocks.map((b, i) => {
    // bbox 格式 [x1, y1, x2, y2]
    let box = b.bbox || b.box || b.coordinates || [0, 0, 0, 0]
    let x: number, y: number, w: number, h: number
    if (Array.isArray(box)) {
      if (box.length === 4) {
        if (box[2] > 1 && box[3] > 1 && box[0] < box[2] && box[1] < box[3]) {
          // [x1, y1, x2, y2] 格式
          x = box[0]; y = box[1]; w = box[2] - box[0]; h = box[3] - box[1]
        } else {
          // [x, y, w, h] 格式
          [x, y, w, h] = box
        }
      } else {
        x = 0; y = 0; w = 0; h = 0
      }
    } else {
      x = box.x || 0; y = box.y || 0; w = box.w || box.width || 0; h = box.h || box.height || 0
    }
    // 字段映射：后端 block_type / block_content
    const type = b.block_type || b.type || b.category || b.label || 'text'
    const text = b.block_content || b.text || b.content || ''
    return {
      idx: i,
      type,
      label: getBboxLabel(type),
      color: getBboxColor(type, i),
      x: Math.max(0, x),
      y: Math.max(0, y),
      w: Math.max(0, w),
      h: Math.max(0, h),
      text,
      page: b.page_index || b.page || 0,
      blockId: b.block_id || (i + 1),
    }
  }).filter(b => b.w > 0 && b.h > 0)
})

// 唯一类型列表（用于图例）
const bboxTypes = computed(() => {
  const map = new Map<string, { label: string; color: string }>()
  normalizedBboxes.value.forEach(b => {
    if (!map.has(b.type)) {
      map.set(b.type, { label: b.label, color: b.color })
    }
  })
  return Array.from(map.entries()).map(([type, info]) => ({ type, ...info }))
})

// JSON 格式化展示
// 优先显示 structured_data（schema 抽取结果），无则显示 ocr_json（OCR 完整结果）
const jsonData = computed(() => {
  if (docData.value?.structured_data) {
    return docData.value.structured_data
  }
  // 兜底：从 layout_data 取 OCR 完整 JSON
  const layout = docData.value?.layout_data
  if (layout && typeof layout === 'object' && !Array.isArray(layout)) {
    const ocrJson = (layout as any).ocr_json
    if (ocrJson) {
      try {
        return typeof ocrJson === 'string' ? JSON.parse(ocrJson) : ocrJson
      } catch {
        return ocrJson
      }
    }
    // 再兜底：显示 merged 版面块
    if (Array.isArray((layout as any).merged) && (layout as any).merged.length > 0) {
      return (layout as any).merged
    }
  }
  return null
})

const jsonSource = computed<'structured' | 'ocr' | null>(() => {
  if (docData.value?.structured_data) return 'structured'
  if (jsonData.value) return 'ocr'
  return null
})

const formattedJson = computed(() => {
  if (!jsonData.value) return ''
  try {
    return JSON.stringify(jsonData.value, null, 2)
  } catch {
    return String(jsonData.value)
  }
})

const statusConfig: Record<string, { color: string; label: string }> = {
  pending: { color: 'bg-muted text-muted-foreground', label: '待处理' },
  processing: { color: 'bg-warning/10 text-warning', label: '处理中' },
  completed: { color: 'bg-success/10 text-success', label: '已完成' },
  failed: { color: 'bg-danger/10 text-danger', label: '失败' },
}

const tabs = [
  { key: 'bbox' as const, label: 'BBox 标注', icon: Layers },
  { key: 'md' as const, label: 'Markdown', icon: FileText },
  { key: 'json' as const, label: 'JSON', icon: Braces },
]

onMounted(() => {
  loadDocument()
})
</script>

<template>
  <div class="flex h-screen flex-col bg-background">
    <!-- 顶部工具栏 -->
    <header class="flex items-center justify-between border-b border-border px-4 py-3">
      <div class="flex items-center gap-3">
        <Button variant="ghost" size="sm" @click="handleBack">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回
        </Button>
        <div class="h-5 w-px bg-border" />
        <div>
          <h1 class="text-sm font-medium text-foreground">
            {{ docData?.filename || '加载中...' }}
          </h1>
          <div class="mt-0.5 flex items-center gap-2">
            <Badge
              v-if="docData?.status"
              variant="secondary"
              :class="statusConfig[docData.status]?.color"
              class="text-xs"
            >
              {{ statusConfig[docData.status]?.label || docData.status }}
            </Badge>
            <span v-if="docData?.file_type" class="text-xs text-muted-foreground uppercase">
              {{ docData.file_type }}
            </span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="resetZoom" title="重置缩放">
          <RotateCcw class="size-4" :stroke-width="1.5" />
        </Button>
        <Button variant="outline" size="sm" @click="zoomOut" title="缩小">
          <ZoomOut class="size-4" :stroke-width="1.5" />
        </Button>
        <span class="min-w-[3rem] text-center text-xs text-muted-foreground">
          {{ Math.round(scale * 100) }}%
        </span>
        <Button variant="outline" size="sm" @click="zoomIn" title="放大">
          <ZoomIn class="size-4" :stroke-width="1.5" />
        </Button>
        <div class="h-5 w-px bg-border" />
        <Button variant="outline" size="sm" @click="handleDownload">
          <Download class="size-4" :stroke-width="1.5" />
          下载原文
        </Button>
      </div>
    </header>

    <!-- 主体：左右分栏 -->
    <div class="flex flex-1 overflow-hidden">
      <!-- 左侧：原文档预览 -->
      <div class="flex w-1/2 flex-col border-r border-border">
        <div class="border-b border-border px-4 py-2">
          <span class="text-xs font-medium text-muted-foreground">原始文档</span>
        </div>
        <div class="flex-1 overflow-auto bg-muted/20 p-4">
          <!-- 加载态 -->
          <div v-if="loading" class="space-y-3">
            <Skeleton class="h-4 w-3/4" />
            <Skeleton class="h-4 w-full" />
            <Skeleton class="h-4 w-5/6" />
            <Skeleton class="h-64 w-full" />
          </div>

          <!-- 错误态 -->
          <div v-else-if="error" class="flex flex-col items-center justify-center gap-3 py-16">
            <AlertCircle class="size-8 text-danger" :stroke-width="1.5" />
            <p class="text-sm text-danger">{{ error }}</p>
            <Button variant="outline" size="sm" @click="loadDocument">重试</Button>
          </div>

          <!-- PDF 预览 -->
          <div v-else-if="isPdf" class="h-full overflow-auto rounded bg-background shadow">
            <PdfViewer :src="pdfSrc" />
          </div>

          <!-- 图片预览（带 bbox 叠加） -->
          <div v-else-if="isImage && imageUrl" class="flex items-start justify-center">
            <div
              class="relative inline-block"
              :style="{ transform: `scale(${scale})`, transformOrigin: 'top center' }"
            >
              <img :src="imageUrl" :alt="docData?.filename" class="block max-w-full" ref="imgEl" />
              <!-- BBox 叠加层（仅在 bbox tab 时显示框） -->
              <svg
                v-if="activeTab === 'bbox'"
                class="pointer-events-none absolute inset-0 h-full w-full"
                xmlns="http://www.w3.org/2000/svg"
              >
                <rect
                  v-for="bbox in normalizedBboxes"
                  :key="bbox.idx"
                  :x="bbox.x"
                  :y="bbox.y"
                  :width="bbox.w"
                  :height="bbox.h"
                  :stroke="bbox.color"
                  stroke-width="2"
                  fill="none"
                />
              </svg>
            </div>
          </div>

          <!-- 其他文件类型 -->
          <div v-else class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
            <FileText class="size-12 opacity-50" :stroke-width="1" />
            <p class="text-sm">该文件类型暂不支持在线预览原始内容</p>
            <Button variant="outline" size="sm" @click="handleDownload">下载文件</Button>
          </div>
        </div>

        <!-- BBox 图例（bbox tab 时显示） -->
        <div v-if="activeTab === 'bbox' && bboxTypes.length > 0" class="border-t border-border p-3">
          <div class="mb-2 text-xs font-medium text-muted-foreground">版面区域标注（{{ normalizedBboxes.length }} 个）</div>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="bt in bboxTypes"
              :key="bt.type"
              class="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs"
            >
              <span class="inline-block size-2 rounded-sm" :style="{ backgroundColor: bt.color }" />
              {{ bt.label }}
            </span>
          </div>
        </div>
      </div>

      <!-- 右侧：解析结果切换 -->
      <div class="flex w-1/2 flex-col">
        <!-- Tab 按钮栏 -->
        <div class="flex items-center gap-1 border-b border-border px-4 py-2">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
            :class="activeTab === tab.key
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
            @click="activeTab = tab.key"
          >
            <component :is="tab.icon" class="size-3.5" :stroke-width="1.5" />
            {{ tab.label }}
          </button>
        </div>

        <!-- Tab 内容区 -->
        <div class="flex-1 overflow-hidden">
          <!-- BBox 文本列表 -->
          <div v-if="activeTab === 'bbox'" class="h-full overflow-auto p-4">
            <div v-if="!docData?.layout_data || normalizedBboxes.length === 0" class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
              <Layers class="size-10 opacity-50" :stroke-width="1" />
              <p class="text-sm">暂无版面标注数据</p>
              <p class="text-xs">请先执行文档解析</p>
            </div>
            <div v-else class="space-y-2">
              <div class="mb-2 text-xs text-muted-foreground">
                共 {{ normalizedBboxes.length }} 个版面块
              </div>
              <div
                v-for="bbox in normalizedBboxes"
                :key="bbox.idx"
                class="rounded-lg border border-border bg-background p-3 transition-colors hover:bg-accent/30"
              >
                <div class="mb-1.5 flex items-center gap-2">
                  <span
                    class="inline-block rounded px-1.5 py-0.5 text-xs font-medium text-white"
                    :style="{ backgroundColor: bbox.color }"
                  >
                    {{ bbox.label }}
                  </span>
                  <span class="text-xs text-muted-foreground">
                    #{{ bbox.blockId }} · 第{{ bbox.page }}页
                  </span>
                  <span class="text-xs text-muted-foreground">
                    ({{ Math.round(bbox.x) }}, {{ Math.round(bbox.y) }}, {{ Math.round(bbox.w) }}×{{ Math.round(bbox.h) }})
                  </span>
                </div>
                <p class="text-sm leading-relaxed text-foreground whitespace-pre-wrap break-words">
                  {{ bbox.text || '（无文本内容）' }}
                </p>
              </div>
            </div>
          </div>

          <!-- Markdown 文本 -->
          <div v-else-if="activeTab === 'md'" class="h-full overflow-auto p-4">
            <div v-if="!docData?.parsed_text" class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
              <FileText class="size-10 opacity-50" :stroke-width="1" />
              <p class="text-sm">暂无 OCR 解析文本</p>
              <p class="text-xs">请先执行文档解析</p>
            </div>
            <div v-else class="prose prose-sm max-w-none dark:prose-invert">
              <MarkdownRenderer :content="docData.parsed_text" />
            </div>
          </div>

          <!-- JSON 结构化数据 -->
          <div v-else-if="activeTab === 'json'" class="h-full overflow-auto p-4">
            <div v-if="!jsonSource" class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
              <Braces class="size-10 opacity-50" :stroke-width="1.5" />
              <p class="text-sm">暂无结构化数据</p>
              <p class="text-xs">请先执行文档解析或结构化抽取任务</p>
            </div>
            <div v-else>
              <div class="mb-2 flex items-center gap-2">
                <Badge
                  :variant="jsonSource === 'structured' ? 'default' : 'secondary'"
                  class="text-[10px]"
                >
                  {{ jsonSource === 'structured' ? '结构化抽取结果' : 'OCR 完整结果' }}
                </Badge>
                <span v-if="jsonSource === 'ocr'" class="text-xs text-muted-foreground">
                  未配置 Schema，显示 OCR 原始 JSON
                </span>
              </div>
              <pre class="rounded-lg border border-border bg-muted/30 p-4 font-mono text-xs leading-relaxed text-foreground overflow-x-auto">{{ formattedJson }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
