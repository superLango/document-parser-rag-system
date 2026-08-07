<script setup lang="ts">
/**
 * 全局仪表盘
 *
 * 展示跨知识库的统计数据：6 个指标卡片 + 30 天趋势折线图 +
 * 文档类型分布柱状图 + 任务状态分布环形图 + 最近文档/任务。
 */
import { ref, onMounted, computed } from 'vue'
import {
  FileText,
  ListChecks,
  Database,
  BookMarked,
  FolderTree,
  Users,
  RefreshCw,
  Loader2,
  CheckCircle2,
} from 'lucide-vue-next'
import { dashboardApi, type DashboardStats, type DashboardTrends, type DashboardDistribution } from '@/api/modules/dashboard'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { LineChart, BarChart, DonutChart } from '@/components/charts'

const loading = ref(true)
const stats = ref<DashboardStats | null>(null)
const trends = ref<DashboardTrends | null>(null)
const distribution = ref<DashboardDistribution | null>(null)

const statCards = computed(() => [
  { label: '知识库', value: stats.value?.kbs_count ?? 0, icon: FolderTree, color: 'bg-primary/10 text-primary' },
  { label: '文档', value: stats.value?.documents_count ?? 0, icon: FileText, color: 'bg-success/10 text-success' },
  { label: '任务', value: stats.value?.tasks_count ?? 0, icon: ListChecks, color: 'bg-warning/10 text-warning' },
  { label: 'Schema', value: stats.value?.schemas_count ?? 0, icon: Database, color: 'bg-info/10 text-info' },
  { label: '术语', value: stats.value?.terms_count ?? 0, icon: BookMarked, color: 'bg-danger/10 text-danger' },
  { label: '用户', value: stats.value?.users_count ?? 0, icon: Users, color: 'bg-primary/10 text-primary' },
])

// 趋势折线图数据
const trendChartData = computed(() => ({
  labels: trends.value?.dates ?? [],
  datasets: [
    {
      label: '文档上传',
      data: trends.value?.documents ?? [],
      borderColor: 'rgb(74, 163, 255)',
      backgroundColor: 'rgba(74, 163, 255, 0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    },
    {
      label: '任务创建',
      data: trends.value?.tasks ?? [],
      borderColor: 'rgb(250, 140, 22)',
      backgroundColor: 'rgba(250, 140, 22, 0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    },
  ],
}))

// 文档类型分布柱状图
const docTypeChartData = computed(() => ({
  labels: distribution.value?.doc_types.map((d) => d.name) ?? [],
  datasets: [
    {
      label: '文档数',
      data: distribution.value?.doc_types.map((d) => d.value) ?? [],
      backgroundColor: 'rgba(74, 163, 255, 0.7)',
      borderColor: 'rgb(74, 163, 255)',
      borderWidth: 1,
    },
  ],
}))

// 任务状态分布环形图
const taskStatusChartData = computed(() => {
  const palette: Record<string, string> = {
    success: 'rgba(82, 196, 26, 0.8)',
    failed: 'rgba(245, 63, 63, 0.8)',
    running: 'rgba(74, 163, 255, 0.8)',
    pending: 'rgba(250, 140, 22, 0.8)',
    started: 'rgba(19, 194, 194, 0.8)',
    progress: 'rgba(114, 46, 209, 0.8)',
  }
  const items = distribution.value?.task_statuses ?? []
  return {
    labels: items.map((i) => i.name),
    datasets: [
      {
        data: items.map((i) => i.value),
        backgroundColor: items.map((i) => palette[i.name] || 'rgba(148, 163, 184, 0.8)'),
        borderWidth: 2,
        borderColor: 'rgba(15, 22, 35, 0.8)',
      },
    ],
  }
})

const trendOptions = {
  scales: {
    x: { ticks: { color: 'rgb(148, 163, 184)', maxTicksLimit: 8 }, grid: { color: 'rgba(148, 163, 184, 0.1)' } },
    y: { ticks: { color: 'rgb(148, 163, 184)', precision: 0 }, grid: { color: 'rgba(148, 163, 184, 0.1)' }, beginAtZero: true },
  },
}

async function fetchAll() {
  loading.value = true
  try {
    const [s, t, d] = await Promise.all([
      dashboardApi.stats(),
      dashboardApi.trends(30),
      dashboardApi.distribution(),
    ])
    stats.value = s
    trends.value = t
    distribution.value = d
  } catch {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

onMounted(fetchAll)
</script>

<template>
  <div>
    <PageHeader title="仪表盘" description="跨知识库全局统计与趋势">
      <template #actions>
        <Button variant="outline" size="sm" :disabled="loading" @click="fetchAll">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
      <Card
        v-for="card in statCards"
        :key="card.label"
        class="hover:shadow-md hover:border-primary/20 transition-all duration-200 hover:-translate-y-0.5"
      >
        <CardContent class="flex items-center gap-3 p-4">
          <div
            class="flex size-11 shrink-0 items-center justify-center rounded-lg shadow-sm transition-transform duration-200"
            :class="card.color"
          >
            <component :is="card.icon" class="size-5" :stroke-width="1.5" />
          </div>
          <div class="min-w-0">
            <p class="text-xs text-muted-foreground/80">{{ card.label }}</p>
            <p v-if="loading" class="mt-1"><Skeleton class="h-7 w-14 rounded-md" /></p>
            <p v-else class="text-2xl font-semibold tracking-tight text-foreground tabular-nums">
              {{ card.value }}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 趋势图 -->
    <Card class="mt-5">
      <CardContent class="p-5">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h3 class="text-sm font-medium text-foreground">30 天趋势</h3>
            <p class="text-xs text-muted-foreground">文档上传与任务创建</p>
          </div>
          <Badge v-if="stats" variant="success" class="text-[10px]">
            <CheckCircle2 class="mr-0.5 size-3" :stroke-width="1.5" />
            成功率 {{ stats.success_rate }}%
          </Badge>
        </div>
        <div v-if="loading" class="flex items-center justify-center py-12">
          <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
        </div>
        <LineChart v-else :data="trendChartData" :options="trendOptions" :height="280" />
      </CardContent>
    </Card>

    <!-- 分布图 -->
    <div class="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardContent class="p-5">
          <div class="mb-3">
            <h3 class="text-sm font-medium text-foreground">文档类型分布</h3>
            <p class="text-xs text-muted-foreground">按文件扩展名统计</p>
          </div>
          <div v-if="loading" class="flex items-center justify-center py-12">
            <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
          </div>
          <BarChart v-else-if="distribution && distribution.doc_types.length > 0" :data="docTypeChartData" :height="240" />
          <div v-else class="py-12 text-center text-sm text-muted-foreground">暂无数据</div>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="p-5">
          <div class="mb-3">
            <h3 class="text-sm font-medium text-foreground">任务状态分布</h3>
            <p class="text-xs text-muted-foreground">按任务当前状态统计</p>
          </div>
          <div v-if="loading" class="flex items-center justify-center py-12">
            <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
          </div>
          <DonutChart v-else-if="distribution && distribution.task_statuses.length > 0" :data="taskStatusChartData" :height="240" />
          <div v-else class="py-12 text-center text-sm text-muted-foreground">暂无数据</div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
