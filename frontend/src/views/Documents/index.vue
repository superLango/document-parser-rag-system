<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, Search, View } from '@element-plus/icons-vue'
import { documentApi } from '@/api/modules/document'
import type { Document } from '@/api/types'

const router = useRouter()

const loading = ref(true)
const documents = ref<Document[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
})

async function fetchList() {
  loading.value = true
  try {
    const res = await documentApi.getList(query)
    documents.value = res.items
    total.value = res.total
  } catch {
    documents.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  query.page = 1
  fetchList()
}

function openParser(doc: Document) {
  router.push(`/parser/${doc.id}`)
}

// 上传占位
const uploadRef = ref()
function handleUpload() {
  // 预留：调用上传组件
}

onMounted(fetchList)
</script>

<template>
  <div class="documents">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">文档管理</h2>
        <p class="page-desc">上传技术标准文档并管理解析状态</p>
      </div>
      <el-button type="primary" class="btn-glow" @click="handleUpload">
        <el-icon><Upload /></el-icon>
        <span>上传文档</span>
      </el-button>
    </div>

    <!-- 上传区 -->
    <div class="bp-card upload-zone">
      <el-upload ref="uploadRef" drag :auto-upload="false" :show-file-list="false">
        <el-icon class="upload-icon"><Upload /></el-icon>
        <div class="upload-text">拖拽 PDF 文件到此处，或<span class="upload-link">点击上传</span></div>
        <div class="upload-hint mono">支持 GB/T、ASTM、ISO 等技术标准文档</div>
      </el-upload>
    </div>

    <!-- 搜索 -->
    <div class="bp-card filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索文档标题、标准号"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
    </div>

    <!-- 文档表格 -->
    <div class="bp-card table-card">
      <el-table
        v-loading="loading"
        :data="documents"
        style="width: 100%"
      >
        <el-table-column label="文档标题" prop="title" min-width="200" show-overflow-tooltip />
        <el-table-column label="标准号" prop="standard_number" width="160">
          <template #default="{ row }">
            <span class="mono">{{ row.standard_number || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" prop="doc_type" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.doc_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" prop="status" width="120">
          <template #default="{ row }">
            <span class="mono status-tag" :class="`status-${row.status}`">{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column label="页数" prop="page_count" width="80" align="center">
          <template #default="{ row }">
            <span class="mono">{{ row.page_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" prop="uploaded_at" width="180">
          <template #default="{ row }">
            <span class="mono date-cell">{{ row.uploaded_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" @click="openParser(row)">
              <el-icon><View /></el-icon>
              <span>解析</span>
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无文档，请上传" :image-size="80" />
        </template>
      </el-table>

      <!-- 分页 -->
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

.upload-zone {
  padding: 24px;
  margin-bottom: 16px;

  :deep(.el-upload-dragger) {
    background-color: var(--bg-base);
    border: 1px dashed var(--border-base);
    border-radius: var(--radius-md);
    transition: border-color var(--transition-fast);

    &:hover {
      border-color: var(--accent-primary);
    }
  }

  .upload-icon {
    font-size: 40px;
    color: var(--accent-primary);
    margin-bottom: 8px;
  }

  .upload-text {
    color: var(--text-primary);
    font-size: var(--fs-base);
    margin-bottom: 4px;

    .upload-link {
      color: var(--accent-primary);
    }
  }

  .upload-hint {
    font-size: var(--fs-xs);
    color: var(--text-muted);
  }
}

.filter-bar {
  padding: 12px 16px;
  margin-bottom: 16px;
}

.table-card {
  padding: 4px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px;
}

.date-cell {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.status-tag {
  font-size: var(--fs-xs);
  text-transform: uppercase;

  &.status-completed, &.status-success { color: var(--accent-success); }
  &.status-failed { color: var(--accent-danger); }
  &.status-parsing, &.status-running { color: var(--accent-primary); }
  &.status-pending, &.status-queued { color: var(--text-secondary); }
}
</style>
