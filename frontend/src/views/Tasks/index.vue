<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { RefreshCw, Eye, RotateCcw, ListChecks, AlertTriangle } from 'lucide-vue-next'
import { taskApi } from '@/api/modules/task'
import type { Task } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/ui/status-badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { Tooltip } from '@/components/ui/tooltip'
import { Dialog } from '@/components/ui/dialog'

const router = useRouter()

// ---------- 任务列表 ----------
const tasks = ref<Task[]>([])
const total = ref(0)
const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)

// ---------- 状态筛选选项（与 TaskStatus 类型对齐） ----------
// 注意：reka-ui 的 SelectItem 不允许空字符串作为 value，使用 'all' 表示全部
const ALL_VALUE = 'all'
const statusOptions = [
  { value: ALL_VALUE, label: '全部状态' },
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'success', label: '已完成' },
  { value: 'failed', label: '已失败' },
]

const statusSelectOptions = statusOptions.map((o) => ({ value: o.value, label: o.label }))

// 当前筛选值（'all' 表示全部，对外映射为 undefined）
const filterStatusValue = ref(ALL_VALUE)

// ---------- 时间格式化 ----------
function formatTime(iso: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

// ---------- ID 截断显示 ----------
function truncateId(id: string): string {
  return id ? id.slice(0, 8) : '-'
}

// ---------- 进度颜色 ----------
function progressIndicatorClass(status: string): string {
  if (status === 'failed') return 'bg-danger'
  if (status === 'success') return 'bg-success'
  if (status === 'running' || status === 'queued') return 'bg-primary'
  return 'bg-muted-foreground'
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await taskApi.getList({
      status: filterStatus.value || undefined,
      page: currentPage.value,
      page_size: pageSize.value,
    })
    tasks.value = res.items
    total.value = res.total
  } catch {
    tasks.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ---------- 查看任务：跳转 Parser 页面 ----------
function handleView(row: Task) {
  router.push({ name: 'Parser', params: { id: row.document_id }, query: { task_id: row.id } })
}

// ---------- 重试失败任务（带确认对话框） ----------
const retryDialogVisible = ref(false)
const retryTarget = ref<Task | null>(null)
const retrying = ref(false)

function openRetryDialog(task: Task) {
  retryTarget.value = task
  retryDialogVisible.value = true
}

async function confirmRetry() {
  if (!retryTarget.value) return
  retrying.value = true
  try {
    const res = await taskApi.retry(retryTarget.value.id)
    toast.success('任务已重新提交', `新任务 ID: ${res.task_id.slice(0, 8)}…`)
    retryDialogVisible.value = false
    await loadTasks()
  } catch {
    // 错误已由拦截器处理
  } finally {
    retrying.value = false
  }
}

function onPageChange(page: number) {
  currentPage.value = page
  loadTasks()
}

function handleFilterChange() {
  currentPage.value = 1
  loadTasks()
}

onMounted(() => {
  loadTasks()
})
</script>

<template>
  <div>
    <PageHeader
      title="任务管理"
      description="查看与管理文档解析任务，支持重试失败任务"
    />

    <!-- 筛选栏 -->
    <Card class="mb-4">
      <CardContent class="flex flex-wrap items-center gap-3 p-3">
        <div class="flex items-center gap-2">
          <span class="text-xs font-medium text-muted-foreground">状态</span>
          <Select
            v-model="filterStatusValue"
            :options="statusSelectOptions"
            placeholder="全部状态"
            class="h-8 w-40"
            @update:model-value="handleFilterChange"
          />
        </div>
        <div class="flex-1" />
        <Button
          variant="outline"
          size="sm"
          class="h-8 gap-1.5"
          :disabled="loading"
          @click="loadTasks"
        >
          <RefreshCw
            class="size-3.5"
            :stroke-width="1.5"
            :class="loading ? 'animate-spin' : ''"
          />
          刷新
        </Button>
      </CardContent>
    </Card>

    <!-- 任务表格 -->
    <Card>
      <CardContent class="p-0">
        <!-- 表头 -->
        <div class="hidden grid-cols-12 gap-3 border-b border-border bg-muted/40 px-5 py-2.5 text-xs font-medium text-muted-foreground lg:grid">
          <div class="col-span-2">任务 ID</div>
          <div class="col-span-2">文档 ID</div>
          <div class="col-span-2">状态</div>
          <div class="col-span-2">进度</div>
          <div class="col-span-2">创建时间</div>
          <div class="col-span-1">完成时间</div>
          <div class="col-span-1 text-right">操作</div>
        </div>

        <!-- 加载态 -->
        <div v-if="loading" class="divide-y divide-border">
          <div v-for="i in 6" :key="i" class="px-5 py-3.5">
            <Skeleton class="h-9 w-full" />
          </div>
        </div>

        <!-- 空态 -->
        <EmptyState
          v-else-if="tasks.length === 0"
          :icon="ListChecks"
          title="暂无任务"
          :description="filterStatusValue !== ALL_VALUE ? '当前筛选条件下没有任务' : '提交文档解析后将在此显示任务'"
          class="py-12"
        />

        <!-- 列表 -->
        <ul v-else class="divide-y divide-border">
          <li
            v-for="task in tasks"
            :key="task.id"
            class="grid grid-cols-1 gap-3 px-5 py-3 transition-colors hover:bg-muted/30 lg:grid-cols-12 lg:items-center"
          >
            <!-- 任务 ID -->
            <div class="lg:col-span-2">
              <span class="font-mono text-xs text-foreground">{{ truncateId(task.id) }}</span>
              <div class="text-[10px] text-muted-foreground">{{ task.task_type }}</div>
            </div>

            <!-- 文档 ID -->
            <div class="lg:col-span-2">
              <button
                type="button"
                class="font-mono text-xs text-foreground transition-colors hover:text-primary"
                @click="router.push(`/parser/${task.document_id}`)"
              >
                {{ truncateId(task.document_id) }}
              </button>
            </div>

            <!-- 状态 -->
            <div class="lg:col-span-2">
              <StatusBadge :status="task.status" kind="task" />
            </div>

            <!-- 进度 -->
            <div class="lg:col-span-2">
              <div class="flex items-center gap-2">
                <Progress
                  :value="task.progress"
                  :indicator-class="progressIndicatorClass(task.status)"
                  class="h-1.5"
                />
                <span class="font-mono text-[10px] text-muted-foreground tabular-nums">
                  {{ task.progress }}%
                </span>
              </div>
            </div>

            <!-- 创建时间 -->
            <div class="text-xs text-muted-foreground lg:col-span-2">
              {{ formatTime(task.created_at) }}
            </div>

            <!-- 完成时间 -->
            <div class="text-xs text-muted-foreground lg:col-span-1">
              {{ formatTime(task.completed_at) }}
            </div>

            <!-- 操作 -->
            <div class="flex justify-end gap-1 lg:col-span-1">
              <Tooltip :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="查看"
                    @click="handleView(task)"
                  >
                    <Eye class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>查看文档</span>
              </Tooltip>

              <Tooltip v-if="task.status === 'failed'" :side="'top'">
                <template #trigger>
                  <button
                    type="button"
                    class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-warning/10 hover:text-warning"
                    aria-label="重试"
                    @click="openRetryDialog(task)"
                  >
                    <RotateCcw class="size-3.5" :stroke-width="1.5" />
                  </button>
                </template>
                <span>重试任务</span>
              </Tooltip>
            </div>
          </li>
        </ul>

        <!-- 分页 -->
        <div class="flex items-center justify-end border-t border-border px-5 py-3">
          <Pagination
            :page="currentPage"
            :page-size="pageSize"
            :total="total"
            @update:page="onPageChange"
          />
        </div>
      </CardContent>
    </Card>

    <!-- 重试确认对话框 -->
    <Dialog
      :open="retryDialogVisible"
      title="重试任务确认"
      description="将基于失败任务的原始参数重新提交一次解析"
      @update:open="(v) => (retryDialogVisible = v)"
    >
      <div v-if="retryTarget" class="space-y-3">
        <div class="flex items-start gap-3 rounded-md border border-warning/30 bg-warning/5 p-3">
          <AlertTriangle class="mt-0.5 size-4 shrink-0 text-warning" :stroke-width="1.5" />
          <div class="flex-1 space-y-1 text-sm">
            <p class="text-foreground">
              即将重试任务
              <span class="font-mono text-xs font-medium">{{ retryTarget.id.slice(0, 8) }}…</span>
            </p>
            <p class="text-xs text-muted-foreground">
              原任务将保留记录，新任务将获得新的 ID。重试期间不会影响其他任务。
            </p>
          </div>
        </div>
        <div v-if="retryTarget.error_message" class="space-y-1">
          <p class="text-xs font-medium text-muted-foreground">原任务错误信息：</p>
          <p class="rounded-md bg-muted/60 p-2 font-mono text-xs text-danger">
            {{ retryTarget.error_message }}
          </p>
        </div>
      </div>
      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="retryDialogVisible = false">
          取消
        </Button>
        <Button :disabled="retrying" @click="confirmRetry">
          <RotateCcw
            class="size-4"
            :stroke-width="1.5"
            :class="retrying ? 'animate-spin' : ''"
          />
          确认重试
        </Button>
      </div>
    </Dialog>
  </div>
</template>
