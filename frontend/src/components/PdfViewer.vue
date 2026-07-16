<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
// Vite 通过 ?url 后缀将 worker 以 URL 形式导入
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { PDFDocumentProxy } from 'pdfjs-dist'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

interface Props {
  /** PDF 文件下载 URL（需鉴权，组件内部用 fetch 获取 ArrayBuffer） */
  src: string
  /** 当前页码（1-based） */
  page?: number
  /** 初始缩放比例 */
  scale?: number
}

const props = withDefaults(defineProps<Props>(), {
  page: 1,
  scale: 1.2,
})

const emit = defineEmits<{
  (e: 'page-change', page: number): void
  (e: 'total-pages-change', total: number): void
  (
    e: 'page-rendered',
    info: {
      pageNumber: number
      width: number
      height: number
      naturalWidth: number
      naturalHeight: number
      scale: number
    },
  ): void
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const pdfDoc = ref<PDFDocumentProxy | null>(null)
const totalPages = ref(0)
const currentPage = ref(props.page)
const currentScale = ref(props.scale)
const loading = ref(false)
const errorMsg = ref('')
// canvas CSS 尺寸与 PDF 原始（scale=1）尺寸，供插槽消费方叠加覆盖层
const canvasW = ref(0)
const canvasH = ref(0)
const naturalW = ref(0)
const naturalH = ref(0)

// 渲染令牌：避免快速翻页/缩放时的并发渲染竞态
let renderToken = 0

/**
 * 加载 PDF 文档
 * 通过 fetch 携带 Authorization 头获取 ArrayBuffer，再交给 pdfjs 解析
 */
async function loadPdf() {
  if (!props.src) return
  loading.value = true
  errorMsg.value = ''
  // 释放旧文档
  if (pdfDoc.value) {
    pdfDoc.value.destroy()
    pdfDoc.value = null
  }
  try {
    const token = localStorage.getItem('token')
    const resp = await fetch(props.src, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!resp.ok) {
      errorMsg.value = `文档加载失败（HTTP ${resp.status}）`
      loading.value = false
      return
    }
    const data = await resp.arrayBuffer()
    const doc = await pdfjsLib.getDocument({ data }).promise
    pdfDoc.value = doc
    totalPages.value = doc.numPages
    emit('total-pages-change', doc.numPages)
    // 修正当前页越界
    if (currentPage.value > doc.numPages) {
      currentPage.value = doc.numPages
      emit('page-change', currentPage.value)
    }
    await renderPage()
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : 'PDF 解析失败'
  } finally {
    loading.value = false
  }
}

/**
 * 渲染当前页到 canvas
 */
async function renderPage() {
  const doc = pdfDoc.value
  const canvas = canvasRef.value
  if (!doc || !canvas) return
  const token = ++renderToken

  try {
    const page = await doc.getPage(currentPage.value)
    if (token !== renderToken) return // 已有更新的渲染请求

    const viewport = page.getViewport({ scale: currentScale.value })
    const baseViewport = page.getViewport({ scale: 1 })
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = `${Math.floor(viewport.width)}px`
    canvas.style.height = `${Math.floor(viewport.height)}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    await page.render({ canvasContext: ctx, viewport }).promise
    if (token !== renderToken) return

    canvasW.value = Math.floor(viewport.width)
    canvasH.value = Math.floor(viewport.height)
    naturalW.value = Math.floor(baseViewport.width)
    naturalH.value = Math.floor(baseViewport.height)

    emit('page-rendered', {
      pageNumber: currentPage.value,
      width: canvasW.value,
      height: canvasH.value,
      naturalWidth: naturalW.value,
      naturalHeight: naturalH.value,
      scale: currentScale.value,
    })
  } catch (err) {
    if (token !== renderToken) return
    errorMsg.value = err instanceof Error ? err.message : '页面渲染失败'
  }
}

function prevPage() {
  if (currentPage.value <= 1) return
  currentPage.value--
  emit('page-change', currentPage.value)
  renderPage()
}

function nextPage() {
  if (currentPage.value >= totalPages.value) return
  currentPage.value++
  emit('page-change', currentPage.value)
  renderPage()
}

function zoomIn() {
  currentScale.value = Math.min(currentScale.value + 0.2, 4)
  renderPage()
}

function zoomOut() {
  currentScale.value = Math.max(currentScale.value - 0.2, 0.4)
  renderPage()
}

function resetZoom() {
  currentScale.value = props.scale
  renderPage()
}

// 外部 page 变化时同步并重新渲染
watch(
  () => props.page,
  (val) => {
    if (val && val !== currentPage.value) {
      currentPage.value = val
      renderPage()
    }
  },
)

onMounted(loadPdf)

defineExpose({ loadPdf, renderPage })
</script>

<template>
  <div class="pdf-viewer">
    <!-- 工具栏 -->
    <div class="pdf-toolbar">
      <div class="nav-group">
        <el-button
          size="small"
          :disabled="currentPage <= 1 || loading"
          @click="prevPage"
        >
          上一页
        </el-button>
        <span class="page-indicator mono">
          {{ totalPages ? currentPage : '—' }} / {{ totalPages || '—' }}
        </span>
        <el-button
          size="small"
          :disabled="currentPage >= totalPages || loading"
          @click="nextPage"
        >
          下一页
        </el-button>
      </div>
      <div class="zoom-group">
        <el-button size="small" :disabled="loading" @click="zoomOut">−</el-button>
        <span class="scale-indicator mono">
          {{ Math.round(currentScale * 100) }}%
        </span>
        <el-button size="small" :disabled="loading" @click="zoomIn">+</el-button>
        <el-button size="small" :disabled="loading" @click="resetZoom">
          重置
        </el-button>
      </div>
    </div>

    <!-- 画布区域 -->
    <div class="pdf-stage" v-loading="loading">
      <div v-if="errorMsg" class="pdf-error">
        <el-empty :description="errorMsg" :image-size="60" />
      </div>
      <div v-else class="canvas-wrapper">
        <canvas ref="canvasRef" class="pdf-canvas" />
        <!-- 作用域插槽：向父组件暴露 canvas 尺寸与原始页面尺寸，
             供其叠加 BoundingBox SVG 覆盖层 -->
        <slot
          v-if="canvasW > 0"
          :width="canvasW"
          :height="canvasH"
          :naturalWidth="naturalW"
          :naturalHeight="naturalH"
          :scale="currentScale"
          :pageNumber="currentPage"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.pdf-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
}

.pdf-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-base);
  flex-shrink: 0;

  .nav-group,
  .zoom-group {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .page-indicator,
  .scale-indicator {
    font-size: var(--fs-xs);
    color: var(--text-secondary);
    min-width: 56px;
    text-align: center;
  }
}

.pdf-stage {
  flex: 1;
  overflow: auto;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 16px;
  background: var(--bg-base);
}

.canvas-wrapper {
  position: relative;
  display: inline-block;
  box-shadow: 0 0 0 1px var(--border-light);
}

.pdf-canvas {
  display: block;
  background: #fff;
}

.pdf-error {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
}
</style>
