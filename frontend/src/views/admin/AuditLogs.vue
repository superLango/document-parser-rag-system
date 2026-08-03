<script setup lang="ts">
/**
 * 审计日志（超管专属）
 *
 * 功能：审计日志列表/多维度过滤/详情查看/操作类型聚合
 * 权限：仅超级管理员可访问
 */
import { ref, onMounted, computed } from 'vue'
import {
  ScrollText,
  RefreshCw,
  Loader2,
  Search,
  Filter,
  ChevronRight,
  BarChart3,
} from 'lucide-vue-next'
import { auditApi, type AuditLog, type AuditStats } from '@/api/modules/audit'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import { LineChart, BarChart } from '@/components/charts'

const loading = ref(true)
const logs = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// 过滤条件
const actionFilter = ref('')
const resourceTypeFilter = ref('')
const startDate = ref('')
const endDate = ref('')

// 可用操作类型
const availableActions = ref<string[]>([])

// 详情对话框
const detailOpen = ref(false)
const selectedLog = ref<AuditLog | null>(null)

const statusColor = (code: number | null): string => {
  if (!code) return 'bg-muted text-muted-foreground'
  if (code < 300) return 'bg-success/10 text-success'
  if (code < 400) return 'bg-info/10 text-info'
  if (code < 500) return 'bg-warning/10 text-warning'
  return 'bg-danger/10 text-danger'
}

const actionColor = (action: string): string => {
  if (action.includes('create') || action.includes('register')) return 'bg-success/10 text-success'
  if (action.includes('update') || action.includes('change')) return 'bg-info/10 text-info'
  if (action.includes('delete') || action.includes('remove')) return 'bg-danger/10 text-danger'
  if (action.includes('login') || action.includes('logout')) return 'bg-warning/10 text-warning'
  return 'bg-muted text-muted-foreground'
}

const actionOptions = computed(() => [
  { value: '', label: '全部操作' },
  ...availableActions.value.map((a) => ({ value: a, label: a })),
])

async function fetchActions() {
  try {
    availableActions.value = await auditApi.listActions()
  } catch {
    availableActions.value = []
  }
}

async function fetchLogs() {
  loading.value = true
  try {
    const res = await auditApi.list({
      page: page.value,
      page_size: pageSize.value,
      action: actionFilter.value || undefined,
      resource_type: resourceTypeFilter.value || undefined,
      start_date: startDate.value || undefined,
      end_date: endDate.value || undefined,
    })
    logs.value = res.items
    total.value = res.total
  } catch {
    logs.value = []
  } finally {
    loading.value = false
  }
}

function showDetail(log: AuditLog) {
  selectedLog.value = log
  detailOpen.value = true
}

function handleSearch() {
  page.value = 1
  fetchLogs()
}

function handlePageChange(p: number) {
  page.value = p
  fetchLogs()
}

function resetFilters() {
  actionFilter.value = ''
  resourceTypeFilter.value = ''
  startDate.value = ''
  endDate.value = ''
  page.value = 1
  fetchLogs()
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

function formatDetails(details: Record<string, unknown> | null): string {
  if (!details) return '-'
  try {
    return JSON.stringify(details, null, 2)
  } catch {
    return String(details)
  }
}

onMounted(() => {
  fetchActions()
  fetchLogs()
  fetchStats()
})

// ===== 审计统计 =====
const stats = ref<AuditStats | null>(null)
const statsLoading = ref(false)
const statsDays = ref(7)

async function fetchStats() {
  statsLoading.value = true
  try {
    stats.value = await auditApi.stats(statsDays.value)
  } catch {
    stats.value = null
  } finally {
    statsLoading.value = false
  }
}

const trendChartData = computed(() => {
  if (!stats.value?.by_day) return { labels: [], datasets: [] }
  return {
    labels: stats.value.by_day.map((d) => d.date.slice(5, 10)),
    datasets: [
      {
        label: '操作数',
        data: stats.value.by_day.map((d) => d.count),
        borderColor: 'hsl(var(--primary))',
        backgroundColor: 'hsl(var(--primary) / 0.1)',
        fill: true,
        tension: 0.3,
      },
    ],
  }
})

const actionChartData = computed(() => {
  if (!stats.value?.by_action) return { labels: [], datasets: [] }
  const entries = Object.entries(stats.value.by_action).slice(0, 8)
  return {
    labels: entries.map((e) => e[0]),
    datasets: [
      {
        label: '操作数',
        data: entries.map((e) => e[1]),
        backgroundColor: 'hsl(var(--primary) / 0.6)',
        borderColor: 'hsl(var(--primary))',
        borderWidth: 1,
      },
    ],
  }
})

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    y: { beginAtZero: true, grid: { color: 'hsl(var(--border))' } },
    x: { grid: { display: false } },
  },
}
</script>

<template>
  <div>
    <PageHeader title="审计日志" description="系统操作审计记录，支持多维度过滤与追溯">
      <template #actions>
        <Button variant="outline" @click="fetchLogs">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <!-- 审计统计图表 -->
    <div class="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardContent class="p-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="flex items-center gap-2 text-sm font-medium">
              <BarChart3 class="size-4" :stroke-width="1.5" />
              操作趋势（{{ statsDays }} 天）
            </h3>
            <Select
              :model-value="String(statsDays)"
              :options="[
                { label: '7 天', value: '7' },
                { label: '14 天', value: '14' },
                { label: '30 天', value: '30' },
              ]"
              class="w-28"
              @update:model-value="(v: string) => { statsDays = Number(v); fetchStats() }"
            />
          </div>
          <div v-if="statsLoading" class="flex h-48 items-center justify-center">
            <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
          </div>
          <div v-else-if="stats && stats.total > 0" class="h-48">
            <LineChart :data="trendChartData" :options="chartOptions" :height="192" />
          </div>
          <div v-else class="flex h-48 items-center justify-center text-sm text-muted-foreground">
            暂无数据
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent class="p-4">
          <h3 class="mb-3 flex items-center gap-2 text-sm font-medium">
            <BarChart3 class="size-4" :stroke-width="1.5" />
            操作类型分布（Top 8）
          </h3>
          <div v-if="statsLoading" class="flex h-48 items-center justify-center">
            <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
          </div>
          <div v-else-if="stats && stats.total > 0" class="h-48">
            <BarChart :data="actionChartData" :options="chartOptions" :height="192" />
          </div>
          <div v-else class="flex h-48 items-center justify-center text-sm text-muted-foreground">
            暂无数据
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 过滤栏 -->
    <Card class="mb-4">
      <CardContent class="flex flex-wrap items-end gap-3 p-3">
        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">操作类型</label>
          <Select
            :model-value="actionFilter"
            :options="actionOptions"
            class="w-48"
            @update:model-value="(v: string) => { actionFilter = v; handleSearch() }"
          />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">资源类型</label>
          <Input
            v-model="resourceTypeFilter"
            placeholder="user / kb / document"
            class="w-40"
            @keyup.enter="handleSearch"
          />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">开始日期</label>
          <Input v-model="startDate" type="date" class="w-40" />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">结束日期</label>
          <Input v-model="endDate" type="date" class="w-40" />
        </div>
        <Button variant="outline" size="sm" @click="handleSearch">
          <Filter class="size-4" :stroke-width="1.5" />
          筛选
        </Button>
        <Button variant="ghost" size="sm" @click="resetFilters">重置</Button>
      </CardContent>
    </Card>

    <!-- 日志列表 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-14 w-full" />
    </div>

    <EmptyState
      v-else-if="logs.length === 0"
      :icon="ScrollText"
      title="暂无审计日志"
      description="调整筛选条件或等待系统产生操作记录"
      class="py-12"
    />

    <div v-else class="space-y-1.5">
      <Card
        v-for="log in logs"
        :key="log.id"
        class="cursor-pointer transition-colors hover:bg-muted/30"
        @click="showDetail(log)"
      >
        <CardContent class="flex items-center gap-3 p-3">
          <!-- 操作类型徽章 -->
          <Badge variant="secondary" :class="actionColor(log.action)" class="shrink-0 font-mono text-[10px]">
            {{ log.action }}
          </Badge>

          <!-- 日志信息 -->
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2 text-sm">
              <span class="font-medium text-foreground">{{ log.username || '匿名' }}</span>
              <span class="text-muted-foreground">{{ log.method }} {{ log.path }}</span>
            </div>
            <div class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span v-if="log.resource_type">资源: {{ log.resource_type }}</span>
              <span v-if="log.resource_id">· ID: {{ log.resource_id }}</span>
              <span v-if="log.ip">· {{ log.ip }}</span>
              <span>· {{ formatTime(log.created_at) }}</span>
            </div>
          </div>

          <!-- 状态码 -->
          <Badge
            v-if="log.status_code"
            variant="secondary"
            :class="statusColor(log.status_code)"
            class="shrink-0 font-mono text-[10px]"
          >
            {{ log.status_code }}
          </Badge>

          <ChevronRight class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
        </CardContent>
      </Card>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="mt-4 flex justify-center">
      <Pagination
        :page="page"
        :page-size="pageSize"
        :total="total"
        @change="(p: number) => handlePageChange(p)"
      />
    </div>

    <!-- 详情对话框 -->
    <Dialog
      :open="detailOpen"
      title="审计日志详情"
      class="max-w-2xl"
      @update:open="(v: boolean) => (detailOpen = v)"
    >
      <div v-if="selectedLog" class="space-y-3 text-sm">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <span class="text-muted-foreground">操作类型</span>
            <p class="font-mono font-medium">{{ selectedLog.action }}</p>
          </div>
          <div>
            <span class="text-muted-foreground">状态码</span>
            <p>
              <Badge variant="secondary" :class="statusColor(selectedLog.status_code)" class="font-mono">
                {{ selectedLog.status_code || '-' }}
              </Badge>
            </p>
          </div>
          <div>
            <span class="text-muted-foreground">操作人</span>
            <p>{{ selectedLog.username || '匿名' }}<span v-if="selectedLog.user_id" class="text-xs text-muted-foreground"> ({{ selectedLog.user_id }})</span></p>
          </div>
          <div>
            <span class="text-muted-foreground">知识库</span>
            <p class="font-mono text-xs">{{ selectedLog.kb_id || '-' }}</p>
          </div>
          <div>
            <span class="text-muted-foreground">请求方法</span>
            <p class="font-mono">{{ selectedLog.method || '-' }}</p>
          </div>
          <div>
            <span class="text-muted-foreground">IP 地址</span>
            <p class="font-mono">{{ selectedLog.ip || '-' }}</p>
          </div>
        </div>
        <div>
          <span class="text-muted-foreground">请求路径</span>
          <p class="break-all font-mono text-xs">{{ selectedLog.path || '-' }}</p>
        </div>
        <div>
          <span class="text-muted-foreground">资源类型 / ID</span>
          <p class="font-mono text-xs">{{ selectedLog.resource_type || '-' }} / {{ selectedLog.resource_id || '-' }}</p>
        </div>
        <div>
          <span class="text-muted-foreground">User-Agent</span>
          <p class="break-all text-xs text-muted-foreground">{{ selectedLog.user_agent || '-' }}</p>
        </div>
        <div>
          <span class="text-muted-foreground">Trace ID</span>
          <p class="font-mono text-xs">{{ selectedLog.trace_id || '-' }}</p>
        </div>
        <div>
          <span class="text-muted-foreground">时间</span>
          <p>{{ formatTime(selectedLog.created_at) }}</p>
        </div>
        <div>
          <span class="text-muted-foreground">详情数据</span>
          <pre class="mt-1 max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs">{{ formatDetails(selectedLog.details) }}</pre>
        </div>
      </div>
    </Dialog>
  </div>
</template>
