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

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()
const kbId = computed(() => route.params.kb_id as string)

const query = ref((route.query.q as string) || '')
const inputQuery = ref(query.value)
const results = ref<KbSearchResult[]>([])
const loading = ref(false)
const searched = ref(false)

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
  // 同步 URL（便于分享/刷新保持）
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
  // 防抖：输入停止 400ms 后自动搜索
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(doSearch, 400)
}

function handleEnter() {
  if (debounceTimer) clearTimeout(debounceTimer)
  query.value = inputQuery.value
  doSearch()
}

function openDocument(docId: string) {
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

// 初始 query 非空时自动搜索
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
  <div>
    <PageHeader title="全文搜索" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="router.push({ name: 'KbOverview', params: { kb_id: kbId } })">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回概览
        </Button>
      </template>
    </PageHeader>

    <!-- 搜索框 -->
    <Card class="mb-4">
      <CardContent class="p-4">
        <div class="flex items-center gap-2">
          <div class="relative flex-1">
            <SearchIcon class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
            <Input
              v-model="inputQuery"
              placeholder="搜索文档名或正文内容..."
              class="pl-9"
              @input="handleInput"
              @keyup.enter="handleEnter"
            />
          </div>
          <Button :disabled="loading || !inputQuery.trim()" @click="handleEnter">
            <Loader2 v-if="loading" class="size-4 animate-spin" :stroke-width="1.5" />
            搜索
          </Button>
        </div>
        <p class="mt-2 text-xs text-muted-foreground">
          支持文件名与正文检索，结果按相关度排序，命中词以高亮显示
        </p>
      </CardContent>
    </Card>

    <!-- 加载态 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 4" :key="i" class="h-24 w-full" />
    </div>

    <!-- 空态：未搜索 -->
    <EmptyState
      v-else-if="!searched"
      :icon="SearchIcon"
      title="输入关键词开始搜索"
      description="跨文档全文检索，快速定位目标内容"
      class="py-16"
    />

    <!-- 空态：无结果 -->
    <EmptyState
      v-else-if="results.length === 0"
      :icon="SearchX"
      title="未找到匹配结果"
      :description="`没有文档匹配「${query}」`"
      class="py-16"
    />

    <!-- 搜索结果 -->
    <div v-else class="space-y-2">
      <p class="px-1 text-sm text-muted-foreground">
        找到 <span class="font-medium text-foreground">{{ results.length }}</span> 条结果
      </p>
      <Card
        v-for="item in results"
        :key="item.id"
        class="cursor-pointer transition-colors hover:border-primary/40 hover:bg-muted/30"
        @click="openDocument(item.id)"
      >
        <CardContent class="p-4">
          <div class="flex items-start gap-3">
            <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <FileText class="size-4" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <!-- 文件名（高亮） -->
              <p class="font-medium text-foreground" v-html="item.filename_highlight"></p>
              <!-- 元信息 -->
              <div class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                <Badge v-if="item.file_type" variant="outline" class="text-[10px]">
                  {{ item.file_type }}
                </Badge>
                <span>{{ formatTime(item.created_at) }}</span>
                <span>· 相关度 {{ (item.rank * 100).toFixed(1) }}%</span>
              </div>
              <!-- 高亮片段 -->
              <div
                v-if="item.snippet"
                class="mt-2 line-clamp-3 rounded bg-muted/40 px-2 py-1.5 text-sm text-muted-foreground"
                v-html="item.snippet"
              ></div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<style scoped>
/* ts_headline 输出的 <mark> 标签高亮样式 */
:deep(mark) {
  background-color: hsl(var(--warning) / 0.25);
  color: hsl(var(--foreground));
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 600;
}

.line-clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
