<script setup lang="ts">
/**
 * 知识库全文搜索页
 *
 * 基于 PostgreSQL tsvector 全文检索，跨文档搜索 filename + parsed_text，
 * ts_headline 生成高亮片段（<mark> 标签）。
 * 数据隔离：后端 RLS 强制按 kb_id 过滤。
 * 权限：viewer+ 可搜索
 */
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Search as SearchIcon,
  FileText,
  Loader2,
  SearchX,
  ArrowLeft,
  ExternalLink,
} from 'lucide-vue-next'
import { kbApi, type KbSearchResult } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()
const kbId = computed(() => route.params.kb_id as string)

const query = ref((route.query.q as string) || '')
const inputQuery = ref(query.value)
const results = ref<KbSearchResult[]>([])
const loading = ref(false)
const searched = ref(false)
const previewOpen = ref(false)
const selectedResult = ref<KbSearchResult | null>(null)
const inputFocused = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

async function doSearch() {
  const q = query.value.trim()
  if (!q) {
    results.value = []
    searched.value = false
    return
  }
  loading.value = true
  searched.value = true
  router.replace({ query: { q } })
  try {
    const res = await kbApi.searchDocuments(kbId.value, q, 30)
    results.value = res.items
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

function handleInput() {
  query.value = inputQuery.value
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(doSearch, 400)
}

function handleEnter() {
  if (debounceTimer) clearTimeout(debounceTimer)
  query.value = inputQuery.value
  doSearch()
}

function openPreview(item: KbSearchResult) {
  selectedResult.value = item
  previewOpen.value = true
}

function viewOriginal() {
  if (selectedResult.value) {
    previewOpen.value = false
    router.push({
      name: 'KbDocumentViewer',
      params: { kb_id: kbId.value, doc_id: selectedResult.value.id },
    })
  }
}

function viewInDocuments() {
  previewOpen.value = false
  router.push({ name: 'KbDocuments', params: { kb_id: kbId.value } })
}

function formatTime(value: string): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

function getRankColor(rank: number): string {
  const percentage = rank * 100
  if (percentage >= 80) return 'from-emerald-500 to-teal-500'
  if (percentage >= 60) return 'from-teal-500 to-cyan-500'
  if (percentage >= 40) return 'from-cyan-500 to-sky-500'
  return 'from-sky-500 to-blue-500'
}

const previewSnippet = computed(() => {
  if (!selectedResult.value?.snippet) {
    return '<p class="text-muted-foreground">暂无匹配片段</p>'
  }
  return selectedResult.value.snippet
})

watch(
  () => route.query.q,
  (q) => {
    if (q && typeof q === 'string' && q !== query.value) {
      query.value = q
      inputQuery.value = q
      doSearch()
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="search-page">
    <PageHeader title="全文搜索" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="router.push({ name: 'KbOverview', params: { kb_id: kbId } })">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回概览
        </Button>
      </template>
    </PageHeader>

    <!-- 搜索框 - Premium Dark-Tech 风格 -->
    <Card class="search-card mb-6 overflow-visible">
      <CardContent class="p-5">
        <div class="search-container relative flex items-center gap-3">
          <div
            class="search-input-wrapper relative flex-1 rounded-xl transition-all duration-300"
            :class="{ 'focused': inputFocused }"
          >
            <div class="search-glow absolute -inset-0.5 rounded-xl opacity-0 transition-opacity duration-300" :class="{ 'opacity-100': inputFocused }"></div>
            <div class="search-input-inner relative flex items-center rounded-xl bg-card">
              <SearchIcon class="search-icon absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground transition-all duration-300" :stroke-width="1.5" :class="{ 'text-primary scale-110': inputFocused }" />
              <Input
                v-model="inputQuery"
                placeholder="搜索文档名或正文内容..."
                class="search-input h-12 border-0 bg-transparent pl-12 pr-4 text-base shadow-none ring-0 focus-visible:ring-0 focus-visible:ring-offset-0"
                @input="handleInput"
                @keyup.enter="handleEnter"
                @focus="inputFocused = true"
                @blur="inputFocused = false"
              />
            </div>
          </div>
          <Button
            :class="cn(
              'search-button h-12 px-6 font-medium transition-all duration-300',
              (inputQuery.trim() && !loading) ? 'search-button-active' : ''
            )"
            :disabled="loading || !inputQuery.trim()"
            @click="handleEnter"
          >
            <Loader2 v-if="loading" class="size-5 animate-spin" :stroke-width="1.5" />
            <template v-else>
              <SearchIcon class="size-5" :stroke-width="1.5" />
              <span>搜索</span>
            </template>
          </Button>
        </div>
        <div class="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <div class="h-1 w-1 rounded-full bg-primary/50"></div>
          <span>支持文件名与正文检索，结果按相关度排序，命中词以高亮显示</span>
        </div>
      </CardContent>
    </Card>

    <!-- 加载态 -->
    <div v-if="loading" class="space-y-3">
      <Skeleton v-for="i in 4" :key="i" class="result-skeleton h-28 w-full rounded-xl" />
    </div>

    <!-- 空态：未搜索 -->
    <EmptyState
      v-else-if="!searched"
      :icon="SearchIcon"
      title="输入关键词开始搜索"
      description="跨文档全文检索，快速定位目标内容"
      class="py-20"
    />

    <!-- 空态：无结果 -->
    <EmptyState
      v-else-if="results.length === 0"
      :icon="SearchX"
      title="未找到匹配结果"
      :description="`没有文档匹配「${query}」`"
      class="py-20"
    />

    <!-- 搜索结果 -->
    <div v-else class="space-y-4">
      <div class="results-header flex items-center justify-between px-1">
        <p class="text-sm text-muted-foreground">
          找到 <span class="results-count font-semibold text-foreground">{{ results.length }}</span> 条结果
        </p>
      </div>
      <Card
        v-for="(item, index) in results"
        :key="item.id"
        class="result-card group cursor-pointer overflow-hidden border border-border/60 bg-card/50 backdrop-blur-sm transition-all duration-300 hover-lift"
        :style="{ animationDelay: `${index * 50}ms` }"
        @click="openPreview(item)"
      >
        <CardContent class="p-5">
          <div class="flex items-start gap-4">
            <!-- 文件图标 -->
            <div class="file-icon-wrapper relative flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 transition-all duration-300 group-hover:bg-primary/15 group-hover:scale-105">
              <div class="file-icon-glow absolute inset-0 rounded-xl bg-primary/20 opacity-0 blur-lg transition-opacity duration-300 group-hover:opacity-100"></div>
              <FileText class="file-icon relative size-5 text-primary" :stroke-width="1.5" />
            </div>

            <div class="min-w-0 flex-1">
              <div class="flex items-start justify-between gap-3">
                <!-- 文件名（高亮） -->
                <p class="result-filename truncate text-base font-semibold text-foreground transition-colors duration-200 group-hover:text-primary/90" v-html="item.filename_highlight"></p>

                <!-- 相关度评分 -->
                <div class="rank-display flex shrink-0 flex-col items-end gap-1">
                  <span
                    class="rank-badge inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-xs font-semibold transition-all duration-300"
                    :class="{
                      'rank-badge-excellent': item.rank >= 0.7,
                      'rank-badge-good': item.rank >= 0.4 && item.rank < 0.7,
                      'rank-badge-normal': item.rank < 0.4,
                    }"
                  >
                    {{ (item.rank * 100).toFixed(1) }}%
                  </span>
                </div>
              </div>

              <!-- 相关度进度条 -->
              <div class="rank-bar-container mt-2 h-1 w-24 overflow-hidden rounded-full bg-muted">
                <div
                  class="rank-bar h-full rounded-full bg-gradient-to-r transition-all duration-500"
                  :class="getRankColor(item.rank)"
                  :style="{ width: `${Math.min(item.rank * 100, 100)}%` }"
                ></div>
              </div>

              <!-- 元信息 -->
              <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge v-if="item.file_type" variant="secondary" class="file-type-badge rounded-md bg-primary/8 px-2 py-0.5 text-[10px] font-medium text-primary/90 transition-colors duration-200 group-hover:bg-primary/12">
                  {{ item.file_type.toUpperCase() }}
                </Badge>
                <span class="flex items-center gap-1">
                  <span class="time-dot h-1 w-1 rounded-full bg-muted-foreground/40"></span>
                  {{ formatTime(item.created_at) }}
                </span>
              </div>

              <!-- 高亮片段 -->
              <div
                v-if="item.snippet"
                class="snippet-box mt-3 rounded-lg border border-border/40 bg-muted/20 px-3 py-2.5 text-sm leading-relaxed text-muted-foreground transition-all duration-200 group-hover:border-primary/20 group-hover:bg-primary/[0.03]"
                v-html="item.snippet"
              ></div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 搜索结果预览弹框 -->
    <Dialog
      v-model:open="previewOpen"
      :title="selectedResult?.filename || '搜索结果'"
      class="max-w-2xl"
    >
      <div v-if="selectedResult" class="space-y-5">
        <!-- 文档信息 -->
        <div class="preview-doc-info flex items-center gap-4 rounded-xl border border-border/60 bg-muted/20 p-4">
          <div class="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
            <FileText class="size-6 text-primary" :stroke-width="1.5" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-foreground">{{ selectedResult.filename }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge v-if="selectedResult.file_type" variant="secondary" class="rounded-md bg-primary/8 px-2 py-0.5 text-[10px] font-medium text-primary/90">
                {{ selectedResult.file_type.toUpperCase() }}
              </Badge>
              <span>{{ formatTime(selectedResult.created_at) }}</span>
            </div>
          </div>
        </div>

        <!-- 相关度评分 -->
        <div class="preview-rank-section rounded-xl border border-border/60 bg-card p-4">
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-foreground">相关度评分</span>
            <div class="flex items-center gap-3">
              <div class="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-gradient-to-r"
                  :class="getRankColor(selectedResult.rank)"
                  :style="{ width: `${Math.min(selectedResult.rank * 100, 100)}%` }"
                ></div>
              </div>
              <Badge variant="default" class="font-mono text-sm font-bold">
                {{ (selectedResult.rank * 100).toFixed(1) }}%
              </Badge>
            </div>
          </div>
        </div>

        <!-- 匹配文本内容 -->
        <div>
          <p class="mb-2 text-sm font-semibold text-foreground">匹配内容</p>
          <div
            class="preview-snippet max-h-[40vh] overflow-auto rounded-xl border border-border/60 bg-muted/10 p-4 text-sm leading-relaxed search-snippet-content"
            v-html="previewSnippet"
          ></div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex items-center justify-end gap-3 pt-2">
          <Button variant="outline" class="h-10 px-5" @click="viewInDocuments">
            返回文档列表
          </Button>
          <Button class="preview-view-btn h-10 px-5 shadow-primary transition-all duration-300 hover:shadow-primary-lg" @click="viewOriginal">
            <ExternalLink class="size-4" :stroke-width="1.5" />
            查看原文
          </Button>
        </div>
      </div>
    </Dialog>
  </div>
</template>

<style scoped>
/* 搜索页面主背景 */
.search-page {
  position: relative;
}

/* ============================================================
 * 搜索框样式 - Premium Dark-Tech
 * ============================================================ */
.search-card {
  position: relative;
  background: linear-gradient(135deg, var(--card) 0%, var(--card) 100%);
  border-color: var(--border);
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.3s var(--ease-out);
}

.search-input-wrapper {
  position: relative;
}

.search-input-wrapper.focused {
  transform: translateY(-1px);
}

/* 主色光晕效果 */
.search-glow {
  background: linear-gradient(135deg, var(--primary-400), var(--primary-600), var(--primary-400));
  filter: blur(12px);
  z-index: 0;
}

.search-input-inner {
  position: relative;
  z-index: 1;
  border: 1.5px solid var(--border);
  transition: all 0.3s var(--ease-out);
}

.search-input-wrapper.focused .search-input-inner {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px oklch(0.58 0.12 200 / 0.1);
}

.search-input::placeholder {
  color: var(--muted-foreground);
  opacity: 0.7;
}

/* 搜索按钮主色光晕 */
.search-button {
  position: relative;
  overflow: hidden;
  background: var(--primary);
  color: var(--primary-foreground);
  box-shadow: none;
  gap: 8px;
}

.search-button::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--primary-400), var(--primary-500));
  opacity: 0;
  transition: opacity 0.3s var(--ease-out);
}

.search-button-active {
  box-shadow: var(--shadow-primary);
}

.search-button-active::before {
  opacity: 1;
}

.search-button-active:hover {
  box-shadow: var(--shadow-primary-lg);
  transform: translateY(-1px);
}

.search-button > * {
  position: relative;
  z-index: 1;
}

/* ============================================================
 * 搜索结果卡片样式
 * ============================================================ */
.result-card {
  position: relative;
  animation: fadeInUp 0.4s var(--ease-out) backwards;
}

.result-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--primary-500) 0%, transparent 50%);
  opacity: 0;
  transition: opacity 0.3s var(--ease-out);
  pointer-events: none;
  border-radius: inherit;
}

.result-card:hover::before {
  opacity: 0.03;
}

.result-card:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-md);
}

.result-filename {
  position: relative;
}

/* 相关度评分徽章 */
.rank-badge-excellent {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: var(--primary-foreground);
  box-shadow: 0 2px 8px oklch(0.58 0.12 200 / 0.3);
}

.rank-badge-good {
  background: var(--secondary);
  color: var(--secondary-foreground);
  border: 1px solid var(--border);
}

.rank-badge-normal {
  background: transparent;
  color: var(--muted-foreground);
  border: 1px solid var(--border);
}

/* 文件类型标签 */
.file-type-badge {
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
}

/* 高亮片段容器 */
.snippet-box {
  position: relative;
  overflow: hidden;
}

.snippet-box::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--primary-400), var(--primary-600));
  opacity: 0;
  transition: opacity 0.3s var(--ease-out);
  border-radius: 0 2px 2px 0;
}

.result-card:hover .snippet-box::before {
  opacity: 1;
}

/* 文件图标光晕 */
.file-icon-glow {
  z-index: 0;
}

.file-icon {
  z-index: 1;
}

/* ============================================================
 * 高亮文本样式 - 更精致的渐变高亮
 * ============================================================ */
:deep(mark) {
  background: linear-gradient(135deg, var(--warning) 0%, oklch(0.75 0.14 85) 100%);
  background-color: transparent;
  color: var(--warning-foreground);
  padding: 1px 4px;
  border-radius: 4px;
  font-weight: 600;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

/* ============================================================
 * 预览弹框优化
 * ============================================================ */
.preview-doc-info {
  background: linear-gradient(135deg, var(--muted) 0%, var(--card) 100%);
}

.preview-rank-section {
  background: linear-gradient(135deg, var(--card) 0%, var(--muted)/30 100%);
}

.preview-snippet {
  background: linear-gradient(180deg, var(--muted)/20 0%, var(--muted)/10 100%);
}

.preview-view-btn {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
}

/* ============================================================
 * 骨架屏优化
 * ============================================================ */
.result-skeleton {
  background: linear-gradient(90deg, var(--muted) 25%, var(--muted)/70 50%, var(--muted) 75%);
  background-size: 200% 100%;
  animation: skeletonShimmer 1.5s ease-in-out infinite;
}

/* ============================================================
 * 动画
 * ============================================================ */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes skeletonShimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* 结果计数数字 */
.results-count {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-400));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

/* 行截断 */
.line-clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>

<style>
/* Dialog Portal 渲染到 body，需要非 scoped 样式确保弹框内高亮生效 */
.search-snippet-content mark {
  background: linear-gradient(135deg, var(--warning) 0%, oklch(0.75 0.14 85) 100%);
  background-color: transparent;
  color: var(--warning-foreground);
  padding: 1px 4px;
  border-radius: 4px;
  font-weight: 600;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
</style>
