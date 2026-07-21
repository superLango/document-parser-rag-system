<script setup lang="ts">
import { ref, shallowRef, watch, onMounted, nextTick } from 'vue'
// 使用 Vite 标准 import 加载 pdfjs-dist
// 背景：之前误以为 Vite 预构建破坏了 pdfjs-dist 的私有字段，
// 实际上根本原因是 Vue 的 ref 会深层代理 PDFDocumentProxy 对象，
// 导致 pdfjs 内部访问 this.#privateField 时报
// "Cannot read private member #x from an object whose class did not declare it"。
// 解决方案：用 shallowRef 存储 PDFDocumentProxy（只追踪 .value 赋值，不深入代理对象本身）。
import * as pdfjsLib from 'pdfjs-dist'
// 通过 Vite 的 ?url 后缀获取 worker 脚本 URL（Vite 会处理打包和路径解析）
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw, FileWarning } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

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

// 配置 worker（模块加载时执行一次）
// 通过 Vite ?url 导入，确保 worker 与主库版本一致
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const canvasRef = ref<HTMLCanvasElement | null>(null)
// 关键：使用 shallowRef 而非 ref
// PDFDocumentProxy 内部使用 JS 私有字段（#privateField），如果被 Vue 的深层响应式代理包装，
// pdfjs 内部访问 this.#privateField 时会报 "Cannot read private member #x from an object
// whose class did not declare it"。shallowRef 只追踪 .value 的赋值，不会深入包装对象本身。
const pdfDoc = shallowRef<PDFDocumentProxy | null>(null)
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
  if (!props.src) {
    console.warn('[PdfViewer] loadPdf skipped: src is empty')
    return
  }
  console.log('[PdfViewer] loadPdf start, src =', props.src)
  loading.value = true
  errorMsg.value = ''
  // 释放旧文档
  if (pdfDoc.value) {
    pdfDoc.value.destroy()
    pdfDoc.value = null
  }
  try {
    const token = localStorage.getItem('token')
    console.log('[PdfViewer] fetching, has token =', !!token)
    const resp = await fetch(props.src, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    console.log('[PdfViewer] fetch response, status =', resp.status, 'ok =', resp.ok)
    if (!resp.ok) {
      errorMsg.value = `文档加载失败（HTTP ${resp.status}）`
      loading.value = false
      return
    }
    const data = await resp.arrayBuffer()
    console.log('[PdfViewer] received arrayBuffer, size =', data.byteLength)
    // 直接使用顶层 import 的 pdfjsLib（Vite 已处理预构建和 worker 配置）
    const doc = await pdfjsLib.getDocument({ data }).promise
    console.log('[PdfViewer] pdf loaded, numPages =', doc.numPages)
    pdfDoc.value = doc
    totalPages.value = doc.numPages
    emit('total-pages-change', doc.numPages)
    // 修正当前页越界
    if (currentPage.value > doc.numPages) {
      currentPage.value = doc.numPages
      emit('page-change', currentPage.value)
    }
    // 关键：先关闭 loading 状态，让模板中的 v-else 块（包含 canvas）渲染出来
    // 否则 canvasRef.value 为 null，renderPage 会直接 return
    loading.value = false
    await nextTick()
    console.log('[PdfViewer] canvas ready, canvasRef =', !!canvasRef.value)
    await renderPage()
  } catch (err) {
    console.error('[PdfViewer] loadPdf error:', err)
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
  if (!doc || !canvas) {
    console.warn('[PdfViewer] renderPage skipped: doc =', !!doc, 'canvas =', !!canvas)
    return
  }
  const token = ++renderToken

  try {
    console.log('[PdfViewer] renderPage start, page =', currentPage.value)
    const page = await doc.getPage(currentPage.value)
    console.log('[PdfViewer] getPage done, page =', page.pageNumber)
    if (token !== renderToken) return // 已有更新的渲染请求

    const viewport = page.getViewport({ scale: currentScale.value })
    const baseViewport = page.getViewport({ scale: 1 })
    console.log('[PdfViewer] viewport =', viewport.width, 'x', viewport.height)
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      console.error('[PdfViewer] canvas 2d context not available')
      return
    }

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = `${Math.floor(viewport.width)}px`
    canvas.style.height = `${Math.floor(viewport.height)}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    console.log('[PdfViewer] start render, canvas =', canvas.width, 'x', canvas.height)
    const renderTask = page.render({ canvasContext: ctx, viewport })
    await renderTask.promise
    console.log('[PdfViewer] render done')
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
    console.error('[PdfViewer] renderPage error:', err)
    console.error('[PdfViewer] error stack:', err instanceof Error ? err.stack : 'no stack')
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

// 外部 src 变化时重新加载（例如组件复用但文档切换）
watch(
  () => props.src,
  (val, oldVal) => {
    if (val && val !== oldVal) {
      console.log('[PdfViewer] src changed, reloading', { old: oldVal, new: val })
      loadPdf()
    }
  },
)

onMounted(() => {
  console.log('[PdfViewer] mounted, src =', props.src)
  loadPdf()
})

defineExpose({ loadPdf, renderPage })
</script>

<template>
  <div class="flex h-full w-full flex-col">
    <!-- 工具栏 -->
    <div class="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
      <div class="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          class="h-7 w-7 p-0"
          :disabled="currentPage <= 1 || loading"
          aria-label="上一页"
          @click="prevPage"
        >
          <ChevronLeft class="size-3.5" :stroke-width="1.5" />
        </Button>
        <span class="min-w-[56px] text-center font-mono text-xs text-muted-foreground">
          {{ totalPages ? currentPage : '-' }} / {{ totalPages || '-' }}
        </span>
        <Button
          variant="outline"
          size="sm"
          class="h-7 w-7 p-0"
          :disabled="currentPage >= totalPages || loading"
          aria-label="下一页"
          @click="nextPage"
        >
          <ChevronRight class="size-3.5" :stroke-width="1.5" />
        </Button>
      </div>
      <div class="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          class="h-7 w-7 p-0"
          :disabled="loading"
          aria-label="缩小"
          @click="zoomOut"
        >
          <ZoomOut class="size-3.5" :stroke-width="1.5" />
        </Button>
        <span class="min-w-[56px] text-center font-mono text-xs text-muted-foreground">
          {{ Math.round(currentScale * 100) }}%
        </span>
        <Button
          variant="outline"
          size="sm"
          class="h-7 w-7 p-0"
          :disabled="loading"
          aria-label="放大"
          @click="zoomIn"
        >
          <ZoomIn class="size-3.5" :stroke-width="1.5" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="h-7 w-7 p-0"
          :disabled="loading"
          aria-label="重置缩放"
          @click="resetZoom"
        >
          <RotateCcw class="size-3.5" :stroke-width="1.5" />
        </Button>
      </div>
    </div>

    <!-- 画布区域 -->
    <div class="flex flex-1 items-start justify-center overflow-auto bg-muted/20 p-4">
      <!-- 错误态 -->
      <div v-if="errorMsg" class="flex w-full flex-col items-center justify-center gap-3 py-16 text-center">
        <div class="flex size-12 items-center justify-center rounded-full bg-danger/10 text-danger">
          <FileWarning class="size-6" :stroke-width="1.5" />
        </div>
        <p class="max-w-md text-sm text-muted-foreground">{{ errorMsg }}</p>
        <Button variant="outline" size="sm" @click="loadPdf">
          <RotateCcw class="size-3.5" :stroke-width="1.5" />
          重新加载
        </Button>
      </div>
      <!-- 加载态 -->
      <div v-else-if="loading" class="flex w-full flex-col items-center gap-3 py-16">
        <Skeleton class="h-[420px] w-[320px] rounded-sm" />
        <p class="text-xs text-muted-foreground">正在加载文档…</p>
      </div>
      <!-- 画布 -->
      <div v-else class="relative inline-block shadow-sm ring-1 ring-border">
        <canvas ref="canvasRef" class="block bg-white" />
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
