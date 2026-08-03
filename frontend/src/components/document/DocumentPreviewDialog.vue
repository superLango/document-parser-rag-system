<script setup lang="ts">
/**
 * 文档预览对话框
 *
 * 根据文件类型选择预览方式：
 * - PDF：复用 PdfViewer（携带鉴权 fetch ArrayBuffer）
 * - 图片（png/jpg/jpeg/tiff/bmp）：fetch blob → object URL → img，可叠加 OCR 框
 * - 文本/markdown：getOcrText 获取 parsed_text → MarkdownRenderer
 * - 其他：提示下载查看
 *
 * 数据隔离：所有请求走 /kbs/{kb_id}/documents/{id}/preview|ocr-text，后端 RLS 强制
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { FileText, Image as ImageIcon, FileWarning, Download, Loader2 } from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { downloadBlob } from '@/composables/useDownload'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import PdfViewer from '@/components/PdfViewer.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

interface Props {
  /** 是否打开 */
  open: boolean
  /** 知识库 ID */
  kbId: string
  /** 文档 ID */
  documentId: string
  /** 文件名（用于判断类型与下载名） */
  filename: string
}

const props = defineProps<Props>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

type PreviewKind = 'pdf' | 'image' | 'text' | 'unsupported'

const loading = ref(false)
const error = ref<string | null>(null)
/** 图片 object URL */
const imageUrl = ref<string | null>(null)
/** OCR 解析文本（文本类预览） */
const parsedText = ref<string>('')
/** OCR 布局数据（图片框叠加，暂留接口） */
const layoutData = ref<unknown>(null)

const ext = computed(() => {
  const idx = props.filename.lastIndexOf('.')
  return idx >= 0 ? props.filename.slice(idx).toLowerCase() : ''
})

const previewKind = computed<PreviewKind>(() => {
  const e = ext.value
  if (e === '.pdf') return 'pdf'
  if (['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'].includes(e)) return 'image'
  if (['.txt', '.md', '.json'].includes(e)) return 'text'
  return 'unsupported'
})

/** PDF 预览 URL（PdfViewer 内部携带 token fetch） */
const pdfSrc = computed(() => `/api/v1/kbs/${props.kbId}/documents/${props.documentId}/preview`)

const dialogTitle = computed(() => `预览：${props.filename}`)

async function loadPreview() {
  if (!props.open) return
  loading.value = true
  error.value = null
  // 重置
  if (imageUrl.value) {
    URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = null
  }
  parsedText.value = ''
  layoutData.value = null

  try {
    if (previewKind.value === 'image') {
      const blob = await kbApi.previewDocument(props.kbId, props.documentId)
      imageUrl.value = URL.createObjectURL(blob)
    } else if (previewKind.value === 'text') {
      const data = await kbApi.getOcrText(props.kbId, props.documentId)
      parsedText.value = data.parsed_text || '（暂无解析文本）'
      layoutData.value = data.layout_data
    }
    // pdf 由 PdfViewer 自行加载；unsupported 无需加载
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function handleDownload() {
  try {
    const blob = await kbApi.downloadDocument(props.kbId, props.documentId)
    downloadBlob(blob, props.filename)
  } catch {
    // 错误已由拦截器提示
  }
}

watch(
  () => props.open,
  (val) => {
    if (val) loadPreview()
  },
)

onBeforeUnmount(() => {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
})
</script>

<template>
  <Dialog
    :open="open"
    :title="dialogTitle"
    class="max-w-4xl"
    @update:open="emit('update:open', $event)"
  >
    <!-- 操作栏 -->
    <div class="mb-3 flex items-center justify-between">
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <component
          :is="previewKind === 'pdf' ? FileText : previewKind === 'image' ? ImageIcon : FileWarning"
          class="size-4"
          :stroke-width="1.5"
        />
        <span>{{ previewKind === 'unsupported' ? '该类型不支持在线预览' : '在线预览' }}</span>
      </div>
      <Button variant="outline" size="sm" @click="handleDownload">
        <Download class="size-4" :stroke-width="1.5" />
        下载
      </Button>
    </div>

    <!-- 预览区 -->
    <div class="min-h-[300px]">
      <!-- 加载态 -->
      <div v-if="loading" class="flex flex-col items-center justify-center gap-3 py-16">
        <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
        <p class="text-sm text-muted-foreground">加载中...</p>
      </div>

      <!-- 错误态 -->
      <div v-else-if="error" class="flex flex-col items-center justify-center gap-3 py-16">
        <FileWarning class="size-8 text-danger" :stroke-width="1.5" />
        <p class="text-sm text-danger">{{ error }}</p>
        <Button variant="outline" size="sm" @click="loadPreview">重试</Button>
      </div>

      <!-- PDF -->
      <div v-else-if="previewKind === 'pdf'" class="h-[70vh] overflow-auto rounded border border-border bg-muted/30">
        <PdfViewer :src="pdfSrc" />
      </div>

      <!-- 图片 -->
      <div v-else-if="previewKind === 'image' && imageUrl" class="flex items-center justify-center rounded border border-border bg-muted/30 p-4">
        <img
          :src="imageUrl"
          :alt="filename"
          class="max-h-[70vh] max-w-full object-contain"
        />
      </div>

      <!-- 文本 -->
      <div v-else-if="previewKind === 'text'" class="h-[70vh] overflow-auto rounded border border-border bg-background p-4">
        <MarkdownRenderer v-if="ext === '.md'" :content="parsedText" />
        <pre v-else class="whitespace-pre-wrap break-words font-mono text-sm text-foreground">{{ parsedText }}</pre>
      </div>

      <!-- 不支持 -->
      <div v-else class="flex flex-col items-center justify-center gap-3 py-16">
        <FileWarning class="size-8 text-muted-foreground" :stroke-width="1.5" />
        <p class="text-sm text-muted-foreground">该文件类型不支持在线预览，请下载后查看</p>
        <Button variant="outline" size="sm" @click="handleDownload">
          <Download class="size-4" :stroke-width="1.5" />
          下载文件
        </Button>
      </div>
    </div>
  </Dialog>
</template>
