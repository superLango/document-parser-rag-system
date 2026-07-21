<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { FileText, ListChecks, Braces, BookOpen, TrendingUp, ArrowRight, Clock } from 'lucide-vue-next'
import { dashboardApi } from '@/api/modules/dashboard'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { StatusBadge } from '@/components/ui/status-badge'
import { Button } from '@/components/ui/button'
import type { DashboardStats } from '@/api/types'

const router = useRouter()

const loading = ref(true)
const stats = ref<DashboardStats | null>(null)

const statCards = [
  { key: 'documents_count' as const, label: '文档总数', icon: FileText, accent: 'text-primary' },
  { key: 'tasks_count' as const, label: '解析任务', icon: ListChecks, accent: 'text-info' },
  { key: 'schemas_count' as const, label: '抽取 Schema', icon: Braces, accent: 'text-success' },
  { key: 'terms_count' as const, label: '术语条目', icon: BookOpen, accent: 'text-warning' },
]

const successRate = computed(() => {
  if (!stats.value) return 0
  return Math.round(stats.value.success_rate * 100) / 100
})

async function fetchStats() {
  loading.value = true
  try {
    stats.value = await dashboardApi.getStats()
  } catch {
    stats.value = {
      documents_count: 0,
      tasks_count: 0,
      schemas_count: 0,
      terms_count: 0,
      success_rate: 0,
      recent_documents: [],
      recent_tasks: [],
    }
  } finally {
    loading.value = false
  }
}

function gotoDocuments() {
  router.push('/documents')
}

function gotoTasks() {
  router.push('/tasks')
}

onMounted(fetchStats)
</script>

<template>
  <div>
    <PageHeader title="仪表盘" description="系统运行概览与近期活动" />

    <!-- KPI 卡片 -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card v-for="card in statCards" :key="card.key">
        <CardContent class="flex items-center gap-4 p-5">
          <div
            class="flex size-11 shrink-0 items-center justify-center rounded-lg bg-muted"
            :class="card.accent"
          >
            <component :is="card.icon" class="size-5" :stroke-width="1.5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-2xl font-semibold tabular-nums text-foreground">
              <Skeleton v-if="loading" class="h-6 w-16" />
              <template v-else>{{ stats?.[card.key] ?? 0 }}</template>
            </div>
            <div class="text-xs text-muted-foreground">{{ card.label }}</div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 成功率横幅 -->
    <Card class="mt-4">
      <CardContent class="flex items-center gap-4 p-5">
        <div class="flex size-10 items-center justify-center rounded-lg bg-success/15 text-success">
          <TrendingUp class="size-5" :stroke-width="1.5" />
        </div>
        <div class="flex-1">
          <div class="text-sm font-medium text-foreground">解析成功率</div>
          <div class="text-xs text-muted-foreground">最近 7 天任务执行成功比例</div>
        </div>
        <div class="text-2xl font-semibold tabular-nums text-foreground">
          <Skeleton v-if="loading" class="h-6 w-20" />
          <template v-else>{{ successRate }}%</template>
        </div>
      </CardContent>
    </Card>

    <!-- 近期活动 -->
    <div class="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
      <!-- 近期文档 -->
      <Card>
        <CardHeader class="flex-row items-center justify-between space-y-0">
          <CardTitle class="text-base">近期文档</CardTitle>
          <Button variant="ghost" size="sm" class="h-7 gap-1 text-xs" @click="gotoDocuments">
            查看全部
            <ArrowRight class="size-3" :stroke-width="1.5" />
          </Button>
        </CardHeader>
        <CardContent class="p-0">
          <div v-if="loading" class="space-y-3 p-5 pt-0">
            <Skeleton v-for="i in 4" :key="i" class="h-9 w-full" />
          </div>
          <template v-else-if="stats?.recent_documents.length">
            <ul class="divide-y divide-border">
              <li
                v-for="doc in stats.recent_documents"
                :key="doc.id"
                class="flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-muted/50"
              >
                <FileText class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-sm font-medium text-foreground">{{ doc.filename }}</div>
                  <div class="text-xs text-muted-foreground font-mono">
                    {{ doc.file_type || '文档' }}
                  </div>
                </div>
                <StatusBadge :status="doc.status" kind="document" />
              </li>
            </ul>
          </template>
          <EmptyState
            v-else
            :icon="FileText"
            title="暂无文档"
            description="上传 PDF 文档后将在此显示"
            class="py-8"
          />
        </CardContent>
      </Card>

      <!-- 近期任务 -->
      <Card>
        <CardHeader class="flex-row items-center justify-between space-y-0">
          <CardTitle class="text-base">近期任务</CardTitle>
          <Button variant="ghost" size="sm" class="h-7 gap-1 text-xs" @click="gotoTasks">
            查看全部
            <ArrowRight class="size-3" :stroke-width="1.5" />
          </Button>
        </CardHeader>
        <CardContent class="p-0">
          <div v-if="loading" class="space-y-3 p-5 pt-0">
            <Skeleton v-for="i in 4" :key="i" class="h-9 w-full" />
          </div>
          <template v-else-if="stats?.recent_tasks.length">
            <ul class="divide-y divide-border">
              <li
                v-for="task in stats.recent_tasks"
                :key="task.id"
                class="flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-muted/50"
              >
                <ListChecks class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
                <div class="min-w-0 flex-1">
                  <div class="truncate font-mono text-sm text-foreground">
                    TASK-{{ task.id.slice(0, 8) }}
                  </div>
                  <div class="flex items-center gap-1 text-xs text-muted-foreground">
                    <Clock class="size-3" :stroke-width="1.5" />
                    {{ task.task_type }}
                  </div>
                </div>
                <StatusBadge :status="task.status" kind="task" />
              </li>
            </ul>
          </template>
          <EmptyState
            v-else
            :icon="ListChecks"
            title="暂无任务"
            description="提交解析任务后将在此显示"
            class="py-8"
          />
        </CardContent>
      </Card>
    </div>
  </div>
</template>
