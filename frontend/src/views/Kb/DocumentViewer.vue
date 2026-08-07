<script setup lang="ts">
/**
 * 文档查看页面（解析结果查看器）
 *
 * 布局：左右分栏
 * - 左侧：原文档预览（PDF）
 * - 右侧：按钮切换查看
 *   - BBox：在原图上叠加版面检测框，下方显示块列表
 *   - MD：Markdown 格式的 Popo 重建文本
 *   - JSON：Popo 处理后的结构化 JSON
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
  popo_json: Record<string, any> | null
  structured_data: Record<string, any> | null
  status: string
  file_type: string
} | null>(null)

// 原文档预览
const pdfSrc = computed(() => `/api/v1/kbs/${kbId.value}/documents/${documentId.value}/preview`)

// 右侧当前激活的 tab
const activeTab = ref<'bbox' | 'md' | 'json'>('md')

const ext = computed(() => {
  if (!docData.value) return ''
  const idx = docData.value.filename.lastIndexOf('.')
  return idx >= 0 ? docData.value.filename.slice(idx).toLowerCase() : ''
})

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

// BBox 数据规范化
// 后端 layout_data 结构：{ ocr_layout, merged, ocr_json, total_pages, ... }
// 每个块字段：block_content, page_index, block_type, block_id, bbox([x1,y1,x2,y2])
const normalizedBboxes = computed(() => {
  if (!docData.value?.layout_data) return []
  const raw = docData.value.layout_data
  // 优先取 merged（Popo 清洗后的版面块），其次 ocr_layout（原始 OCR 版面块）
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
// 优先显示 popo_json（Popo VLM 处理后的完整文档树 JSON），
// 其次显示 merged 版面块（layout_data.merged）
const jsonData = computed(() => {
  if (docData.value?.popo_json) {
    return docData.value.popo_json
  }
  // 兜底：从 layout_data 取 merged 版面块
  const layout = docData.value?.layout_data
  if (layout && typeof layout === 'object' && !Array.isArray(layout)) {
    if (Array.isArray((layout as any).merged) && (layout as any).merged.length > 0) {
      return (layout as any).merged
    }
    const ocrJson = (layout as any).ocr_json
    if (ocrJson) {
      try {
        return typeof ocrJson === 'string' ? JSON.parse(ocrJson) : ocrJson
      } catch {
        return ocrJson
      }
    }
  }
  return null
})

const jsonSource = computed<'popo' | 'merged' | 'ocr' | null>(() => {
  if (docData.value?.popo_json) return 'popo'
  const layout = docData.value?.layout_data
  if (layout && Array.isArray((layout as any).merged) && (layout as any).merged.length > 0) return 'merged'
  if (jsonData.value) return 'ocr'
  return null
})

const jsonSourceLabel = computed(() => {
  const map = { popo: 'Popo 处理结果', merged: '版面块数据', ocr: 'OCR 原始数据' }
  return jsonSource.value ? map[jsonSource.value] : ''
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
        <Button variant="outline" size="sm" @click="handleDownload">
          <Download class="size-4" :stroke-width="1.5" />
          下载原文
        </Button>
      </div>
    </header>

    <!-- 主体：左右分栏 -->
    <div class="flex flex-1 overflow-hidden">
      <!-- 左侧：原文档预览（PDF） -->
      <div class="flex w-1/2 flex-col border-r border-border">
        <div class="border-b border-border px-4 py-2">
          <span class="text-xs font-medium text-muted-foreground">原始文档</span>
        </div>
        <div class="flex-1 overflow-auto bg-muted/20">
          <!-- 加载态 -->
          <div v-if="loading" class="space-y-3 p-4">
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
          <div v-else-if="isPdf" class="h-full">
            <PdfViewer :src="pdfSrc" />
          </div>

          <!-- 其他文件类型 -->
          <div v-else class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
            <FileText class="size-12 opacity-50" :stroke-width="1" />
            <p class="text-sm">该文件类型暂不支持在线预览</p>
            <Button variant="outline" size="sm" @click="handleDownload">下载文件</Button>
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
          <!-- BBox 版面块列表 -->
          <div v-if="activeTab === 'bbox'" class="h-full overflow-auto p-4">
            <div v-if="!docData?.layout_data || normalizedBboxes.length === 0" class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
              <Layers class="size-10 opacity-50" :stroke-width="1" />
              <p class="text-sm">暂无版面标注数据</p>
              <p class="text-xs">请先执行文档解析</p>
            </div>
            <div v-else class="space-y-2">
              <div class="mb-2 flex items-center justify-between">
                <span class="text-xs text-muted-foreground">
                  共 {{ normalizedBboxes.length }} 个版面块
                </span>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="bt in bboxTypes"
                    :key="bt.type"
                    class="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px]"
                  >
                    <span class="inline-block size-2 rounded-sm" :style="{ backgroundColor: bt.color }" />
                    {{ bt.label }}
                  </span>
                </div>
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
                    #{{ bbox.blockId }} · 第{{ bbox.page + 1 }}页
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
              <p class="text-sm">暂无解析文本</p>
              <p class="text-xs">请先执行文档解析</p>
            </div>
            <div v-else class="prose prose-sm max-w-none dark:prose-invert">
              <MarkdownRenderer :content="docData.parsed_text" />
            </div>
          </div>

          <!-- JSON：Popo 处理结果 -->
          <div v-else-if="activeTab === 'json'" class="h-full overflow-auto p-4">
            <div v-if="!jsonSource" class="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
              <Braces class="size-10 opacity-50" :stroke-width="1.5" />
              <p class="text-sm">暂无 JSON 数据</p>
              <p class="text-xs">请先执行文档解析（Popo 后处理）</p>
            </div>
            <div v-else>
              <div class="mb-2 flex items-center gap-2">
                <Badge
                  :variant="jsonSource === 'popo' ? 'default' : 'secondary'"
                  class="text-[10px]"
                >
                  {{ jsonSourceLabel }}
                </Badge>
              </div>
              <pre class="rounded-lg border border-border bg-muted/30 p-4 font-mono text-xs leading-relaxed text-foreground overflow-x-auto whitespace-pre-wrap break-all">{{ formattedJson }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
