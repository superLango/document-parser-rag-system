<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Play,
  History,
  FileText,
  CheckCircle2,
  Clock,
  RefreshCw,
  ShieldCheck,
  Braces,
  Calendar,
  Loader2,
} from 'lucide-vue-next'
import { kbApi, type KbExtractableDocument } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Dialog } from '@/components/ui/dialog'

const router = useRouter()
const kbStore = useKbStore()
const kbId = kbStore.currentKb?.id || ''

const docsLoading = ref(true)
const documents = ref<KbExtractableDocument[]>([])
const historyDialogOpen = ref(false)
const historyLoading = ref(false)
const selectedDocForHistory = ref<KbExtractableDocument | null>(null)
const historyItems = ref<Array<{
  schema_name: string | null
  extracted_at: string | null
  is_latest: boolean
}>>([])

const statusConfig: Record<string, { color: string; glow: string }> = {
  completed: {
    color: 'bg-success/10 text-success border-success/30',
    glow: 'shadow-[0_0_12px_rgba(46,160,93,0.25)]',
  },
  pending: {
    color: 'bg-muted text-muted-foreground border-muted-foreground/20',
    glow: '',
  },
  processing: {
    color: 'bg-warning/10 text-warning border-warning/30',
    glow: 'shadow-[0_0_12px_rgba(179,142,36,0.25)]',
  },
}

async function fetchDocuments() {
  docsLoading.value = true
  try {
    const res = await kbApi.listExtractableDocuments(kbId)
    documents.value = res.items
  } catch {
    documents.value = []
  } finally {
    docsLoading.value = false
  }
}

function handleExtract(doc: KbExtractableDocument) {
  router.push({ name: 'KbExtractionDetail', params: { kb_id: kbId, doc_id: doc.id } })
}

async function handleViewHistory(doc: KbExtractableDocument) {
  selectedDocForHistory.value = doc
  historyDialogOpen.value = true
  historyLoading.value = true
  historyItems.value = []
  try {
    const res = await kbApi.getExtractionHistory(kbId, doc.id)
    historyItems.value = res.items.map((item) => ({
      schema_name: item.schema_name,
      extracted_at: item.extracted_at,
      is_latest: item.is_latest,
    }))
  } catch {
    historyItems.value = []
  } finally {
    historyLoading.value = false
  }
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

onMounted(() => {
  fetchDocuments()
})
</script>

<template>
  <div class="space-y-5 bg-subtle-gradient min-h-full">
    <PageHeader title="结构化抽取" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Badge variant="secondary" class="gap-1.5 border border-primary/20 bg-primary/5 text-primary shadow-primary/20 shadow-sm">
          <ShieldCheck class="size-3.5" :stroke-width="1.5" />
          RLS 隔离
        </Badge>
        <Button variant="outline" size="sm" @click="fetchDocuments" class="gap-1.5 transition-all hover:border-primary/30 hover:bg-primary/5">
          <RefreshCw class="size-3.5" :class="{ 'animate-spin': docsLoading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <Card class="overflow-hidden border-border/60 shadow-sm transition-all hover:shadow-md">
      <CardContent class="p-0">
        <div v-if="docsLoading" class="divide-y divide-border/50">
          <div v-for="i in 5" :key="i" class="flex items-center gap-4 p-4">
            <Skeleton class="size-11 rounded-xl skeleton-shimmer" />
            <div class="flex-1 space-y-2.5">
              <Skeleton class="h-4 w-1/3 skeleton-shimmer" />
              <Skeleton class="h-3 w-1/4 skeleton-shimmer" />
            </div>
            <Skeleton class="h-9 w-20 rounded-lg skeleton-shimmer" />
            <Skeleton class="h-9 w-24 rounded-lg skeleton-shimmer" />
          </div>
        </div>

        <EmptyState
          v-else-if="documents.length === 0"
          :icon="FileText"
          title="无可抽取文档"
          description="请先上传文档并完成 OCR 解析"
          class="py-20"
        />

        <div v-else class="divide-y divide-border/50">
          <div
            v-for="doc in documents"
            :key="doc.id"
            class="group flex items-center gap-4 p-4 transition-all duration-300 hover:bg-gradient-to-r hover:from-primary/[0.03] hover:to-transparent hover:shadow-[inset_0_1px_0_rgba(0,0,0,0.02)] relative"
          >
            <div class="absolute left-0 top-1/2 h-0 w-0.5 -translate-y-1/2 rounded-r bg-gradient-to-b from-primary/80 to-primary/40 transition-all duration-300 group-hover:h-8" />

            <div class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-primary/5 text-primary transition-all duration-300 group-hover:scale-105 group-hover:from-primary/25 group-hover:to-primary/10 group-hover:shadow-primary group-hover:shadow-md">
              <FileText class="size-5" :stroke-width="1.5" />
            </div>

            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <p class="truncate text-sm font-medium text-foreground transition-colors group-hover:text-foreground" :title="doc.filename">
                  {{ doc.filename }}
                </p>
                <Badge
                  v-if="doc.status"
                  variant="secondary"
                  :class="[statusConfig[doc.status]?.color || 'bg-muted text-muted-foreground', statusConfig[doc.status]?.glow || '']"
                  class="gap-1 border px-2 py-0.5 text-[10px] font-medium transition-all duration-300"
                >
                  <Loader2 v-if="doc.status === 'processing'" class="size-3 animate-spin" :stroke-width="2" />
                  <CheckCircle2 v-else-if="doc.status === 'completed'" class="size-3" :stroke-width="2" />
                  {{ doc.status === 'completed' ? '已解析' : doc.status === 'processing' ? '解析中' : doc.status }}
                </Badge>
                <div class="relative">
                  <CheckCircle2
                    v-if="doc.has_extraction"
                    class="size-4 text-success transition-all duration-300 group-hover:scale-110"
                    :stroke-width="2"
                  />
                  <div v-if="doc.has_extraction" class="absolute inset-0 animate-ping rounded-full bg-success/20 opacity-0 group-hover:opacity-100" />
                </div>
              </div>
              <div class="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                <span class="tabular-nums">{{ formatSize(doc.file_size) }}</span>
                <span class="opacity-40">·</span>
                <span>{{ doc.text_length }} 字符</span>
                <span v-if="doc.latest_schema_name" class="inline-flex items-center gap-1 transition-colors group-hover:text-primary/80">
                  <span class="opacity-40">·</span>
                  <Braces class="size-3" :stroke-width="1.5" />
                  <span>{{ doc.latest_schema_name }}</span>
                </span>
                <span v-if="doc.history_count" class="inline-flex items-center gap-1 transition-colors group-hover:text-info/80">
                  <span class="opacity-40">·</span>
                  <History class="size-3" :stroke-width="1.5" />
                  <span>{{ doc.history_count }} 个历史版本</span>
                </span>
              </div>
            </div>

            <div class="hidden shrink-0 text-right text-xs text-muted-foreground sm:block">
              <div class="flex items-center gap-1.5 transition-colors group-hover:text-foreground/80">
                <Calendar class="size-3" :stroke-width="1.5" />
                <span class="tabular-nums">{{ formatDate(doc.latest_extracted_at || doc.updated_at) }}</span>
              </div>
            </div>

            <div class="flex shrink-0 items-center gap-1.5 opacity-80 transition-opacity duration-300 group-hover:opacity-100">
              <Button
                variant="ghost"
                size="sm"
                :disabled="!doc.has_extraction"
                class="gap-1.5 rounded-lg transition-all hover:bg-info/10 hover:text-info disabled:opacity-40"
                @click="handleViewHistory(doc)"
              >
                <History class="size-3.5" :stroke-width="1.5" />
                历史
              </Button>
              <Button size="sm" class="gap-1.5 rounded-lg shadow-sm shadow-primary/20 transition-all hover:shadow-primary hover:-translate-y-0.5" @click="handleExtract(doc)">
                <Play class="size-3.5" :stroke-width="1.5" />
                抽取
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <Dialog
      :open="historyDialogOpen"
      title="抽取历史"
      class="max-w-lg"
      @update:open="(v: boolean) => (historyDialogOpen = v)"
    >
      <p v-if="selectedDocForHistory" class="-mt-2 mb-4 flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm">
        <FileText class="size-4 text-primary/70" :stroke-width="1.5" />
        <span class="truncate font-medium">{{ selectedDocForHistory.filename }}</span>
      </p>

      <div v-if="historyLoading" class="space-y-3">
        <Skeleton v-for="i in 3" :key="i" class="h-16 w-full rounded-lg skeleton-shimmer" />
      </div>

      <EmptyState
        v-else-if="historyItems.length === 0"
        :icon="Clock"
        title="暂无抽取记录"
        description="该文档尚未进行过抽取"
        class="py-12"
      />

      <div v-else class="max-h-96 space-y-2 overflow-y-auto pr-1">
        <div
          v-for="(item, idx) in historyItems"
          :key="idx"
          class="group cursor-pointer rounded-xl border p-3.5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
          :class="item.is_latest ? 'border-primary/30 bg-gradient-to-br from-primary/5 to-transparent hover:border-primary/50 hover:shadow-primary/20' : 'border-border/60 hover:border-border bg-card/50'"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <div
                class="flex size-8 items-center justify-center rounded-lg transition-all duration-300 group-hover:scale-105"
                :class="item.is_latest ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'"
              >
                <Braces class="size-4" :stroke-width="1.5" />
              </div>
              <div>
                <span class="text-sm font-medium">
                  {{ item.schema_name || '未知 Schema' }}
                </span>
                <div v-if="item.is_latest" class="mt-0.5">
                  <Badge class="gap-1 border-0 bg-gradient-to-r from-primary to-primary/80 px-1.5 py-0 text-[10px] text-primary-foreground shadow-primary/30 shadow-sm">
                    <CheckCircle2 class="size-2.5" :stroke-width="2.5" />
                    最新
                  </Badge>
                </div>
              </div>
            </div>
            <span class="text-xs tabular-nums text-muted-foreground transition-colors group-hover:text-foreground/70">
              {{ formatDate(item.extracted_at) }}
            </span>
          </div>
        </div>
      </div>
    </Dialog>
  </div>
</template>
