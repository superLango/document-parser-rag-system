<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  FileText,
  FileSearch,
  ArrowRight,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
} from 'lucide-vue-next'
import { extractionApi, type ExtractableDocument } from '@/api/modules/extraction'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Tooltip } from '@/components/ui/tooltip'

const router = useRouter()

// ---------- 文档列表 ----------
const loading = ref(true)
const documents = ref<ExtractableDocument[]>([])

async function fetchList() {
  loading.value = true
  try {
    const res = await extractionApi.listDocuments()
    documents.value = res.items
  } catch {
    documents.value = []
  } finally {
    loading.value = false
  }
}

// ---------- 跳转到抽取操作页 ----------
function startExtraction(doc: ExtractableDocument) {
  router.push(`/extraction/${doc.id}`)
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTextLength(len: number): string {
  if (len < 1000) return `${len} 字符`
  if (len < 10000) return `${(len / 1000).toFixed(1)}k 字符`
  return `${(len / 10000).toFixed(1)}w 字符`
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

onMounted(fetchList)
</script>

<template>
  <div>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <PageHeader
        title="文档抽取"
        description="对已完成 OCR 解析的文档进行基于 LangExtract 的结构化字段抽取"
      />
      <Button variant="outline" class="mb-6 shrink-0 gap-2" @click="fetchList">
        <RefreshCw class="size-4" :stroke-width="1.5" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <!-- 加载态 -->
    <div v-if="loading" class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      <Skeleton v-for="i in 6" :key="i" class="h-32 w-full" />
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="documents.length === 0"
      :icon="FileSearch"
      title="暂无可抽取的文档"
      description="需要先上传文档并完成 OCR 解析后，才能进行结构化抽取"
      class="py-16"
    >
      <Button class="mt-2" @click="router.push('/documents')">
        前往文档管理
        <ArrowRight class="size-4" :stroke-width="1.5" />
      </Button>
    </EmptyState>

    <!-- 文档卡片列表 -->
    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="doc in documents"
        :key="doc.id"
        class="group cursor-pointer transition-all hover:border-primary/40 hover:shadow-md"
        @click="startExtraction(doc)"
      >
        <CardContent class="flex h-full flex-col gap-3 p-4">
          <!-- 头部：图标 + 文件名 + 状态 -->
          <div class="flex items-start gap-3">
            <div class="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <FileText class="size-5" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <h3
                class="truncate text-sm font-medium text-foreground group-hover:text-primary"
                :title="doc.filename"
              >
                {{ doc.filename }}
              </h3>
              <div class="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge variant="success" class="gap-1 text-[10px]">
                  <CheckCircle2 class="size-2.5" :stroke-width="2" />
                  OCR 已完成
                </Badge>
                <Badge
                  v-if="doc.has_extraction"
                  variant="info"
                  class="gap-1 text-[10px]"
                >
                  <CheckCircle2 class="size-2.5" :stroke-width="2" />
                  已有抽取
                </Badge>
                <Badge v-else variant="secondary" class="gap-1 text-[10px]">
                  <Clock class="size-2.5" :stroke-width="2" />
                  待抽取
                </Badge>
              </div>
            </div>
          </div>

          <!-- 元信息 -->
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="rounded-md bg-muted/30 px-2 py-1.5">
              <p class="text-[10px] uppercase tracking-wide text-muted-foreground">文件大小</p>
              <p class="font-mono text-foreground">{{ formatFileSize(doc.file_size) }}</p>
            </div>
            <div class="rounded-md bg-muted/30 px-2 py-1.5">
              <p class="text-[10px] uppercase tracking-wide text-muted-foreground">文本长度</p>
              <p class="font-mono text-foreground">{{ formatTextLength(doc.text_length) }}</p>
            </div>
          </div>

          <!-- 底部：时间 + 操作按钮 -->
          <div class="mt-auto flex items-center justify-between border-t border-border pt-3">
            <span class="truncate text-[10px] text-muted-foreground" :title="formatTime(doc.created_at)">
              {{ formatTime(doc.created_at) }}
            </span>
            <Tooltip :side="'top'">
              <template #trigger>
                <Button
                  size="sm"
                  class="h-7 gap-1.5"
                  @click.stop="startExtraction(doc)"
                >
                  开始抽取
                  <ArrowRight class="size-3.5" :stroke-width="1.5" />
                </Button>
              </template>
              <span>进入抽取操作页</span>
            </Tooltip>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
