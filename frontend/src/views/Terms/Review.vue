<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { termApi } from '@/api/modules/term'
import type { Term } from '@/api/types'

const loading = ref(true)
const terms = ref<Term[]>([])
const total = ref(0)

const query = reactive({
  status: 'pending',
  page: 1,
  page_size: 20,
})

async function fetchList() {
  loading.value = true
  try {
    const res = await termApi.getList(query)
    terms.value = res.items
    total.value = res.total
  } catch {
    terms.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function handleApprove(row: unknown) {
  const term = row as Term
  try {
    await ElMessageBox.confirm(`确认通过术语「${term.term}」吗？`, '审核确认', {
      confirmButtonText: '通过',
      cancelButtonText: '取消',
      type: 'success',
    })
  } catch {
    return
  }

  try {
    await termApi.review(term.id, 'approve')
    ElMessage.success('已通过')
    fetchList()
  } catch {
    // 错误提示由拦截器统一处理
  }
}

async function handleReject(row: unknown) {
  const term = row as Term
  try {
    await ElMessageBox.confirm(`确认拒绝术语「${term.term}」吗？`, '审核确认', {
      confirmButtonText: '拒绝',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    await termApi.review(term.id, 'reject')
    ElMessage.success('已拒绝')
    fetchList()
  } catch {
    // 错误提示由拦截器统一处理
  }
}

function formatSynonyms(synonyms: string[] | undefined): string {
  if (!synonyms || synonyms.length === 0) return '—'
  return synonyms.join('、')
}

function formatTime(value: string | undefined): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 19)
}

onMounted(fetchList)
</script>

<template>
  <div class="term-review">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">术语审核</h2>
        <p class="page-desc">审核待处理的术语</p>
      </div>
    </div>

    <!-- 待审核术语列表 -->
    <div class="bp-card review-card" v-loading="loading">
      <el-table :data="terms" style="width: 100%">
        <el-table-column label="术语" prop="term" min-width="140">
          <template #default="{ row }">
            <span class="term-name">{{ row.term }}</span>
          </template>
        </el-table-column>
        <el-table-column label="英文" prop="english_term" width="180">
          <template #default="{ row }">
            <span class="mono">{{ row.english_term || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="定义" prop="definition" min-width="280" show-overflow-tooltip />
        <el-table-column label="同义词" min-width="180">
          <template #default="{ row }">
            <span>{{ formatSynonyms(row.synonyms) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            <span class="mono">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="success" size="small" @click="handleApprove(row)">通过</el-button>
            <el-button type="danger" size="small" @click="handleReject(row)">拒绝</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无待审核术语" :image-size="80" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          layout="total, prev, pager, next"
          background
          @current-change="fetchList"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.page-header {
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

.review-card {
  padding: 4px;

  .term-name {
    color: var(--text-primary);
    font-weight: 500;
  }
}

.pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px;
}
</style>
