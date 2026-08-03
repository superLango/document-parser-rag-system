<script setup lang="ts">
/**
 * 知识库任务监控
 *
 * 功能：任务列表/统计概览/状态过滤/重试/取消
 * 数据隔离：/kbs/{kb_id}/tasks，后端 RLS 强制
 * 权限：viewer 可查看；editor+ 可重试/取消
 */
import { ref, onMounted, computed, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import {
  ListChecks,
  RefreshCw,
  Loader2,
  Play,
  XCircle,
  CheckCircle2,
  Clock,
  AlertCircle,
  RotateCcw,
  Ban,
  Activity,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { useBatchSelection } from '@/composables/useBatchSelection'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Select } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import BatchActionbar from '@/components/common/BatchActionbar.vue'
import type { Task } from '@/api/types'

const route = useRoute()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const loading = ref(true)
const tasks = ref<Task[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('')
const batchLoading = ref(false)

// 批量选择
const sel = useBatchSelection<Task>({ idKey: 'id' })
const visibleIds = computed(() => tasks.value.map((t) => t.id))

// 统计
const stats = ref<{
  total: number
  by_status: Record<string, number>
  by_type: Record<string, number>
  success_count: number
  failed_count: number
  success_rate: number
} | null>(null)

// 自动刷新
let refreshTimer: ReturnType<typeof setInterval> | null = null

const statusConfig: Record<string, { label: string; color: string; icon: typeof Clock }> = {
  pending: { label: '等待中', color: 'bg-muted text-muted-foreground', icon: Clock },
  queued: { label: '排队中', color: 'bg-muted text-muted-foreground', icon: Clock },
  started: { label: '处理中', color: 'bg-info/10 text-info', icon: Loader2 },
  running: { label: '处理中', color: 'bg-info/10 text-info', icon: Loader2 },
  progress: { label: '处理中', color: 'bg-info/10 text-info', icon: Activity },
  success: { label: '成功', color: 'bg-success/10 text-success', icon: CheckCircle2 },
  completed: { label: '成功', color: 'bg-success/10 text-success', icon: CheckCircle2 },
  failed: { label: '失败', color: 'bg-danger/10 text-danger', icon: XCircle },
}

function getStatusInfo(status: string) {
  return statusConfig[status] || { label: status, color: 'bg-muted text-muted-foreground', icon: AlertCircle }
}

const taskTypeLabel: Record<string, string> = {
  parse: 'OCR 解析',
  extraction: '结构化抽取',
  graph: '图谱构建',
  embedding: '向量化',
}

async function fetchTasks() {
  loading.value = true
  try {
    const res = await kbApi.listTasks(kbId.value, {
      page: page.value,
      page_size: pageSize.value,
      status: statusFilter.value || undefined,
    })
    tasks.value = res.items
    total.value = res.total
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    stats.value = await kbApi.taskStats(kbId.value)
  } catch {
    stats.value = null
  }
}

async function refreshAll() {
  await Promise.all([fetchTasks(), fetchStats()])
}

async function retryTask(task: Task) {
  try {
    await kbApi.retryTask(kbId.value, task.id)
    toast.success('重试已提交', task.id.slice(0, 8))
    await refreshAll()
  } catch {
    // 错误已由拦截器提示
  }
}

async function cancelTask(task: Task) {
  if (!confirm(`确定取消任务「${task.id.slice(0, 8)}」？`)) return
  try {
    await kbApi.cancelTask(kbId.value, task.id)
    toast.success('任务已取消')
    await refreshAll()
  } catch {
    // 错误已由拦截器提示
  }
}

async function handleBatchRetry() {
  const ids = sel.getSelectedIds()
  if (ids.length === 0) return
  batchLoading.value = true
  try {
    const res = await kbApi.batchRetryTasks(kbId.value, ids)
    toast.success('批量重试已提交', `成功 ${res.success} 个，失败 ${res.failed} 个`)
    sel.clear()
    await refreshAll()
  } catch {
    // 错误已由拦截器提示
  } finally {
    batchLoading.value = false
  }
}

function handlePageChange(p: number) {
  page.value = p
  fetchTasks()
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

function duration(start: string | null, end: string | null): string {
  if (!start) return '-'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const sec = Math.round((e - s) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m${sec % 60}s`
  return `${Math.floor(sec / 3600)}h${Math.floor((sec % 3600) / 60)}m`
}

onMounted(() => {
  refreshAll()
  // 有进行中任务时自动刷新
  refreshTimer = setInterval(refreshAll, 5000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div>
    <PageHeader title="任务监控" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="refreshAll">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div v-if="stats" class="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
      <Card>
        <CardContent class="p-3">
          <p class="text-xs text-muted-foreground">总任务</p>
          <p class="mt-1 text-2xl font-semibold text-foreground">{{ stats.total }}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="p-3">
          <p class="text-xs text-muted-foreground">成功</p>
          <p class="mt-1 text-2xl font-semibold text-success">{{ stats.success_count }}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="p-3">
          <p class="text-xs text-muted-foreground">失败</p>
          <p class="mt-1 text-2xl font-semibold text-danger">{{ stats.failed_count }}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="p-3">
          <p class="text-xs text-muted-foreground">成功率</p>
          <p class="mt-1 text-2xl font-semibold text-primary">{{ stats.success_rate }}%</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="p-3">
          <p class="text-xs text-muted-foreground">任务类型</p>
          <div class="mt-1 flex flex-wrap gap-1">
            <Badge
              v-for="(count, type) in stats.by_type"
              :key="type"
              variant="secondary"
              class="text-[10px]"
            >
              {{ taskTypeLabel[type] || type }}: {{ count }}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 状态过滤 -->
    <div class="mb-4 flex items-center gap-2">
      <Select
        :model-value="statusFilter"
        :options="[
          { value: '', label: '全部状态' },
          { value: 'pending', label: '等待中' },
          { value: 'running', label: '处理中' },
          { value: 'success', label: '成功' },
          { value: 'failed', label: '失败' },
        ]"
        class="w-36"
        @update:model-value="(v: string) => { statusFilter = v; page = 1; fetchTasks() }"
      />
    </div>

    <!-- 批量操作栏 -->
    <BatchActionbar
      v-if="isEditor"
      :selected-count="sel.selectedCount.value"
      :loading="batchLoading"
      @clear="sel.clear"
    >
      <Button variant="outline" size="sm" :disabled="batchLoading" @click="handleBatchRetry">
        <RotateCcw class="size-4" :stroke-width="1.5" />
        批量重试
      </Button>
    </BatchActionbar>

    <!-- 任务列表 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 5" :key="i" class="h-20 w-full" />
    </div>

    <EmptyState
      v-else-if="tasks.length === 0"
      :icon="ListChecks"
      title="暂无任务"
      description="上传文档并发起解析后，任务将在此显示"
      class="py-12"
    />

    <div v-else class="space-y-2">
      <!-- 表头（含全选，仅失败状态可批量重试） -->
      <div v-if="isEditor && tasks.length > 0" class="flex items-center gap-3 px-3 py-1 text-xs text-muted-foreground">
        <Checkbox
          :model-value="sel.isAllSelected(visibleIds)"
          :indeterminate="sel.isIndeterminate(visibleIds)"
          @update:checked="(v) => sel.selectAll(visibleIds, v === true)"
        />
        <span>全选当前页（已选 {{ sel.selectedCount.value }}）</span>
      </div>

      <Card v-for="task in tasks" :key="task.id">
        <CardContent class="p-3">
          <div class="flex items-start gap-3">
            <Checkbox
              v-if="isEditor"
              :model-value="sel.isSelected(task.id)"
              class="mt-1"
              @update:checked="(v) => sel.setSelected(task.id, v === true)"
            />
            <div class="flex size-9 shrink-0 items-center justify-center rounded-md" :class="getStatusInfo(task.status).color">
              <component :is="getStatusInfo(task.status).icon" class="size-4" :class="{ 'animate-spin': task.status === 'running' || task.status === 'started' }" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <Badge variant="outline" class="font-mono text-[10px]">{{ task.id.slice(0, 8) }}</Badge>
                <Badge variant="secondary" class="text-[10px]">{{ taskTypeLabel[task.task_type] || task.task_type }}</Badge>
                <Badge variant="secondary" :class="getStatusInfo(task.status).color" class="text-[10px]">
                  {{ getStatusInfo(task.status).label }}
                </Badge>
                <span v-if="task.retry_count" class="text-xs text-muted-foreground">重试 {{ task.retry_count }} 次</span>
              </div>
              <p class="mt-1 text-xs text-muted-foreground">
                文档: <span class="font-mono">{{ task.document_id.slice(0, 8) }}</span>
                · 创建 {{ formatTime(task.created_at) }}
                · 耗时 {{ duration(task.started_at, task.completed_at) }}
              </p>
              <!-- 进度条 -->
              <div v-if="task.status === 'running' || task.status === 'started'" class="mt-2">
                <Progress :model-value="task.progress || 0" class="h-1.5" />
                <p class="mt-0.5 text-[10px] text-muted-foreground">{{ task.progress || 0 }}%</p>
              </div>
              <!-- 错误信息 -->
              <p v-if="task.error_message" class="mt-1 rounded bg-danger/5 px-2 py-1 text-xs text-danger">
                {{ task.error_message }}
              </p>
            </div>
            <div v-if="isEditor" class="flex shrink-0 items-center gap-1">
              <Button
                v-if="task.status === 'failed'"
                variant="ghost"
                size="sm"
                title="重试"
                @click="retryTask(task)"
              >
                <RotateCcw class="size-4" :stroke-width="1.5" />
              </Button>
              <Button
                v-if="['pending', 'queued', 'running', 'started', 'progress'].includes(task.status)"
                variant="ghost"
                size="sm"
                title="取消"
                @click="cancelTask(task)"
              >
                <Ban class="size-4 text-danger" :stroke-width="1.5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="mt-4 flex justify-center">
      <Pagination :page="page" :page-size="pageSize" :total="total" @change="(p: number) => handlePageChange(p)" />
    </div>
  </div>
</template>
