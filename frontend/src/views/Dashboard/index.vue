<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Document, SetUp, Collection, DocumentChecked } from '@element-plus/icons-vue'
import { dashboardApi } from '@/api/modules/dashboard'
import type { DashboardStats } from '@/api/types'

const loading = ref(true)
const stats = ref<DashboardStats | null>(null)

const statCards = [
  { key: 'documents_count', label: '文档总数', icon: Document, color: 'var(--accent-primary)' },
  { key: 'tasks_count', label: '解析任务', icon: DocumentChecked, color: 'var(--accent-secondary)' },
  { key: 'schemas_count', label: '抽取 Schema', icon: SetUp, color: 'var(--accent-success)' },
  { key: 'terms_count', label: '术语条目', icon: Collection, color: 'var(--accent-info)' },
] as const

async function fetchStats() {
  loading.value = true
  try {
    stats.value = await dashboardApi.getStats()
  } catch {
    // 后端未就绪时使用空数据
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

onMounted(fetchStats)
</script>

<template>
  <div class="dashboard">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">仪表盘</h2>
        <p class="page-desc">系统运行概览与近期活动</p>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <div
        v-for="card in statCards"
        :key="card.key"
        class="stat-card bp-card"
      >
        <div class="stat-icon" :style="{ color: card.color, borderColor: card.color }">
          <el-icon><component :is="card.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-value mono">
            <el-skeleton-item v-if="loading" variant="text" style="width: 60px" />
            <template v-else>{{ stats?.[card.key] ?? 0 }}</template>
          </div>
          <div class="stat-label">{{ card.label }}</div>
        </div>
      </div>
    </div>

    <!-- 近期活动 -->
    <div class="activity-grid">
      <div class="bp-card activity-card">
        <div class="card-header">
          <span class="card-title">近期文档</span>
          <span class="mono card-count">{{ stats?.recent_documents.length ?? 0 }}</span>
        </div>
        <div class="card-body">
          <template v-if="loading">
            <div v-for="i in 4" :key="i" class="skeleton-row">
              <el-skeleton-item variant="text" style="width: 50%" />
              <el-skeleton-item variant="text" style="width: 30%" />
            </div>
          </template>
          <template v-else-if="stats?.recent_documents.length">
            <div
              v-for="doc in stats.recent_documents"
              :key="doc.id"
              class="activity-row"
            >
              <span class="activity-title text-truncate">{{ doc.title }}</span>
              <span class="mono activity-meta">{{ doc.standard_number || doc.doc_type }}</span>
            </div>
          </template>
          <el-empty v-else description="暂无文档" :image-size="60" />
        </div>
      </div>

      <div class="bp-card activity-card">
        <div class="card-header">
          <span class="card-title">近期任务</span>
          <span class="mono card-count">{{ stats?.recent_tasks.length ?? 0 }}</span>
        </div>
        <div class="card-body">
          <template v-if="loading">
            <div v-for="i in 4" :key="i" class="skeleton-row">
              <el-skeleton-item variant="text" style="width: 40%" />
              <el-skeleton-item variant="text" style="width: 30%" />
            </div>
          </template>
          <template v-else-if="stats?.recent_tasks.length">
            <div
              v-for="task in stats.recent_tasks"
              :key="task.id"
              class="activity-row"
            >
              <span class="mono activity-title">TASK-{{ task.id }}</span>
              <span class="activity-meta" :class="`status-${task.status}`">{{ task.status }}</span>
            </div>
          </template>
          <el-empty v-else description="暂无任务" :image-size="60" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 24px;

  .page-title {
    font-size: var(--fs-xl);
    font-weight: 600;
    margin-bottom: 4px;
  }

  .page-desc {
    font-size: var(--fs-sm);
    color: var(--text-secondary);
  }
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;

  .stat-icon {
    width: 48px;
    height: 48px;
    border-radius: var(--radius-md);
    border: 1px solid;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    flex-shrink: 0;
  }

  .stat-value {
    font-size: var(--fs-2xl);
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.2;
  }

  .stat-label {
    font-size: var(--fs-sm);
    color: var(--text-secondary);
    margin-top: 2px;
  }
}

.activity-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.activity-card {
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-base);

    .card-title {
      font-weight: 600;
      color: var(--text-primary);
    }

    .card-count {
      font-size: var(--fs-xs);
      color: var(--accent-primary);
    }
  }

  .card-body {
    padding: 8px 20px;
  }
}

.skeleton-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
}

.activity-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-light);

  &:last-child {
    border-bottom: none;
  }

  .activity-title {
    font-size: var(--fs-sm);
    color: var(--text-primary);
    max-width: 60%;
  }

  .activity-meta {
    font-size: var(--fs-xs);
    color: var(--text-muted);
  }

  .status-success { color: var(--accent-success); }
  .status-failed { color: var(--accent-danger); }
  .status-running { color: var(--accent-primary); }
  .status-queued { color: var(--text-secondary); }
}
</style>
