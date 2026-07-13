<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { termApi } from '@/api/modules/term'
import type { Term } from '@/api/types'

const loading = ref(true)
const terms = ref<Term[]>([])
const total = ref(0)

const query = reactive({
  keyword: '',
  category: '',
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

function handleSearch() {
  query.page = 1
  fetchList()
}

onMounted(fetchList)
</script>

<template>
  <div class="terms">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">术语库</h2>
        <p class="page-desc">技术标准术语的检索与管理</p>
      </div>
    </div>

    <!-- 搜索栏 -->
    <div class="bp-card filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索术语、英文、同义词"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-input v-model="query.category" placeholder="分类" clearable class="category-input" @keyup.enter="handleSearch" />
      <el-button type="primary" @click="handleSearch">查询</el-button>
    </div>

    <!-- 术语列表 -->
    <div class="bp-card terms-card" v-loading="loading">
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
        <el-table-column label="分类" prop="category" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标准号" prop="standard_number" width="140">
          <template #default="{ row }">
            <span class="mono">{{ row.standard_number || '—' }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无术语" :image-size="80" />
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

.filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;

  .category-input {
    width: 160px;
  }
}

.terms-card {
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
