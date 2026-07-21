<script setup lang="ts">
/**
 * BoundingBoxOverlay
 *
 * 在 PdfViewer canvas 之上叠加 SVG 高亮层，根据 OCR layout_data 中的 bbox
 * 坐标绘制半透明矩形，支持点击高亮与外部激活。
 *
 * 坐标系约定：
 * - 后端 bbox 格式为 [x1, y1, x2, y2]，像素坐标，基于 OCR 渲染 DPI（默认 200）
 * - PdfViewer 通过插槽暴露 naturalWidth / naturalHeight（scale=1 时的 PDF 原始尺寸）
 * - 本组件负责将 bbox 坐标按 naturalWidth / naturalHeight 缩放至当前 canvas 显示尺寸
 *
 * 使用方式：
 *   <PdfViewer :src="url" v-slot="{ width, height, naturalWidth, naturalHeight, pageNumber }">
 *     <BoundingBoxOverlay
 *       :width="width"
 *       :height="height"
 *       :natural-width="naturalWidth"
 *       :natural-height="naturalHeight"
 *       :page-number="pageNumber"
 *       :layout="layoutData?.merged || []"
 *       :active-index="activeIdx"
 *       @select="onSelectBox"
 *     />
 *   </PdfViewer>
 */

interface LayoutItem {
  type?: string
  bbox?: number[]  // [x1, y1, x2, y2]
  text?: string
  page?: number
  confidence?: number | null
  [key: string]: unknown
}

const props = defineProps<{
  /** canvas CSS 宽度（px） */
  width: number
  /** canvas CSS 高度（px） */
  height: number
  /** PDF scale=1 时的原始宽度 */
  naturalWidth: number
  /** PDF scale=1 时的原始高度 */
  naturalHeight: number
  /** 当前页码（1-based） */
  pageNumber: number
  /** layout_data.merged 列表 */
  layout: LayoutItem[]
  /** 当前激活的 box 索引（null 表示无激活） */
  activeIndex?: number | null
}>()

const emit = defineEmits<{
  (e: 'select', index: number, item: LayoutItem): void
}>()

// 仅显示当前页的 layout 项
const pageItems = computed(() => {
  const items = props.layout || []
  return items
    .map((item, idx) => ({ item, idx }))
    .filter(({ item }) => {
      // page 字段缺省视为第 1 页
      const page = item.page ?? 1
      return page === props.pageNumber
    })
})

// 计算缩放比：bbox 坐标 → canvas 显示坐标
// 关键假设：后端 bbox 基于渲染后的图像尺寸（DPI=200），
// 而 naturalWidth/Height 是 PDF scale=1 时的尺寸（DPI=72）。
// 通过 naturalWidth <-> 实际渲染图像宽度的比例换算。
// 但由于 PDF.js 的 naturalWidth 与 PyMuPDF 渲染的图像尺寸并非 1:1 对应，
// 我们采用「bbox 坐标归一化为百分比」的稳健方案。
interface BoxRect {
  idx: number
  item: LayoutItem
  // 百分比坐标（0-100）
  leftPct: number
  topPct: number
  widthPct: number
  heightPct: number
}

const boxes = computed<BoxRect[]>(() => {
  if (!props.naturalWidth || !props.naturalHeight) return []
  // 假设后端 bbox 坐标基于 PDF 原始尺寸（与 naturalWidth/Height 同坐标系）
  // 如果实际是渲染图像尺寸，需要调整这里的换算基准
  const refWidth = props.naturalWidth
  const refHeight = props.naturalHeight

  return pageItems.value.map(({ item, idx }) => {
    const bbox = item.bbox || [0, 0, 0, 0]
    const [x1, y1, x2, y2] = bbox
    // 安全防呆：避免负值或倒置
    const left = Math.max(0, Math.min(x1, x2))
    const right = Math.min(refWidth, Math.max(x1, x2))
    const top = Math.max(0, Math.min(y1, y2))
    const bottom = Math.min(refHeight, Math.max(y1, y2))

    return {
      idx,
      item,
      leftPct: (left / refWidth) * 100,
      topPct: (top / refHeight) * 100,
      widthPct: ((right - left) / refWidth) * 100,
      heightPct: ((bottom - top) / refHeight) * 100,
    }
  })
})

// 按 type 分配颜色
function colorForType(type?: string): string {
  switch (type) {
    case 'title':
    case 'heading':
      return 'rgba(20, 184, 166, 0.28)'  // Steel Teal
    case 'table':
      return 'rgba(249, 115, 22, 0.28)'  // Orange
    case 'figure':
    case 'image':
      return 'rgba(139, 92, 246, 0.28)'  // Purple
    default:
      return 'rgba(59, 130, 246, 0.22)'  // Blue
  }
}

function strokeForType(type?: string): string {
  switch (type) {
    case 'title':
    case 'heading':
      return 'rgb(20, 184, 166)'
    case 'table':
      return 'rgb(249, 115, 22)'
    case 'figure':
    case 'image':
      return 'rgb(139, 92, 246)'
    default:
      return 'rgb(59, 130, 246)'
  }
}

function handleClick(idx: number, item: LayoutItem) {
  emit('select', idx, item)
}
</script>

<script lang="ts">
import { computed } from 'vue'
export default { name: 'BoundingBoxOverlay' }
</script>

<template>
  <svg
    v-if="width > 0 && height > 0"
    :width="width"
    :height="height"
    class="pointer-events-auto absolute left-0 top-0"
    style="overflow: visible"
    aria-label="OCR 区域高亮层"
  >
    <g v-for="box in boxes" :key="box.idx">
      <rect
        :x="`${box.leftPct}%`"
        :y="`${box.topPct}%`"
        :width="`${box.widthPct}%`"
        :height="`${box.heightPct}%`"
        :fill="colorForType(box.item.type)"
        :stroke="strokeForType(box.item.type)"
        :stroke-width="activeIndex === box.idx ? 2 : 1"
        :stroke-dasharray="activeIndex === box.idx ? 'none' : '4 2'"
        :class="[
          'cursor-pointer transition-all',
          activeIndex === box.idx ? 'opacity-100' : 'opacity-70 hover:opacity-100',
        ]"
        @click="handleClick(box.idx, box.item)"
      />
    </g>
  </svg>
</template>
