<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Document, Files, Collection, DocumentChecked, RefreshRight, Delete, MagicStick } from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '@/api/modules/knowledgeBase'
import { documentApi } from '@/api/modules/document'
import type { KBStats, Document as DocType } from '@/api/types'

// ---------- 统计 ----------
const statsLoading = ref(true)
const stats = ref<KBStats>({
  total_chunks: 0,
  total_docs: 0,
  indexed_docs: 0,
  completed_docs: 0,
})

const statCards = [
  { key: 'total_chunks', label: '分块总数', icon: Files, color: 'var(--accent-primary)' },
  { key: 'total_docs', label: '文档总数', icon: Document, color: 'var(--accent-secondary)' },
  { key: 'indexed_docs', label: '已索引文档', icon: Collection, color: 'var(--accent-info)' },
  { key: 'completed_docs', label: '索引完成文档', icon: DocumentChecked, color: 'var(--accent-success)' },
] as const

async function fetchStats() {
  statsLoading.value = true
  try {
    stats.value = await knowledgeBaseApi.stats()
  } catch {
    // 后端未就绪时保持空数据
  } finally {
    statsLoading.value = false
  }
}

// ---------- 文档列表 ----------
const listLoading = ref(true)
const documents = ref<DocType[]>([])

async function fetchDocuments() {
  listLoading.value = true
  try {
    const res = await documentApi.getList({ status: 'completed', page_size: 100 })
    documents.value = res.items
  } catch {
    documents.value = []
  } finally {
    listLoading.value = false
  }
}

// ---------- 索引操作 ----------
const indexingIds = ref<Set<string>>(new Set())

async function handleIndex(row: unknown) {
  const doc = row as DocType
  if (indexingIds.value.has(doc.id)) return
  indexingIds.value.add(doc.id)
  try {
    await knowledgeBaseApi.indexDocument(doc.id)
    ElMessage.success('索引任务已提交')
    await fetchStats()
  } catch {
    // 错误提示已由 axios 拦截器处理
  } finally {
    indexingIds.value.delete(doc.id)
  }
}

// ---------- 移除索引 ----------
const removingIds = ref<Set<string>>(new Set())

async function handleRemove(row: unknown) {
  const doc = row as DocType
  removingIds.value.add(doc.id)
  try {
    await knowledgeBaseApi.removeDocument(doc.id)
    ElMessage.success('已移除文档索引')
    await fetchStats()
  } catch {
    // 错误提示已由 axios 拦截器处理
  } finally {
    removingIds.value.delete(doc.id)
  }
}

// ---------- 重建索引 ----------
const rebuilding = ref(false)

async function handleRebuild() {
  rebuilding.value = true
  try {
    await knowledgeBaseApi.rebuild()
    ElMessage.success('重建索引任务已提交')
    await fetchStats()
  } catch {
    // 错误提示已由 axios 拦截器处理
  } finally {
    rebuilding.value = false
  }
}

onMounted(() => {
  fetchStats()
  fetchDocuments()
})
</script>

<template>
  <div class="knowledge-base">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">知识库管理</h2>
        <p class="page-desc">管理文档向量索引，支持入索引、移除与重建</p>
      </div>
      <el-popconfirm
        title="确定重建全部索引？该操作将清空现有向量并重新索引所有已解析文档"
        confirm-button-text="重建"
        cancel-button-text="取消"
        confirm-button-type="danger"
        @confirm="handleRebuild"
      >
        <template #reference>
          <el-button type="primary" class="btn-glow" :loading="rebuilding">
            <el-icon><RefreshRight /></el-icon>
            <span>重建索引</span>
          </el-button>
        </template>
      </el-popconfirm>
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
            <el-skeleton-item v-if="statsLoading" variant="text" style="width: 60px" />
            <template v-else>{{ stats[card.key] }}</template>
          </div>
          <div class="stat-label">{{ card.label }}</div>
        </div>
      </div>
    </div>

    <!-- 文档表格 -->
    <div class="bp-card table-card">
      <div class="card-header">
        <span class="card-title">已解析文档</span>
        <span class="mono card-count">{{ documents.length }}</span>
      </div>
      <el-table v-loading="listLoading" :data="documents" style="width: 100%">
        <el-table-column label="文档标题" prop="title" min-width="220" show-overflow-tooltip />
        <el-table-column label="类型" prop="doc_type" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.doc_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标准号" prop="standard_number" width="160">
          <template #default="{ row }">
            <span class="mono">{{ row.standard_number || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" prop="status" width="120">
          <template #default="{ row }">
            <span class="mono status-tag" :class="`status-${row.status}`">{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <el-button
                text
                size="small"
                type="primary"
                :loading="indexingIds.has(row.id)"
                @click="handleIndex(row)"
              >
                <el-icon><MagicStick /></el-icon>
                <span>索引</span>
              </el-button>
              <el-popconfirm
                title="确定移除该文档的索引？移除后该文档将不可检索"
                confirm-button-text="移除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                @confirm="handleRemove(row)"
              >
                <template #reference>
                  <el-button
                    text
                    size="small"
                    type="danger"
                    :loading="removingIds.has(row.id)"
                  >
                    <el-icon><Delete /></el-icon>
                    <span>移除</span>
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无已解析文档" :image-size="80" />
        </template>
      </el-table>
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

.table-card {
  padding: 0;

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
}

.status-tag {
  font-size: var(--fs-xs);
  text-transform: uppercase;

  &.status-completed,
  &.status-success {
    color: var(--accent-success);
  }
  &.status-failed {
    color: var(--accent-danger);
  }
  &.status-parsing,
  &.status-running {
    color: var(--accent-primary);
  }
  &.status-pending,
  &.status-queued {
    color: var(--text-secondary);
  }
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
