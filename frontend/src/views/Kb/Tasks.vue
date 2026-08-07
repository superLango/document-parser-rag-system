<script setup lang="ts">
/**
 * 知识库任务监控
 *
 * 功能：任务列表/统计概览/状态过滤/类型过滤/重试/取消/删除
 * 数据隔离：/kbs/{kb_id}/tasks，后端 RLS 强制
 * 权限：viewer 可查看；editor+ 可重试/取消/删除
 */
import { ref, onMounted, computed, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import {
  ListChecks,
  RefreshCw,
  Loader2,
  XCircle,
  CheckCircle2,
  Clock,
  AlertCircle,
  RotateCcw,
  Ban,
  Activity,
  Trash2,
  FileText,
  Wand2,
  Network,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { useBatchSelection } from '@/composables/useBatchSelection'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

import { Skeleton } from '@/components/ui/skeleton'
import { Select } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import BatchActionbar from '@/components/common/BatchActionbar.vue'
import type { Task } from '@/api/types'
import { confirm } from '@/composables/useConfirm'

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
const taskTypeFilter = ref('')
const batchLoading = ref(false)

const sel = useBatchSelection<any>({ idKey: 'id' })
const visibleIds = computed(() => tasks.value.map((t) => t.id))

const stats = ref<{
  total: number
  by_status: Record<string, number>
  by_type: Record<string, number>
  success_count: number
  failed_count: number
  success_rate: number
} | null>(null)

let refreshTimer: ReturnType<typeof setInterval> | null = null

const statusConfig: Record<string, { label: string; color: string; icon: typeof Clock; glow: string }> = {
  pending: { label: '等待中', color: 'bg-muted text-muted-foreground border-border', icon: Clock, glow: 'shadow-muted-foreground/20' },
  queued: { label: '排队中', color: 'bg-muted text-muted-foreground border-border', icon: Clock, glow: 'shadow-muted-foreground/20' },
  started: { label: '处理中', color: 'bg-info/15 text-info border-info/30 dark:bg-info/20 dark:border-info/30', icon: Loader2, glow: 'shadow-info/30' },
  running: { label: '处理中', color: 'bg-info/15 text-info border-info/30 dark:bg-info/20 dark:border-info/30', icon: Loader2, glow: 'shadow-info/30' },
  progress: { label: '处理中', color: 'bg-info/15 text-info border-info/30 dark:bg-info/20 dark:border-info/30', icon: Activity, glow: 'shadow-info/30' },
  success: { label: '成功', color: 'bg-success/15 text-success border-success/30 dark:bg-success/20 dark:border-success/30', icon: CheckCircle2, glow: 'shadow-success/30' },
  completed: { label: '成功', color: 'bg-success/15 text-success border-success/30 dark:bg-success/20 dark:border-success/30', icon: CheckCircle2, glow: 'shadow-success/30' },
  failed: { label: '失败', color: 'bg-danger/15 text-danger border-danger/30 dark:bg-danger/20 dark:border-danger/30', icon: XCircle, glow: 'shadow-danger/30' },
}

function getStatusInfo(status: string) {
  return statusConfig[status] || { label: status, color: 'bg-muted text-muted-foreground border-border', icon: AlertCircle, glow: 'shadow-muted-foreground/20' }
}

const taskTypeConfig: Record<string, { label: string; icon: typeof FileText; color: string }> = {
  parse_document: { label: 'OCR解析', icon: FileText, color: 'bg-primary/10 text-primary border-primary/20 dark:bg-primary/15 dark:border-primary/30' },
  parse: { label: 'OCR解析', icon: FileText, color: 'bg-primary/10 text-primary border-primary/20 dark:bg-primary/15 dark:border-primary/30' },
  extract_document: { label: '结构化抽取', icon: Wand2, color: 'bg-warning/10 text-warning border-warning/20 dark:bg-warning/15 dark:border-warning/30' },
  extraction: { label: '结构化抽取', icon: Wand2, color: 'bg-warning/10 text-warning border-warning/20 dark:bg-warning/15 dark:border-warning/30' },
  build_index_graph: { label: '索引图谱构建', icon: Network, color: 'bg-success/10 text-success border-success/20 dark:bg-success/15 dark:border-success/30' },
}

function getTaskTypeInfo(taskType: string) {
  return taskTypeConfig[taskType] || { label: taskType, icon: Activity, color: 'bg-muted text-muted-foreground border-border' }
}

async function fetchTasks() {
  loading.value = true
  try {
    const res = await kbApi.listTasks(kbId.value, {
      page: page.value,
      page_size: pageSize.value,
      status: statusFilter.value || undefined,
      task_type: taskTypeFilter.value || undefined,
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
  if (!await confirm(`确定取消任务「${task.id.slice(0, 8)}」？取消后任务将标记为失败。`)) return
  try {
    await kbApi.cancelTask(kbId.value, task.id)
    toast.success('任务已取消')
    await refreshAll()
  } catch {
    // 错误已由拦截器提示
  }
}

async function deleteTask(task: Task) {
  if (!await confirm(`确定删除任务「${task.id.slice(0, 8)}」？此操作不可恢复。`)) return
  try {
    await kbApi.deleteTask(kbId.value, task.id)
    toast.success('任务已删除')
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

function isTaskCancellable(status: string) {
  return ['pending', 'queued', 'running', 'started', 'progress'].includes(status)
}

function isTaskRetryable(status: string) {
  return ['success', 'failed', 'completed'].includes(status)
}

function isTaskDeletable(status: string) {
  return ['success', 'failed', 'completed'].includes(status)
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

const hasRunningTasks = computed(() =>
  tasks.value.some((t) => ['pending', 'queued', 'running', 'started', 'progress'].includes(t.status)),
)

onMounted(() => {
  refreshAll()
  refreshTimer = setInterval(() => {
    if (hasRunningTasks.value) {
      refreshAll()
    }
  }, 5000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="tasks-page">
    <PageHeader title="任务监控" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" class="premium-btn-outline" @click="refreshAll">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div v-if="stats" class="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
      <Card class="stat-card group stat-card-total">
        <CardContent class="p-4">
          <div class="flex items-center gap-2">
            <div class="stat-icon-bg bg-muted">
              <ListChecks class="size-4 text-muted-foreground" :stroke-width="1.5" />
            </div>
            <p class="text-xs font-medium text-muted-foreground uppercase tracking-wider">总任务</p>
          </div>
          <p class="mt-3 text-3xl font-bold text-foreground tabular-nums">{{ stats.total }}</p>
        </CardContent>
      </Card>
      <Card class="stat-card group stat-card-success">
        <CardContent class="p-4">
          <div class="flex items-center gap-2">
            <div class="stat-icon-bg bg-success/10 dark:bg-success/15">
              <CheckCircle2 class="size-4 text-success" :stroke-width="1.5" />
            </div>
            <p class="text-xs font-medium text-muted-foreground uppercase tracking-wider">成功</p>
          </div>
          <p class="mt-3 text-3xl font-bold text-success tabular-nums">{{ stats.success_count }}</p>
        </CardContent>
      </Card>
      <Card class="stat-card group stat-card-failed">
        <CardContent class="p-4">
          <div class="flex items-center gap-2">
            <div class="stat-icon-bg bg-danger/10 dark:bg-danger/15">
              <XCircle class="size-4 text-danger" :stroke-width="1.5" />
            </div>
            <p class="text-xs font-medium text-muted-foreground uppercase tracking-wider">失败</p>
          </div>
          <p class="mt-3 text-3xl font-bold text-danger tabular-nums">{{ stats.failed_count }}</p>
        </CardContent>
      </Card>
      <Card class="stat-card group stat-card-rate">
        <CardContent class="p-4">
          <div class="flex items-center gap-2">
            <div class="stat-icon-bg bg-info/10 dark:bg-info/15">
              <Activity class="size-4 text-info" :stroke-width="1.5" />
            </div>
            <p class="text-xs font-medium text-muted-foreground uppercase tracking-wider">成功率</p>
          </div>
          <p class="mt-3 text-3xl font-bold text-info tabular-nums">{{ stats.success_rate }}%</p>
        </CardContent>
      </Card>
      <Card class="stat-card group stat-card-types col-span-2 md:col-span-1">
        <CardContent class="p-4">
          <div class="flex items-center gap-2">
            <div class="stat-icon-bg bg-primary/10 dark:bg-primary/15">
              <Network class="size-4 text-primary" :stroke-width="1.5" />
            </div>
            <p class="text-xs font-medium text-muted-foreground uppercase tracking-wider">任务类型</p>
          </div>
          <div class="mt-3 flex flex-wrap gap-1.5">
            <Badge
              v-for="(count, type) in stats.by_type"
              :key="type"
              variant="secondary"
              class="type-badge text-[10px] font-medium border"
              :class="getTaskTypeInfo(type).color"
            >
              {{ getTaskTypeInfo(type).label }}: {{ count }}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 过滤器 -->
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <Select
        :model-value="statusFilter"
        :options="[
          { value: '', label: '全部状态' },
          { value: 'pending', label: '等待中' },
          { value: 'running', label: '处理中' },
          { value: 'success', label: '成功' },
          { value: 'failed', label: '失败' },
        ]"
        class="w-40 premium-select"
        @update:model-value="(v: string) => { statusFilter = v; page = 1; fetchTasks() }"
      />
      <Select
        :model-value="taskTypeFilter"
        :options="[
          { value: '', label: '全部类型' },
          { value: 'parse_document', label: 'OCR解析' },
          { value: 'extract_document', label: '结构化抽取' },
          { value: 'build_index_graph', label: '索引图谱构建' },
        ]"
        class="w-44 premium-select"
        @update:model-value="(v: string) => { taskTypeFilter = v; page = 1; fetchTasks() }"
      />
    </div>

    <!-- 批量操作栏 -->
    <BatchActionbar
      v-if="isEditor"
      :selected-count="sel.selectedCount.value"
      :loading="batchLoading"
      @clear="sel.clear"
    >
      <Button variant="outline" size="sm" class="premium-btn-outline" :disabled="batchLoading" @click="handleBatchRetry">
        <RotateCcw class="size-4" :stroke-width="1.5" />
        批量重试
      </Button>
    </BatchActionbar>

    <!-- 任务列表 -->
    <div v-if="loading" class="space-y-3">
      <Skeleton v-for="i in 5" :key="i" class="h-24 w-full premium-skeleton" />
    </div>

    <EmptyState
      v-else-if="tasks.length === 0"
      :icon="ListChecks"
      title="暂无任务"
      description="上传文档并发起解析后，任务将在此显示"
      class="py-16"
    />

    <div v-else class="space-y-3">
      <!-- 表头（含全选） -->
      <div v-if="isEditor && tasks.length > 0" class="flex items-center gap-3 px-4 py-2 text-xs text-muted-foreground">
        <Checkbox
          :model-value="sel.isAllSelected(visibleIds)"
          :indeterminate="sel.isIndeterminate(visibleIds)"
          class="premium-checkbox"
          @update:model-value="(v: boolean) => sel.selectAll(visibleIds, v)"
        />
        <span class="font-medium">全选当前页（已选 {{ sel.selectedCount.value }}）</span>
      </div>

      <Card v-for="task in tasks" :key="task.id" class="task-card group">
        <CardContent class="p-4">
          <div class="flex items-start gap-4">
            <Checkbox
              v-if="isEditor && isTaskRetryable(task.status)"
              :model-value="sel.isSelected(task.id)"
              class="mt-1 premium-checkbox"
              @update:model-value="(v: boolean) => sel.setSelected(task.id, v)"
            />
            <div
              class="status-icon-wrapper flex size-11 shrink-0 items-center justify-center rounded-xl border transition-all duration-300"
              :class="[getStatusInfo(task.status).color, getStatusInfo(task.status).glow]"
            >
              <component
                :is="getStatusInfo(task.status).icon"
                class="size-5"
                :class="{ 'animate-spin-slow': ['running', 'started', 'progress'].includes(task.status) }"
                :stroke-width="1.5"
              />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <Badge variant="outline" class="task-id-badge font-mono text-[10px] font-semibold">
                  {{ task.id.slice(0, 8) }}
                </Badge>
                <Badge variant="secondary" class="type-badge gap-1.5 text-[10px] font-medium border" :class="getTaskTypeInfo(task.task_type).color">
                  <component :is="getTaskTypeInfo(task.task_type).icon" class="size-3" :stroke-width="1.5" />
                  {{ getTaskTypeInfo(task.task_type).label }}
                </Badge>
                <Badge variant="secondary" class="status-badge gap-1.5 text-[10px] font-semibold border" :class="getStatusInfo(task.status).color">
                  {{ getStatusInfo(task.status).label }}
                </Badge>
                <span v-if="task.retry_count" class="flex items-center gap-1 rounded-md bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning border border-warning/20 dark:bg-warning/15">
                  <RotateCcw class="size-3" :stroke-width="1.5" />
                  重试 {{ task.retry_count }} 次
                </span>
              </div>
              <p class="mt-2 text-xs text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="flex items-center gap-1">
                  <FileText class="size-3 text-muted-foreground/70" :stroke-width="1.5" />
                  文档: <span class="font-mono text-foreground">{{ task.document_id?.slice(0, 8) || '-' }}</span>
                </span>
                <span class="text-border">•</span>
                <span class="flex items-center gap-1">
                  <Clock class="size-3 text-muted-foreground/70" :stroke-width="1.5" />
                  创建 {{ formatTime(task.created_at) }}
                </span>
                <span class="text-border">•</span>
                <span class="flex items-center gap-1">
                  <Activity class="size-3 text-muted-foreground/70" :stroke-width="1.5" />
                  耗时 <span class="text-foreground font-medium">{{ duration(task.started_at, task.completed_at) }}</span>
                </span>
              </p>
              <!-- 进度条 -->
              <div v-if="['running', 'started', 'progress'].includes(task.status)" class="mt-3 progress-wrapper">
                <div class="progress-bar-container">
                  <div class="progress-bar-bg">
                    <div 
                      class="progress-bar-fill"
                      :style="{ width: `${task.progress || 0}%` }"
                    ></div>
                  </div>
                  <span class="progress-text">{{ task.progress || 0 }}%</span>
                </div>
              </div>
              <!-- 错误信息 -->
              <div v-if="task.error_message" class="mt-2 error-message">
                <AlertCircle class="size-3.5 shrink-0" :stroke-width="1.5" />
                <span class="text-xs leading-relaxed">{{ task.error_message }}</span>
              </div>
            </div>
            <div v-if="isEditor" class="flex shrink-0 items-center gap-1 task-actions">
              <Button
                v-if="isTaskRetryable(task.status)"
                variant="ghost"
                size="sm"
                class="action-btn action-btn-retry"
                title="重试"
                @click="retryTask(task)"
              >
                <RotateCcw class="size-4" :stroke-width="1.5" />
              </Button>
              <Button
                v-if="isTaskCancellable(task.status)"
                variant="ghost"
                size="sm"
                class="action-btn action-btn-cancel"
                title="取消"
                @click="cancelTask(task)"
              >
                <Ban class="size-4" :stroke-width="1.5" />
              </Button>
              <Button
                v-if="isTaskDeletable(task.status)"
                variant="ghost"
                size="sm"
                class="action-btn action-btn-delete"
                title="删除"
                @click="deleteTask(task)"
              >
                <Trash2 class="size-4" :stroke-width="1.5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="mt-6 flex justify-center">
      <Pagination :page="page" :page-size="pageSize" :total="total" @change="(p: number) => handlePageChange(p)" />
    </div>
  </div>
</template>

<style scoped>
@reference "../../styles/globals.css";

.tasks-page {
  position: relative;
}

.tasks-page :deep(.premium-btn-outline) {
  @apply border-border bg-muted/50 text-muted-foreground hover:bg-accent hover:text-foreground transition-all duration-300;
  backdrop-filter: blur(8px);
}

.tasks-page :deep(.premium-select) {
  @apply border-border bg-muted/50 text-foreground;
}

.tasks-page :deep(.premium-checkbox) {
  @apply border-border data-[state=checked]:bg-primary data-[state=checked]:border-primary;
}

.tasks-page :deep(.premium-skeleton) {
  @apply bg-muted border border-border/50;
}

.stat-card {
  @apply relative overflow-hidden border-border bg-card backdrop-blur-sm;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--color-border), transparent);
  opacity: 0;
  transition: opacity 0.4s ease;
}

.stat-card:hover {
  transform: translateY(-4px);
  @apply border-border/80;
  box-shadow: var(--shadow-lg);
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-icon-bg {
  @apply flex size-8 items-center justify-center rounded-lg;
  transition: all 0.3s ease;
}

.stat-card:hover .stat-icon-bg {
  transform: scale(1.1);
}

.stat-card-total:hover {
  box-shadow: var(--shadow-lg), 0 0 30px -10px color-mix(in oklch, var(--color-muted-foreground) 20%, transparent);
}

.stat-card-success:hover {
  border-color: color-mix(in oklch, var(--color-success) 30%, transparent);
  box-shadow: var(--shadow-lg), 0 0 30px -10px color-mix(in oklch, var(--color-success) 25%, transparent);
}

.stat-card-failed:hover {
  border-color: color-mix(in oklch, var(--color-danger) 30%, transparent);
  box-shadow: var(--shadow-lg), 0 0 30px -10px color-mix(in oklch, var(--color-danger) 25%, transparent);
}

.stat-card-rate:hover {
  border-color: color-mix(in oklch, var(--color-info) 30%, transparent);
  box-shadow: var(--shadow-lg), 0 0 30px -10px color-mix(in oklch, var(--color-info) 25%, transparent);
}

.stat-card-types:hover {
  border-color: color-mix(in oklch, var(--color-primary) 30%, transparent);
  box-shadow: var(--shadow-lg), 0 0 30px -10px color-mix(in oklch, var(--color-primary) 25%, transparent);
}

.type-badge {
  @apply font-medium;
  transition: all 0.2s ease;
}

.type-badge:hover {
  transform: scale(1.02);
}

.status-badge {
  @apply font-semibold;
  animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.85; }
}

.task-card {
  @apply relative overflow-hidden border-border bg-card backdrop-blur-sm;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, transparent, color-mix(in oklch, var(--color-primary) 40%, transparent), transparent);
  opacity: 0;
  transition: all 0.35s ease;
}

.task-card:hover {
  transform: translateX(4px);
  @apply border-border/80;
  box-shadow: var(--shadow-md);
}

.task-card:hover::before {
  opacity: 1;
}

.task-card:hover .status-icon-wrapper {
  transform: scale(1.08);
}

.task-id-badge {
  letter-spacing: 0.5px;
}

.status-icon-wrapper {
  box-shadow: 0 0 0 0 transparent;
}

.task-card:hover .status-icon-wrapper {
  box-shadow: 0 0 20px -5px currentColor;
}

.progress-wrapper {
  position: relative;
}

.progress-bar-container {
  @apply flex items-center gap-3;
}

.progress-bar-bg {
  @apply relative h-2 flex-1 overflow-hidden rounded-full bg-muted;
  box-shadow: inset 0 1px 3px color-mix(in oklch, var(--color-foreground) 10%, transparent);
}

.progress-bar-fill {
  @apply absolute left-0 top-0 h-full rounded-full;
  background: linear-gradient(90deg, var(--color-info), var(--color-primary), var(--color-info));
  background-size: 200% 100%;
  animation: progress-shimmer 2s linear infinite, progress-pulse 1.5s ease-in-out infinite;
  box-shadow: 0 0 10px color-mix(in oklch, var(--color-info) 50%, transparent);
  transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes progress-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@keyframes progress-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.85; }
}

.progress-text {
  @apply min-w-[40px] text-right text-[11px] font-bold tabular-nums text-info;
  text-shadow: 0 0 10px color-mix(in oklch, var(--color-info) 30%, transparent);
}

.error-message {
  @apply flex items-start gap-2 rounded-lg border border-danger/20 bg-danger/10 px-3 py-2 text-danger dark:bg-danger/15;
  animation: error-slide-in 0.3s ease-out;
}

@keyframes error-slide-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.task-actions {
  opacity: 0.6;
  transition: opacity 0.2s ease;
}

.task-card:hover .task-actions {
  opacity: 1;
}

.action-btn {
  @apply size-9 rounded-lg border border-transparent p-0 transition-all duration-200;
}

.action-btn-retry {
  @apply text-muted-foreground hover:bg-info/10 hover:text-info hover:border-info/20;
}

.action-btn-cancel {
  @apply text-muted-foreground hover:bg-warning/10 hover:text-warning hover:border-warning/20;
}

.action-btn-delete {
  @apply text-muted-foreground hover:bg-danger/10 hover:text-danger hover:border-danger/20;
}

.action-btn:hover {
  transform: scale(1.1);
}

.action-btn:active {
  transform: scale(0.95);
}

.animate-spin-slow {
  animation: spin 1.5s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .stat-card {
    @apply p-3;
  }
  
  .task-card :deep(.card-content) {
    @apply p-3;
  }
  
  .task-actions {
    opacity: 1;
  }
}
</style>
