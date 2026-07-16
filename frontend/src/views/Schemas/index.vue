<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { schemaApi } from '@/api/modules/schema'
import type { Schema, SchemaField } from '@/api/types'

const loading = ref(true)
const schemas = ref<Schema[]>([])

const dialogVisible = ref(false)
const submitting = ref(false)
const editingSchema = ref<Schema | null>(null)
const form = reactive({
  name: '',
  description: '',
  doc_type: '',
  fields: [] as SchemaField[],
})

// 详情抽屉
const detailVisible = ref(false)
const detailSchema = ref<Schema | null>(null)

async function fetchList() {
  loading.value = true
  try {
    const res = await schemaApi.getList()
    schemas.value = res.items
  } catch {
    schemas.value = []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingSchema.value = null
  form.name = ''
  form.description = ''
  form.doc_type = ''
  form.fields = [{ name: '', description: '', field_type: 'string', required: true }]
  dialogVisible.value = true
}

// 编辑：获取详情并预填表单
async function openEdit(schema: Schema) {
  try {
    const detail = await schemaApi.getDetail(schema.id)
    editingSchema.value = detail
    form.name = detail.name
    form.description = detail.description
    form.doc_type = detail.doc_type
    form.fields = detail.fields.length
      ? detail.fields.map((f) => ({ ...f }))
      : [{ name: '', description: '', field_type: 'string', required: false }]
    dialogVisible.value = true
  } catch {
    ElMessage.error('获取 Schema 详情失败')
  }
}

function addField() {
  form.fields.push({ name: '', description: '', field_type: 'string', required: false })
}

function removeField(index: number) {
  form.fields.splice(index, 1)
}

async function submit() {
  submitting.value = true
  try {
    if (editingSchema.value) {
      await schemaApi.update(editingSchema.value.id, { ...form })
      ElMessage.success('Schema 已更新')
    } else {
      await schemaApi.create({ ...form })
      ElMessage.success('Schema 已创建')
    }
    dialogVisible.value = false
    await fetchList()
  } catch {
    ElMessage.error(editingSchema.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

// 删除 Schema
async function handleDelete(schema: Schema) {
  try {
    await ElMessageBox.confirm(`确定删除 Schema「${schema.name}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await schemaApi.remove(schema.id)
    ElMessage.success('Schema 已删除')
    await fetchList()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// 启用/停用切换
async function handleToggleActive(schema: Schema, val: boolean | string | number) {
  const active = Boolean(val)
  try {
    await schemaApi.toggleActive(schema.id, active)
    schema.is_active = active
    ElMessage.success(active ? '已启用' : '已停用')
  } catch {
    ElMessage.error('状态切换失败')
  }
}

// 打开详情抽屉
function openDetail(schema: Schema) {
  detailSchema.value = schema
  detailVisible.value = true
}

const fieldTypeOptions = [
  { label: '字符串', value: 'string' },
  { label: '数字', value: 'number' },
  { label: '布尔', value: 'boolean' },
  { label: '日期', value: 'date' },
  { label: '枚举', value: 'enum' },
  { label: '数组', value: 'array' },
]

onMounted(fetchList)
</script>

<template>
  <div class="schemas">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">抽取 Schema</h2>
        <p class="page-desc">定义文档结构化抽取的字段规则</p>
      </div>
      <el-button type="primary" class="btn-glow" @click="openCreate">
        <el-icon><Plus /></el-icon>
        <span>新建 Schema</span>
      </el-button>
    </div>

    <!-- Schema 列表 -->
    <div v-loading="loading" class="schema-grid">
      <div v-for="schema in schemas" :key="schema.id" class="bp-card schema-card" @click="openDetail(schema)">
        <div class="schema-header">
          <span class="schema-name">{{ schema.name }}</span>
          <el-switch
            :model-value="schema.is_active"
            size="small"
            @change="(val: boolean | string | number) => handleToggleActive(schema, val)"
          />
        </div>
        <p class="schema-desc">{{ schema.description || '暂无描述' }}</p>
        <div class="schema-fields">
          <span class="mono field-count">{{ schema.fields.length }} 字段</span>
          <div class="field-list">
            <span v-for="f in schema.fields.slice(0, 4)" :key="f.name" class="field-tag mono">
              {{ f.name }}
            </span>
          </div>
        </div>
        <div class="schema-actions">
          <el-button size="small" text @click.stop="openEdit(schema)">编辑</el-button>
          <el-button size="small" text type="danger" @click.stop="handleDelete(schema)">删除</el-button>
        </div>
      </div>
      <el-empty v-if="!loading && !schemas.length" description="暂无 Schema" class="grid-empty" />
    </div>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingSchema ? '编辑 Schema' : '新建 Schema'" width="720px">
      <el-form :model="form" label-width="80px" label-position="left">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：GB/T 标准基础字段" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="文档类型">
          <el-input v-model="form.doc_type" placeholder="如：gbt_standard" />
        </el-form-item>
        <el-form-item label="字段定义">
          <div class="field-builder">
            <div v-for="(field, idx) in form.fields" :key="idx" class="field-row">
              <el-input v-model="field.name" placeholder="字段名" class="col-name" />
              <el-select v-model="field.field_type" placeholder="类型" class="col-type">
                <el-option v-for="o in fieldTypeOptions" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-switch v-model="field.required" active-text="必填" class="col-required" />
              <el-input v-model="field.description" placeholder="描述" class="col-desc" />
              <el-button text @click="removeField(idx)" :disabled="form.fields.length <= 1">删除</el-button>
            </div>
            <el-button text @click="addField">
              <el-icon><Plus /></el-icon>
              <span>添加字段</span>
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">
          {{ editingSchema ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" title="Schema 详情" size="480px">
      <template v-if="detailSchema">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="名称">{{ detailSchema.name }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ detailSchema.description || '暂无描述' }}</el-descriptions-item>
          <el-descriptions-item label="文档类型">{{ detailSchema.doc_type || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="detailSchema.is_active ? 'success' : 'info'">
              {{ detailSchema.is_active ? '启用' : '停用' }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <h4 class="detail-section-title">字段列表</h4>
        <el-table :data="detailSchema.fields" border size="small">
          <el-table-column prop="name" label="字段名" min-width="100" />
          <el-table-column prop="field_type" label="类型" width="90" />
          <el-table-column label="必填" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.required ? 'danger' : 'info'">
                {{ row.required ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="120" show-overflow-tooltip />
        </el-table>
      </template>
    </el-drawer>
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

.schema-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.grid-empty {
  grid-column: 1 / -1;
}

.schema-card {
  padding: 20px;
  cursor: pointer;
  transition: border-color 0.2s ease;

  &:hover {
    border-color: var(--accent-primary);
  }

  .schema-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;

    .schema-name {
      font-size: var(--fs-base);
      font-weight: 600;
      color: var(--text-primary);
    }
  }

  .schema-desc {
    font-size: var(--fs-sm);
    color: var(--text-secondary);
    margin-bottom: 16px;
    min-height: 20px;
  }

  .field-count {
    font-size: var(--fs-xs);
    color: var(--accent-primary);
    margin-bottom: 8px;
    display: block;
  }

  .field-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .field-tag {
    font-size: var(--fs-xs);
    padding: 2px 8px;
    background: var(--bg-base);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
  }

  .schema-actions {
    display: flex;
    justify-content: flex-end;
    gap: 4px;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border-light);
  }
}

.field-builder {
  width: 100%;

  .field-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;

    .col-name { flex: 1; min-width: 100px; }
    .col-type { width: 120px; flex-shrink: 0; }
    .col-required { flex-shrink: 0; }
    .col-desc { flex: 1; min-width: 120px; }
  }
}

.detail-section-title {
  font-size: var(--fs-base);
  font-weight: 600;
  margin: 20px 0 12px;
  color: var(--text-primary);
}
</style>
