<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, Search, View, Delete, ArrowDown, Document } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { documentApi } from '@/api/modules/document'
import { taskApi } from '@/api/modules/task'
import { schemaApi } from '@/api/modules/schema'
import type { Document as DocType, Schema } from '@/api/types'

const router = useRouter()

// ---------- 文档列表 ----------
const loading = ref(true)
const documents = ref<DocType[]>([])
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

// ---------- 文档上传 ----------
const uploadRef = ref()
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const pendingFile = ref<File | null>(null)
const uploadForm = reactive({
  title: '',
  doc_type: 'standard',
  standard_number: '',
})

const docTypeOptions = [
  { label: '标准', value: 'standard' },
  { label: '规程', value: 'regulation' },
  { label: '规范', value: 'specification' },
  { label: '手册', value: 'manual' },
  { label: '其他', value: 'other' },
]

const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

function handleUpload() {
  uploadRef.value?.$el?.querySelector('input[type=file]')?.click()
}

function handleFileChange(uploadFile: UploadFile) {
  if (uploadFile.status !== 'ready') return
  const file = uploadFile.raw
  if (!file) return

  // 文件类型校验：仅支持 PDF
  const isPdf =
    file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  if (!isPdf) {
    ElMessage.error('仅支持 PDF 格式文件')
    uploadRef.value?.clearFiles()
    return
  }

  // 文件大小校验：≤ 50MB
  if (file.size > MAX_FILE_SIZE) {
    ElMessage.error('文件大小不能超过 50MB')
    uploadRef.value?.clearFiles()
    return
  }

  // 存储文件并打开元信息对话框
  pendingFile.value = file
  uploadForm.title = file.name.replace(/\.pdf$/i, '')
  uploadForm.doc_type = 'standard'
  uploadForm.standard_number = ''
  uploadDialogVisible.value = true
}

function onUploadDialogClose() {
  pendingFile.value = null
  uploadRef.value?.clearFiles()
}

async function submitUpload() {
  if (!pendingFile.value) return
  if (!uploadForm.title.trim()) {
    ElMessage.error('请填写文档标题')
    return
  }

  uploading.value = true
  try {
    await documentApi.upload(pendingFile.value, {
      title: uploadForm.title.trim(),
      doc_type: uploadForm.doc_type,
      standard_number: uploadForm.standard_number.trim() || undefined,
    })
    ElMessage.success('文档上传成功')
    uploadDialogVisible.value = false
    await fetchList()
  } catch {
    // 错误提示已由 axios 拦截器处理
  } finally {
    uploading.value = false
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ---------- 文档删除 ----------
// 表格 row 类型为 DefaultRow，此处断言为 DocType
async function handleDelete(row: unknown) {
  const doc = row as DocType
  try {
    await documentApi.remove(doc.id)
    ElMessage.success('文档已删除')
    await fetchList()
  } catch {
    // 错误提示已由 axios 拦截器处理
  }
}

// ---------- 触发解析 ----------
const parseDialogVisible = ref(false)
const parseDoc = ref<DocType | null>(null)
const schemaLoading = ref(false)
const schemas = ref<Schema[]>([])
const selectedSchemaId = ref<string>('')
const submittingParse = ref(false)

// 表格 row 类型为 DefaultRow，此处断言为 DocType
function handleCommand(command: string, row: unknown) {
  const doc = row as DocType
  if (command === 'view') {
    viewDetail(doc)
  } else if (command === 'parse') {
    openParseDialog(doc)
  }
}

function viewDetail(doc: DocType) {
  router.push(`/parser/${doc.id}`)
}

async function openParseDialog(doc: DocType) {
  parseDoc.value = doc
  selectedSchemaId.value = ''
  parseDialogVisible.value = true

  schemaLoading.value = true
  try {
    const res = await schemaApi.getList({ is_active: true })
    schemas.value = res.items
  } catch {
    schemas.value = []
  } finally {
    schemaLoading.value = false
  }
}

async function submitParse() {
  if (!parseDoc.value) return
  if (!selectedSchemaId.value) {
    ElMessage.error('请选择抽取 Schema')
    return
  }

  submittingParse.value = true
  try {
    const res = await taskApi.submit({
      document_id: String(parseDoc.value.id),
      schema_id: selectedSchemaId.value,
    })
    ElMessage.success('解析任务已提交')
    parseDialogVisible.value = false
    router.push(`/parser/${parseDoc.value.id}?task_id=${res.task_id}`)
  } catch {
    // 错误提示已由 axios 拦截器处理
  } finally {
    submittingParse.value = false
  }
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
      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="handleFileChange"
        accept="application/pdf,.pdf"
      >
        <el-icon class="upload-icon"><Upload /></el-icon>
        <div class="upload-text">拖拽 PDF 文件到此处，或<span class="upload-link">点击上传</span></div>
        <div class="upload-hint mono">支持 GB/T、ASTM、ISO 等技术标准文档（最大 50MB）</div>
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
      <el-table v-loading="loading" :data="documents" style="width: 100%">
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
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <el-dropdown trigger="click" @command="(cmd) => handleCommand(cmd, row)">
                <el-button text size="small">
                  <span>操作</span>
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="view">
                      <el-icon><View /></el-icon>
                      查看详情
                    </el-dropdown-item>
                    <el-dropdown-item command="parse">
                      <el-icon><Upload /></el-icon>
                      开始解析
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-popconfirm
                title="确定删除该文档？删除后不可恢复"
                confirm-button-text="删除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                @confirm="handleDelete(row)"
              >
                <template #reference>
                  <el-button text size="small" type="danger">
                    <el-icon><Delete /></el-icon>
                    <span>删除</span>
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
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

    <!-- 上传元信息对话框 -->
    <el-dialog
      v-model="uploadDialogVisible"
      title="上传文档"
      width="520px"
      @close="onUploadDialogClose"
    >
      <el-form :model="uploadForm" label-width="80px" label-position="left">
        <el-form-item label="文件">
          <div v-if="pendingFile" class="file-info">
            <el-icon class="file-icon"><Document /></el-icon>
            <span class="file-name">{{ pendingFile.name }}</span>
            <span class="file-size mono">{{ formatFileSize(pendingFile.size) }}</span>
          </div>
        </el-form-item>
        <el-form-item label="标题" required>
          <el-input v-model="uploadForm.title" placeholder="请输入文档标题" />
        </el-form-item>
        <el-form-item label="文档类型" required>
          <el-select v-model="uploadForm.doc_type" placeholder="请选择文档类型" style="width: 100%">
            <el-option
              v-for="o in docTypeOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标准号">
          <el-input
            v-model="uploadForm.standard_number"
            placeholder="如：GB/T 12345-2020（可选）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">确认上传</el-button>
      </template>
    </el-dialog>

    <!-- 解析 Schema 选择对话框 -->
    <el-dialog v-model="parseDialogVisible" title="开始解析" width="480px">
      <el-form label-width="80px" label-position="left">
        <el-form-item label="文档">
          <span class="parse-doc-name">{{ parseDoc?.title }}</span>
        </el-form-item>
        <el-form-item label="Schema" required>
          <el-select
            v-model="selectedSchemaId"
            placeholder="请选择抽取 Schema"
            style="width: 100%"
            :loading="schemaLoading"
          >
            <el-option
              v-for="schema in schemas"
              :key="schema.id"
              :label="schema.name"
              :value="String(schema.id)"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="parseDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingParse" @click="submitParse">
          提交解析
        </el-button>
      </template>
    </el-dialog>
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

// 操作列按钮布局
.action-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}

// 上传对话框文件信息
.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-base);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  width: 100%;

  .file-icon {
    color: var(--accent-primary);
    font-size: 18px;
    flex-shrink: 0;
  }

  .file-name {
    flex: 1;
    font-size: var(--fs-sm);
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .file-size {
    font-size: var(--fs-xs);
    color: var(--text-muted);
    flex-shrink: 0;
  }
}

// 解析对话框文档名
.parse-doc-name {
  font-size: var(--fs-sm);
  color: var(--text-primary);
  font-weight: 500;
}
</style>
