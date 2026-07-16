<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { termApi } from '@/api/modules/term'
import type { Term, TermCreate } from '@/api/types'

const loading = ref(true)
const terms = ref<Term[]>([])
const total = ref(0)

const query = reactive({
  keyword: '',
  category: '',
  page: 1,
  page_size: 20,
})

// 分类列表
const categories = ref<string[]>([])

async function loadCategories() {
  try {
    categories.value = await termApi.getCategories()
  } catch {
    categories.value = []
  }
}

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

// ---------- 新增 / 编辑 ----------
const dialogVisible = ref(false)
const editingTerm = ref<Term | null>(null)
const submitting = ref(false)
const form = reactive({
  term: '',
  english_term: '',
  definition: '',
  category: '',
  standard_number: '',
  synonyms: '',
})

function resetForm() {
  form.term = ''
  form.english_term = ''
  form.definition = ''
  form.category = ''
  form.standard_number = ''
  form.synonyms = ''
}

function openCreate() {
  editingTerm.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: unknown) {
  const term = row as Term
  editingTerm.value = term
  form.term = term.term
  form.english_term = term.english_term || ''
  form.definition = term.definition || ''
  form.category = term.category || ''
  form.standard_number = term.standard_number || ''
  form.synonyms = (term.synonyms || []).join(',')
  dialogVisible.value = true
}

async function submit() {
  if (!form.term.trim()) {
    ElMessage.warning('请填写术语名')
    return
  }
  if (!form.definition.trim()) {
    ElMessage.warning('请填写定义')
    return
  }
  if (!form.category.trim()) {
    ElMessage.warning('请选择分类')
    return
  }

  const payload: TermCreate = {
    term: form.term.trim(),
    english_term: form.english_term.trim() || undefined,
    definition: form.definition.trim(),
    category: form.category.trim(),
    standard_number: form.standard_number.trim() || undefined,
    synonyms: form.synonyms
      .split(',')
      .map(s => s.trim())
      .filter(Boolean),
  }

  submitting.value = true
  try {
    if (editingTerm.value) {
      await termApi.update(editingTerm.value.id, payload)
      ElMessage.success('术语已更新')
    } else {
      await termApi.create(payload)
      ElMessage.success('术语已创建')
    }
    dialogVisible.value = false
    await fetchList()
  } catch {
    ElMessage.error(editingTerm.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

// ---------- 删除 ----------
async function handleDelete(row: unknown) {
  const term = row as Term
  try {
    await ElMessageBox.confirm(`确认删除术语「${term.term}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await termApi.remove(term.id)
    ElMessage.success('术语已删除')
    await fetchList()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// ---------- 批量导入 ----------
const importDialogVisible = ref(false)
const importText = ref('')
const importing = ref(false)

function openImport() {
  importText.value = ''
  importDialogVisible.value = true
}

async function handleImport() {
  let data: TermCreate[]
  try {
    data = JSON.parse(importText.value)
    if (!Array.isArray(data)) {
      throw new Error('not array')
    }
  } catch {
    ElMessage.error('JSON 格式错误，请粘贴有效的数组')
    return
  }

  importing.value = true
  try {
    const res = await termApi.batchImport(data)
    ElMessage.success(`成功导入 ${res.imported} 条术语`)
    importDialogVisible.value = false
    await fetchList()
  } catch {
    ElMessage.error('批量导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadCategories()
  fetchList()
})
</script>

<template>
  <div class="terms">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">术语库</h2>
        <p class="page-desc">技术标准术语的检索与管理</p>
      </div>
      <div class="header-actions">
        <el-button @click="openImport">
          <el-icon><Plus /></el-icon>
          <span>批量导入</span>
        </el-button>
        <el-button type="primary" class="btn-glow" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>新增术语</span>
        </el-button>
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
      <el-select
        v-model="query.category"
        placeholder="分类"
        clearable
        filterable
        class="category-select"
        @change="handleSearch"
      >
        <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
      </el-select>
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
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="handleDelete(row)">删除</el-button>
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

    <!-- 新增 / 编辑 对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingTerm ? '编辑术语' : '新增术语'"
      width="600px"
    >
      <el-form :model="form" label-width="80px" label-position="left">
        <el-form-item label="术语名">
          <el-input v-model="form.term" placeholder="如：术语标准" />
        </el-form-item>
        <el-form-item label="英文">
          <el-input v-model="form.english_term" placeholder="如：terminology" />
        </el-form-item>
        <el-form-item label="定义">
          <el-input v-model="form.definition" type="textarea" :rows="3" placeholder="术语定义" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select
            v-model="form.category"
            placeholder="选择或输入分类"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
          >
            <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
          </el-select>
        </el-form-item>
        <el-form-item label="标准号">
          <el-input v-model="form.standard_number" placeholder="如：GB/T 1.1-2020" />
        </el-form-item>
        <el-form-item label="同义词">
          <el-input v-model="form.synonyms" placeholder="多个同义词用逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">
          {{ editingTerm ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量导入对话框 -->
    <el-dialog v-model="importDialogVisible" title="批量导入术语" width="640px">
      <p class="import-tip">
        粘贴 JSON 数组，格式示例：
        <code>[{ "term": "...", "definition": "...", "category": "..." }]</code>
      </p>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="12"
        placeholder='[{ "term": "术语", "definition": "定义", "category": "分类" }]'
        class="import-textarea"
      />
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="handleImport">导入</el-button>
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

  .header-actions {
    display: flex;
    gap: 8px;
  }
}

.filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;

  .category-select {
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

.import-tip {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  margin-bottom: 12px;

  code {
    font-family: var(--font-mono, monospace);
    background: var(--bg-base);
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-size: var(--fs-xs);
  }
}

.import-textarea {
  :deep(.el-textarea__inner) {
    font-family: var(--font-mono, monospace);
    font-size: var(--fs-sm);
  }
}
</style>
