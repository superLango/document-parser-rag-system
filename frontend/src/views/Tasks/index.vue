<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, View, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { taskApi } from '@/api/modules/task'
import type { Task } from '@/api/types'

const router = useRouter()

// ---------- 任务列表 ----------
const tasks = ref<Task[]>([])
const total = ref(0)
const loading = ref(false)
const filterStatus = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// ---------- 状态筛选选项 ----------
const statusOptions = [
  { label: '全部', value: '' },
  { label: '等待中', value: 'pending' },
  { label: '已开始', value: 'started' },
  { label: '处理中', value: 'progress' },
  { label: '已完成', value: 'success' },
  { label: '已失败', value: 'failed' },
]

// ---------- 状态标签分色 ----------
function statusTagType(status: string): 'info' | 'warning' | 'success' | 'danger' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'progress') return 'warning'
  return 'info'
}

function statusLabel(status: string): string {
  const found = statusOptions.find(o => o.value === status)
  return found ? found.label : status
}

// ---------- 时间格式化 ----------
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN')
}

// ---------- ID 截断显示 ----------
function truncateId(id: string): string {
  return id ? id.slice(0, 8) + '...' : '—'
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
    ElMessage.error('加载任务列表失败')
  } finally {
    loading.value = false
  }
}

// ---------- 查看任务：跳转 Parser 页面 ----------
function handleView(row: unknown) {
  const task = row as Task
  router.push({ name: 'Parser', params: { id: task.document_id }, query: { task_id: task.id } })
}

// ---------- 重试失败任务 ----------
async function handleRetry(row: unknown) {
  const task = row as Task
  try {
    await ElMessageBox.confirm(`确认重试任务 ${task.id.slice(0, 8)}...？`, '重试确认', { type: 'warning' })
    const res = await taskApi.retry(task.id)
    ElMessage.success(`任务已重新提交，新任务ID: ${res.task_id.slice(0, 8)}...`)
    await loadTasks()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error('重试失败')
    }
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadTasks()
}

function handleSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
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
  <div class="tasks-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">任务管理</h2>
        <p class="page-desc">查看与管理文档解析任务</p>
      </div>
    </div>

    <div class="bp-card">
      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-select v-model="filterStatus" placeholder="状态筛选" clearable style="width: 160px" @change="handleFilterChange">
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
      </div>

      <!-- 任务表格 -->
      <el-table v-loading="loading" :data="tasks" style="width: 100%" stripe>
        <el-table-column label="任务ID" width="130">
          <template #default="{ row }">
            <span class="mono">{{ truncateId(row.id) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="文档ID" width="130">
          <template #default="{ row }">
            <span class="mono">{{ truncateId(row.document_id) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : row.status === 'success' ? 'success' : undefined" />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="180">
          <template #default="{ row }">{{ formatTime(row.completed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="View" @click="handleView(row)">查看</el-button>
            <el-button v-if="row.status === 'failed'" size="small" type="warning" :icon="RefreshRight" @click="handleRetry(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.page-header {
  margin-bottom: 24px;
  .page-title { font-size: var(--fs-xl); font-weight: 600; margin-bottom: 4px; }
  .page-desc { font-size: var(--fs-sm); color: var(--text-secondary); }
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
