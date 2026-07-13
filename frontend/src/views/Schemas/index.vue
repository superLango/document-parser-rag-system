<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { schemaApi } from '@/api/modules/schema'
import type { Schema, SchemaField } from '@/api/types'

const loading = ref(true)
const schemas = ref<Schema[]>([])

const dialogVisible = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '',
  description: '',
  doc_type: '',
  fields: [] as SchemaField[],
})

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
  form.name = ''
  form.description = ''
  form.doc_type = ''
  form.fields = [{ name: '', description: '', field_type: 'string', required: true }]
  dialogVisible.value = true
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
    await schemaApi.create({ ...form })
    dialogVisible.value = false
    await fetchList()
  } finally {
    submitting.value = false
  }
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
      <div v-for="schema in schemas" :key="schema.id" class="bp-card schema-card">
        <div class="schema-header">
          <span class="schema-name">{{ schema.name }}</span>
          <el-tag size="small" :type="schema.is_active ? 'success' : 'info'">
            {{ schema.is_active ? '启用' : '停用' }}
          </el-tag>
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
      </div>
      <el-empty v-if="!loading && !schemas.length" description="暂无 Schema" class="grid-empty" />
    </div>

    <!-- 新建对话框 -->
    <el-dialog v-model="dialogVisible" title="新建 Schema" width="640px">
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
        <el-button type="primary" :loading="submitting" @click="submit">创建</el-button>
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
}

.field-builder {
  width: 100%;

  .field-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;

    .col-name { flex: 1; }
    .col-type { width: 120px; }
    .col-required { flex-shrink: 0; }
  }
}
</style>
