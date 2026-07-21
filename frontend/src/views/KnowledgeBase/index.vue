<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Database,
  Files,
  Layers,
  FileCheck2,
  RefreshCw,
  Trash2,
  Loader2,
  Search,
  Sparkles,
  AlertTriangle,
  X,
  Send,
} from 'lucide-vue-next'
import { knowledgeBaseApi } from '@/api/modules/knowledgeBase'
import { documentApi } from '@/api/modules/document'
import type { KBStats, Document as DocType, KBSearchResult } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Dialog } from '@/components/ui/dialog'
import { Tooltip } from '@/components/ui/tooltip'
import { StatusBadge } from '@/components/ui/status-badge'

// ---------- 统计 ----------
const statsLoading = ref(true)
const stats = ref<KBStats>({
  total_chunks: 0,
  total_docs: 0,
  indexed_docs: 0,
  completed_docs: 0,
})

const statCards = [
  { key: 'total_chunks' as const, label: '分块总数', icon: Files, color: 'primary' },
  { key: 'total_docs' as const, label: '文档总数', icon: Database, color: 'success' },
  { key: 'indexed_docs' as const, label: '已索引文档', icon: Layers, color: 'warning' },
  { key: 'completed_docs' as const, label: '索引完成文档', icon: FileCheck2, color: 'primary' },
]

const colorClasses: Record<string, string> = {
  primary: 'bg-primary/10 text-primary',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
}

async function fetchStats() {
  statsLoading.value = true
  try {
    stats.value = await knowledgeBaseApi.stats()
  } catch {
    // 错误已处理
  } finally {
    statsLoading.value = false
  }
}

// ---------- 文档列表 ----------
const listLoading = ref(true)
const documents = ref<DocType[]>([])

async function fetchDocuments() {
  listLoading.value = true
  try {
    const res = await documentApi.getList({ status: 'completed', page_size: 100 })
    documents.value = res.items
  } catch {
    documents.value = []
  } finally {
    listLoading.value = false
  }
}

// ---------- 索引操作 ----------
const indexingIds = ref<Set<string>>(new Set())

async function handleIndex(doc: DocType) {
  if (indexingIds.value.has(doc.id)) return
  indexingIds.value.add(doc.id)
  try {
    const res = await knowledgeBaseApi.indexDocument(doc.id)
    toast.success('已提交', `索引任务已提交（task_id: ${res.task_id}）`)
    setTimeout(() => {
      fetchStats()
      fetchDocuments()
    }, 2000)
  } catch {
    // 错误已处理
  } finally {
    indexingIds.value.delete(doc.id)
  }
}

// ---------- 移除索引 ----------
const removingIds = ref<Set<string>>(new Set())
const removeDialogVisible = ref(false)
const removeTarget = ref<DocType | null>(null)

function openRemoveDialog(doc: DocType) {
  removeTarget.value = doc
  removeDialogVisible.value = true
}

async function confirmRemove() {
  if (!removeTarget.value) return
  removingIds.value.add(removeTarget.value.id)
  try {
    const res = await knowledgeBaseApi.removeDocument(removeTarget.value.id)
    toast.success('已提交', `移除任务已提交（task_id: ${res.task_id}）`)
    removeDialogVisible.value = false
    setTimeout(() => {
      fetchStats()
      fetchDocuments()
    }, 2000)
  } catch {
    // 错误已处理
  } finally {
    if (removeTarget.value) removingIds.value.delete(removeTarget.value.id)
  }
}

// ---------- 重建索引 ----------
const rebuildDialogVisible = ref(false)
const rebuilding = ref(false)

async function confirmRebuild() {
  rebuilding.value = true
  try {
    const res = await knowledgeBaseApi.rebuild()
    toast.success('已提交', `重建索引任务已提交（task_id: ${res.task_id}）`)
    rebuildDialogVisible.value = false
    setTimeout(() => {
      fetchStats()
      fetchDocuments()
    }, 2000)
  } catch {
    // 错误已处理
  } finally {
    rebuilding.value = false
  }
}

// ---------- 检索测试 ----------
const searchQuery = ref('')
const searchTopK = ref(5)
const searching = ref(false)
const searchResults = ref<KBSearchResult[]>([])
const searchTotal = ref(0)
const hasSearched = ref(false)

async function handleSearch() {
  if (!searchQuery.value.trim()) {
    toast.warning('请输入查询', '检索测试需要输入查询内容')
    return
  }
  searching.value = true
  hasSearched.value = true
  try {
    const res = await knowledgeBaseApi.search(searchQuery.value.trim(), searchTopK.value)
    searchResults.value = res.results || []
    searchTotal.value = res.total || 0
  } catch {
    searchResults.value = []
    searchTotal.value = 0
  } finally {
    searching.value = false
  }
}

function formatScore(score: number): string {
  return score.toFixed(4)
}

function formatTime(value: string | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

onMounted(() => {
  fetchStats()
  fetchDocuments()
})
</script>

<template>
  <div>
    <PageHeader title="知识库管理" description="管理文档向量索引，支持入索引、移除与重建">
      <template #actions>
        <Button variant="outline" @click="fetchStats">
          <RefreshCw class="size-4" :class="{ 'animate-spin': statsLoading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button variant="outline" @click="rebuildDialogVisible = true">
          <Loader2 class="size-4" :stroke-width="1.5" />
          重建索引
        </Button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div class="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Card v-for="card in statCards" :key="card.key">
        <CardContent class="flex items-center gap-3 p-4">
          <div
            class="flex size-10 shrink-0 items-center justify-center rounded-md"
            :class="colorClasses[card.color]"
          >
            <component :is="card.icon" class="size-5" :stroke-width="1.5" />
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-xs text-muted-foreground">{{ card.label }}</p>
            <Skeleton v-if="statsLoading" class="mt-1 h-6 w-16" />
            <p v-else class="font-mono text-2xl font-semibold text-foreground">
              {{ stats[card.key] }}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 检索测试 -->
    <Card class="mb-4">
      <CardContent class="p-4">
        <div class="mb-3 flex items-center gap-2">
          <Sparkles class="size-4 text-primary" :stroke-width="1.5" />
          <span class="text-sm font-medium text-foreground">检索测试</span>
          <Badge variant="secondary" class="text-[10px]">
            top-{{ searchTopK }}
          </Badge>
        </div>

        <div class="flex flex-col gap-2 sm:flex-row">
          <div class="relative flex-1">
            <Search
              class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              :stroke-width="1.5"
            />
            <Input
              v-model="searchQuery"
              placeholder="输入查询文本进行检索测试"
              class="pl-9"
              @keyup.enter="handleSearch"
            />
          </div>
          <Input
            v-model.number="searchTopK"
            type="number"
            min="1"
            max="20"
            placeholder="K"
            class="sm:w-[88px]"
          />
          <Button class="sm:w-[100px]" :disabled="searching" @click="handleSearch">
            <Loader2 v-if="searching" class="size-4 animate-spin" :stroke-width="1.5" />
            <Send v-else class="size-4" :stroke-width="1.5" />
            检索
          </Button>
        </div>

        <!-- 检索结果 -->
        <div v-if="hasSearched" class="mt-4 space-y-2">
          <div class="flex items-center justify-between">
            <p class="text-xs text-muted-foreground">
              共检索到 <strong class="font-mono text-primary">{{ searchTotal }}</strong> 条结果
            </p>
          </div>

          <div v-if="searching" class="space-y-2">
            <Skeleton v-for="i in 3" :key="i" class="h-20 w-full" />
          </div>

          <EmptyState
            v-else-if="searchResults.length === 0"
            :icon="Search"
            title="无检索结果"
            description="尝试更换查询关键词或检查文档是否已索引"
            class="py-8"
          />

          <div v-else class="space-y-2">
            <div
              v-for="result in searchResults"
              :key="result.chunk_id"
              class="rounded-md border border-border bg-muted/20 p-3 transition-colors hover:bg-muted/40"
            >
              <div class="mb-2 flex items-center justify-between gap-2">
                <div class="flex items-center gap-2">
                  <Badge variant="secondary" class="font-mono text-[10px]">
                    #{{ result.rank }}
                  </Badge>
                  <span class="truncate text-xs text-muted-foreground" :title="result.title_chain">
                    {{ result.title_chain }}
                  </span>
                </div>
                <Tooltip :side="'left'">
                  <template #trigger>
                    <Badge variant="outline" class="font-mono text-[10px]">
                      {{ formatScore(result.score) }}
                    </Badge>
                  </template>
                  <span>相似度分数</span>
                </Tooltip>
              </div>
              <p class="line-clamp-3 text-sm text-foreground">{{ result.text }}</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 文档表格 -->
    <Card>
      <CardContent class="p-0">
        <div class="flex items-center justify-between border-b border-border px-4 py-3">
          <div class="flex items-center gap-2">
            <Database class="size-4 text-primary" :stroke-width="1.5" />
            <span class="text-sm font-medium text-foreground">已解析文档</span>
            <Badge variant="secondary" class="font-mono text-[10px]">
              {{ documents.length }}
            </Badge>
          </div>
        </div>

        <!-- 表头 -->
        <div
          class="hidden grid-cols-12 gap-3 border-b border-border bg-muted/40 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground lg:grid"
        >
          <div class="col-span-5">文件名</div>
          <div class="col-span-2">类型</div>
          <div class="col-span-3">状态</div>
          <div class="col-span-2 text-right">操作</div>
        </div>

        <!-- 加载态 -->
        <div v-if="listLoading" class="divide-y divide-border">
          <div v-for="i in 5" :key="i" class="grid grid-cols-12 gap-3 px-4 py-3">
            <Skeleton class="col-span-4 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-2 h-5" />
          </div>
        </div>

        <!-- 空态 -->
        <EmptyState
          v-else-if="documents.length === 0"
          :icon="Database"
          title="暂无已解析文档"
          description="请先在文档管理中上传并解析文档，已解析的文档可在此处进行索引管理"
          class="py-16"
        />

        <!-- 数据行 -->
        <div v-else class="divide-y divide-border">
          <div
            v-for="doc in documents"
            :key="doc.id"
            class="grid grid-cols-12 gap-3 px-4 py-3 transition-colors hover:bg-muted/30"
          >
            <!-- 文件名 -->
            <div class="col-span-12 lg:col-span-5">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">文件名</div>
              <p class="truncate font-medium text-foreground" :title="doc.filename">
                {{ doc.filename }}
              </p>
            </div>

            <!-- 类型 -->
            <div class="col-span-6 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">类型</div>
              <Badge v-if="doc.file_type" variant="outline" class="text-[10px] uppercase">
                {{ doc.file_type }}
              </Badge>
              <span v-else class="text-xs text-muted-foreground">-</span>
            </div>

            <!-- 状态 -->
            <div class="col-span-6 lg:col-span-3">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">状态</div>
              <StatusBadge :status="doc.status" kind="document" />
            </div>

            <!-- 操作 -->
            <div class="col-span-6 flex items-center justify-end gap-1 lg:col-span-2">
              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="indexingIds.has(doc.id)"
                    aria-label="索引"
                    @click="handleIndex(doc)"
                  >
                    <Loader2
                      v-if="indexingIds.has(doc.id)"
                      class="size-3.5 animate-spin"
                      :stroke-width="1.5"
                    />
                    <Sparkles v-else class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>索引文档</span>
              </Tooltip>
              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="removingIds.has(doc.id)"
                    aria-label="移除"
                    @click="openRemoveDialog(doc)"
                  >
                    <Loader2
                      v-if="removingIds.has(doc.id)"
                      class="size-3.5 animate-spin"
                      :stroke-width="1.5"
                    />
                    <Trash2 v-else class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>移除索引</span>
              </Tooltip>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 重建索引确认 Dialog -->
    <Dialog
      :open="rebuildDialogVisible"
      title="重建全部索引"
      description="该操作将清空现有向量索引并重新索引"
      @update:open="(v) => (rebuildDialogVisible = v)"
    >
      <div class="flex items-start gap-3 rounded-md border border-warning/30 bg-warning/5 p-3">
        <AlertTriangle class="mt-0.5 size-4 shrink-0 text-warning" :stroke-width="1.5" />
        <div class="flex-1 space-y-1 text-sm">
          <p class="font-medium text-foreground">确认重建全部索引？</p>
          <p class="text-xs text-muted-foreground">
            该操作将清空 Milvus 中的现有向量索引，重新扫描所有已解析文档并建立索引。任务异步执行，可能耗时较长。
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="rebuildDialogVisible = false">取消</Button>
        <Button variant="destructive" :disabled="rebuilding" @click="confirmRebuild">
          <Loader2 v-if="rebuilding" class="size-4 animate-spin" :stroke-width="1.5" />
          <RefreshCw v-else class="size-4" :stroke-width="1.5" />
          确认重建
        </Button>
      </div>
    </Dialog>

    <!-- 移除索引确认 Dialog -->
    <Dialog
      :open="removeDialogVisible"
      title="移除文档索引"
      :description="`即将移除文档「${removeTarget?.filename}」的索引`"
      @update:open="(v) => (removeDialogVisible = v)"
    >
      <div v-if="removeTarget" class="space-y-3">
        <div class="flex items-start gap-3 rounded-md border border-danger/30 bg-danger/5 p-3">
          <X class="mt-0.5 size-4 shrink-0 text-danger" :stroke-width="1.5" />
          <div class="flex-1 space-y-1 text-sm">
            <p class="text-foreground">
              即将移除文档
              <span class="font-medium">{{ removeTarget.filename }}</span>
              的向量索引
            </p>
            <p class="text-xs text-muted-foreground">
              移除后该文档将不可被检索，但文档记录与解析结果不受影响。该操作不可恢复。
            </p>
          </div>
        </div>

        <div class="space-y-2 rounded-md border border-border bg-muted/20 p-3">
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div>
              <p class="text-muted-foreground">文件类型</p>
              <p class="text-foreground">{{ removeTarget.file_type || '-' }}</p>
            </div>
            <div>
              <p class="text-muted-foreground">文件大小</p>
              <p class="font-mono text-foreground">{{ removeTarget.file_size }} B</p>
            </div>
          </div>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="removeDialogVisible = false">取消</Button>
        <Button variant="destructive" :disabled="removingIds.has(removeTarget?.id || '')" @click="confirmRemove">
          <Trash2 class="size-4" :stroke-width="1.5" />
          确认移除
        </Button>
      </div>
    </Dialog>
  </div>
</template>
