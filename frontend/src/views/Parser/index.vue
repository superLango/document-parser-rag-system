<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { documentApi } from '@/api/modules/document'
import { taskApi } from '@/api/modules/task'
import { useTaskProgress } from '@/composables/useTaskProgress'
import PdfViewer from '@/components/PdfViewer.vue'
import type { Document, LayoutRegion } from '@/api/types'

const route = useRoute()
const router = useRouter()
const docId = String(route.params.id)
const taskIdFromUrl = route.query.task_id ? String(route.query.task_id) : ''

const loading = ref(true)
const document = ref<Document | null>(null)
const activeTab = ref('extraction')

// ---------- 任务进度 ----------
const { progress, status: taskStatus, message: taskMessage, startProgress } =
  useTaskProgress()

// ---------- PDF 预览状态 ----------
const currentPage = ref(1)
const totalPages = ref(0)

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
const statusTagType = computed(() => {
  const s = document.value?.status
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'parsing') return 'warning'
  return 'info'
})

const statusLabel = computed(() => {
  const s = document.value?.status
  const map: Record<string, string> = {
    pending: '待解析',
    parsing: '解析中',
    completed: '已完成',
    failed: '解析失败',
  }
  return map[s || ''] || s || '—'
})

const showStartButton = computed(() => {
  if (!document.value) return false
  if (taskStatus.value === 'running' || taskStatus.value === 'queued') return false
  return (
    document.value.status === 'pending' || document.value.status === 'failed'
  )
})

const showProgress = computed(() => taskStatus.value !== 'idle')

const progressStatus = computed<'success' | 'exception' | undefined>(() => {
  if (taskStatus.value === 'completed') return 'success'
  if (taskStatus.value === 'failed') return 'exception'
  return undefined
})

// ---------- BoundingBox ----------
// 区域类型颜色映射
const REGION_COLORS: Record<string, string> = {
  text: '#409EFF',
  table: '#67C23A',
  figure: '#E6A23C',
  title: '#F56C6C',
  header: '#909399',
  footer: '#909399',
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

/**
 * 将 PDF 原始坐标的 bbox 转换为 canvas 像素坐标的矩形
 */
function bboxRects(
  naturalWidth: number,
  naturalHeight: number,
  canvasWidth: number,
  canvasHeight: number,
  pageNumber: number,
) {
  if (!naturalWidth || !naturalHeight) return []
  const ratioX = canvasWidth / naturalWidth
  const ratioY = canvasHeight / naturalHeight
  return regions.value
    .filter((r) => {
      // 若区域携带 page 字段则按页过滤，否则视为当前页
      if (r.page !== undefined && r.page !== null) return r.page === pageNumber
      return true
    })
    .map((r) => {
      const [x1, y1, x2, y2] = r.bbox
      return {
        key: `${r.type}-${x1}-${y1}-${x2}-${y2}`,
        type: r.type,
        label: REGION_LABELS[r.type] || r.type,
        confidence: r.confidence,
        x: x1 * ratioX,
        y: y1 * ratioY,
        w: (x2 - x1) * ratioX,
        h: (y2 - y1) * ratioY,
        color: REGION_COLORS[r.type] || '#909399',
      }
    })
}

// ---------- 原始文本 ----------
const parsedText = computed(() => document.value?.parsed_text || '')

async function copyText() {
  if (!parsedText.value) return
  try {
    await navigator.clipboard.writeText(parsedText.value)
    ElMessage.success('已复制全文')
  } catch {
    ElMessage.error('复制失败')
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

  // 元数据字段
  const meta: Record<string, unknown> = {
    standard_number: doc.standard_number,
    title: doc.title,
    doc_type: doc.doc_type,
  }
  for (const [k, v] of Object.entries(meta)) {
    if (v !== undefined && v !== null && v !== '') {
      rows.push({ name: k, value: String(v), type: 'string' })
    }
  }

  // 结构化抽取字段（完整展示，不限于元数据三项）
  const sd = doc.structured_data
  if (sd && typeof sd === 'object') {
    for (const [k, v] of Object.entries(sd)) {
      rows.push({
        name: k,
        value: formatValue(v) || '—',
        type: inferType(v),
      })
    }
  }

  // 兜底：structured_data 为空时尝试 metadata 中的抽取字段
  if (rows.length <= 3 && doc.metadata && typeof doc.metadata === 'object') {
    for (const [k, v] of Object.entries(doc.metadata)) {
      rows.push({
        name: k,
        value: formatValue(v) || '—',
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

// ---------- 生命周期 ----------
onMounted(async () => {
  await fetchDocument()
  if (taskIdFromUrl) {
    startProgress(taskIdFromUrl)
  }
})
</script>

<template>
  <div class="parser">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">
          {{ document?.title || document?.file_name || '解析查看' }}
        </h2>
        <p class="page-desc">
          <span class="mono" v-if="document">DOC-{{ document.id.slice(0, 8) }}</span>
          <span v-else>加载中…</span>
          <el-tag
            v-if="document"
            :type="statusTagType"
            size="small"
            class="status-tag"
          >
            {{ statusLabel }}
          </el-tag>
        </p>
      </div>
      <div class="header-right">
        <el-button
          v-if="showStartButton"
          type="primary"
          :loading="taskStatus === 'queued'"
          @click="submitParse"
        >
          开始解析
        </el-button>
      </div>
    </div>

    <!-- 进度条 -->
    <div v-if="showProgress" class="progress-bar">
      <el-progress
        :percentage="progress"
        :status="progressStatus"
        :stroke-width="8"
      />
      <span class="progress-message mono">{{ taskMessage }}</span>
    </div>

    <!-- 双栏布局 -->
    <div class="parser-grid">
      <!-- 左栏：PDF 预览 + BoundingBox -->
      <div class="bp-card viewer-pane">
        <div class="pane-header">
          <span class="pane-title">文档预览</span>
          <span class="mono pane-meta" v-if="totalPages">{{ totalPages }} 页</span>
        </div>
        <div class="pane-body viewer-body" v-loading="loading">
          <el-empty
            v-if="!loading && !document"
            description="无法加载文档"
            :image-size="60"
          />
          <PdfViewer
            v-else-if="pdfUrl"
            :src="pdfUrl"
            :page="currentPage"
            :scale="1.2"
            @page-change="onPageChange"
            @total-pages-change="totalPages = $event"
          >
            <template #default="{ width, height, naturalWidth, naturalHeight, pageNumber }">
              <svg
                v-if="regions.length && width > 0"
                class="bbox-overlay"
                :width="width"
                :height="height"
                :viewBox="`0 0 ${width} ${height}`"
              >
                <g
                  v-for="rect in bboxRects(naturalWidth, naturalHeight, width, height, pageNumber)"
                  :key="rect.key"
                >
                  <rect
                    :x="rect.x"
                    :y="rect.y"
                    :width="rect.w"
                    :height="rect.h"
                    fill="transparent"
                    :stroke="rect.color"
                    stroke-width="1.5"
                    style="pointer-events: all"
                  >
                    <title>
                      {{ rect.label }} · 置信度 {{ rect.confidence ?? '—' }}
                    </title>
                  </rect>
                </g>
              </svg>
            </template>
          </PdfViewer>
        </div>
      </div>

      <!-- 右栏：解析结果 -->
      <div class="bp-card result-pane">
        <div class="pane-header">
          <el-tabs v-model="activeTab" class="result-tabs">
            <el-tab-pane label="抽取数据" name="extraction" />
            <el-tab-pane label="原始文本" name="text" />
            <el-tab-pane label="结构化" name="structured" />
          </el-tabs>
        </div>
        <div class="pane-body result-body" v-loading="loading">
          <!-- 抽取数据 Tab -->
          <template v-if="activeTab === 'extraction'">
            <el-empty
              v-if="extractionRows.length === 0"
              description="文档尚未解析"
              :image-size="60"
            />
            <el-table v-else :data="extractionRows" border stripe size="small">
              <el-table-column prop="name" label="字段名" min-width="140" />
              <el-table-column prop="value" label="字段值" min-width="200" show-overflow-tooltip />
              <el-table-column prop="type" label="类型" width="100" />
            </el-table>
          </template>

          <!-- 原始文本 Tab -->
          <template v-else-if="activeTab === 'text'">
            <div v-if="parsedText" class="text-tab">
              <div class="tab-toolbar">
                <el-button size="small" @click="copyText">复制全文</el-button>
              </div>
              <pre class="parsed-text">{{ parsedText }}</pre>
            </div>
            <el-empty v-else description="文档尚未解析" :image-size="60" />
          </template>

          <!-- 结构化 Tab -->
          <template v-else>
            <el-empty
              v-if="structuredEntries.length === 0"
              description="文档尚未解析"
              :image-size="60"
            />
            <el-descriptions v-else :column="1" border size="small">
              <el-descriptions-item
                v-for="[key, val] in structuredEntries"
                :key="key"
                :label="key"
              >
                {{ formatValue(val) || '—' }}
              </el-descriptions-item>
            </el-descriptions>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;

  .page-title {
    font-size: var(--fs-xl);
    font-weight: 600;
    margin-bottom: 4px;
  }

  .page-desc {
    font-size: var(--fs-sm);
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .status-tag {
    margin-left: 4px;
  }
}

.progress-bar {
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);

  .progress-message {
    display: block;
    margin-top: 6px;
    font-size: var(--fs-xs);
    color: var(--text-secondary);
  }
}

.parser-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  height: calc(100vh - 240px);
  min-height: 400px;
}

.viewer-pane,
.result-pane {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-base);
  flex-shrink: 0;

  .pane-title {
    font-weight: 600;
    color: var(--text-primary);
  }

  .pane-meta {
    font-size: var(--fs-xs);
    color: var(--text-muted);
  }
}

.pane-body {
  padding: 0;
  overflow: auto;
  flex: 1;
}

.viewer-body {
  background-color: var(--bg-base);
}

// BoundingBox 叠加层
.bbox-overlay {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 2;

  rect {
    pointer-events: all;
    cursor: help;
  }
}

// 结果面板
.result-tabs {
  flex: 1;

  :deep(.el-tabs__header) {
    margin: 0;
  }
  :deep(.el-tabs__nav-wrap)::after {
    background-color: var(--border-base);
  }
}

.result-body {
  padding: 16px 20px;
}

.text-tab {
  display: flex;
  flex-direction: column;
  height: 100%;

  .tab-toolbar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 12px;
  }
}

.parsed-text {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: var(--fs-sm);
  color: var(--text-primary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  padding: 12px;
  background: var(--bg-base);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  overflow: auto;
}
</style>
