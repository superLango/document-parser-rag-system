<script setup lang="ts">
/**
 * 知识库列表页
 *
 * 展示当前用户参与的知识库列表，支持搜索、新建。
 * 点击知识库卡片进入 KBLayout。
 */
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  Database,
  Plus,
  Search,
  RefreshCw,
  Loader2,
  FileText,
  Users,
  Settings,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import type { KnowledgeBase, KbRole } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'

const router = useRouter()

const loading = ref(true)
const knowledgeBases = ref<KnowledgeBase[]>([])
const searchQuery = ref('')

const filteredKbs = computed(() => {
  if (!searchQuery.value.trim()) return knowledgeBases.value
  const q = searchQuery.value.toLowerCase()
  return knowledgeBases.value.filter(
    (kb) =>
      kb.name.toLowerCase().includes(q) ||
      kb.description?.toLowerCase().includes(q) ||
      kb.domain_code.toLowerCase().includes(q),
  )
})

async function fetchKbs() {
  loading.value = true
  try {
    const res = await kbApi.list({ page: 1, page_size: 100 })
    knowledgeBases.value = res.items
  } catch {
    knowledgeBases.value = []
  } finally {
    loading.value = false
  }
}

function enterKb(kb: KnowledgeBase) {
  router.push({ name: 'KbOverview', params: { kb_id: kb.id } })
}

function goCreate() {
  router.push({ name: 'KbCreate' })
}

const roleLabel: Record<KbRole, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}
const roleColor: Record<KbRole, string> = {
  owner: 'bg-primary/10 text-primary',
  admin: 'bg-success/10 text-success',
  editor: 'bg-warning/10 text-warning',
  viewer: 'bg-muted text-muted-foreground',
}

function formatTime(value: string | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleDateString('zh-CN')
  } catch {
    return value
  }
}

onMounted(fetchKbs)
</script>

<template>
  <div>
    <PageHeader title="知识库" description="以知识库为隔离边界的垂直领域文档智能产品">
      <template #actions>
        <Button variant="outline" @click="fetchKbs">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button @click="goCreate">
          <Plus class="size-4" :stroke-width="1.5" />
          新建知识库
        </Button>
      </template>
    </PageHeader>

    <!-- 搜索栏 -->
    <div class="mb-4">
      <div class="relative max-w-md">
        <Search
          class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          :stroke-width="1.5"
        />
        <Input
          v-model="searchQuery"
          placeholder="搜索知识库名称、描述或领域..."
          class="pl-9"
        />
      </div>
    </div>

    <!-- 加载态 -->
    <div v-if="loading" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card v-for="i in 6" :key="i">
        <CardContent class="p-5">
          <Skeleton class="mb-3 h-6 w-2/3" />
          <Skeleton class="mb-4 h-4 w-full" />
          <div class="flex gap-2">
            <Skeleton class="h-5 w-16" />
            <Skeleton class="h-5 w-16" />
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="filteredKbs.length === 0"
      :icon="Database"
      title="暂无知识库"
      :description="searchQuery ? '未找到匹配的知识库' : '点击「新建知识库」创建第一个知识库'"
      class="py-16"
    >
      <template v-if="!searchQuery" #actions>
        <Button @click="goCreate">
          <Plus class="size-4" :stroke-width="1.5" />
          新建知识库
        </Button>
      </template>
    </EmptyState>

    <!-- 知识库卡片网格 -->
    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="kb in filteredKbs"
        :key="kb.id"
        class="cursor-pointer transition-all hover:border-primary/40 hover:shadow-md"
        @click="enterKb(kb)"
      >
        <CardContent class="p-5">
          <!-- 头部：图标 + 名称 + 状态 -->
          <div class="mb-3 flex items-start justify-between gap-2">
            <div class="flex items-center gap-2.5">
              <div
                class="flex size-10 shrink-0 items-center justify-center rounded-md"
                :class="kb.is_active ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'"
              >
                <Database class="size-5" :stroke-width="1.5" />
              </div>
              <div class="min-w-0">
                <p class="truncate font-semibold text-foreground" :title="kb.name">{{ kb.name }}</p>
                <p class="font-mono text-[10px] text-muted-foreground">{{ kb.domain_code }}</p>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <span
                v-if="!kb.is_active"
                class="rounded bg-danger/10 px-1.5 py-0.5 text-[10px] text-danger"
              >
                停用
              </span>
              <span
                v-if="kb.my_role"
                class="rounded px-1.5 py-0.5 text-[10px] font-medium"
                :class="roleColor[kb.my_role as KbRole]"
              >
                {{ roleLabel[kb.my_role as KbRole] }}
              </span>
            </div>
          </div>

          <!-- 描述 -->
          <p class="mb-4 line-clamp-2 min-h-[2.5rem] text-sm text-muted-foreground">
            {{ kb.description || '暂无描述' }}
          </p>

          <!-- 底部：模板 + 创建时间 -->
          <div class="flex items-center justify-between text-[11px] text-muted-foreground">
            <div class="flex items-center gap-2">
              <Badge v-if="kb.template_code" variant="secondary" class="text-[10px]">
                {{ kb.template_code }}
              </Badge>
              <span>{{ formatTime(kb.created_at) }}</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
