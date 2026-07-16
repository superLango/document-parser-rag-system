<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { Search, Plus, Refresh, Delete, DataLine } from '@element-plus/icons-vue'
import { knowledgeApi } from '@/api/modules/knowledge'
import { documentApi } from '@/api/modules/document'
import type { KnowledgeGraph, GraphNode, GraphEdge, Document as DocType } from '@/api/types'
import GraphViewer from '@/components/GraphViewer.vue'

// ---------- 图谱数据 ----------
const loading = ref(true)
const graph = ref<KnowledgeGraph>({ nodes: [], edges: [] })

const query = reactive({
  keyword: '',
})

// 搜索结果高亮节点名称集合
const highlightNames = ref<string[]>([])

async function fetchGraph() {
  loading.value = true
  try {
    const result = await knowledgeApi.getGraph({ limit: 50 })
    graph.value = result || { nodes: [], edges: [] }
    highlightNames.value = []
  } catch {
    graph.value = { nodes: [], edges: [] }
  } finally {
    loading.value = false
  }
}

async function handleSearch() {
  if (!query.keyword.trim()) {
    return fetchGraph()
  }
  loading.value = true
  try {
    const result = await knowledgeApi.search(query.keyword.trim())
    graph.value = result || { nodes: [], edges: [] }
    // 高亮匹配的节点
    highlightNames.value = graph.value.nodes.map((n) => String(n.name))
  } catch {
    graph.value = { nodes: [], edges: [] }
  } finally {
    loading.value = false
  }
}

// ---------- 统计信息 ----------
const statsLoading = ref(false)
const stats = ref<{
  total_nodes: number
  total_relations: number
  node_labels: string[]
}>({
  total_nodes: 0,
  total_relations: 0,
  node_labels: [],
})

async function fetchStats() {
  statsLoading.value = true
  try {
    const result = await knowledgeApi.getStats()
    stats.value = result || { total_nodes: 0, total_relations: 0, node_labels: [] }
  } catch {
    // 拦截器已处理错误提示
  } finally {
    statsLoading.value = false
  }
}

// ---------- 构建图谱对话框 ----------
const buildDialogVisible = ref(false)
const buildLoading = ref(false)
const buildSubmitting = ref(false)
const buildDocList = ref<DocType[]>([])
const selectedDocId = ref<string>('')

async function openBuildDialog() {
  buildDialogVisible.value = true
  selectedDocId.value = ''
  buildLoading.value = true
  try {
    // 仅展示已解析完成的文档（status=completed）
    const res = await documentApi.getList({ status: 'completed', page_size: 100 })
    buildDocList.value = res.items || []
  } catch {
    buildDocList.value = []
  } finally {
    buildLoading.value = false
  }
}

async function submitBuild() {
  if (!selectedDocId.value) {
    ElMessage.warning('请选择要构建图谱的文档')
    return
  }
  buildSubmitting.value = true
  try {
    const res = await knowledgeApi.buildGraph(selectedDocId.value)
    ElMessage.success(`图谱构建任务已提交，task_id: ${res.task_id}`)
    buildDialogVisible.value = false
    // 略微延迟后刷新统计
    setTimeout(() => {
      fetchStats()
      fetchGraph()
    }, 2000)
  } catch {
    // 拦截器已处理错误提示
  } finally {
    buildSubmitting.value = false
  }
}

// ---------- 重建全部图谱 ----------
async function handleRebuild() {
  try {
    const res = await knowledgeApi.rebuildGraph()
    ElMessage.success(`重建任务已提交，task_id: ${res.task_id}`)
    setTimeout(() => {
      fetchStats()
      fetchGraph()
    }, 2000)
  } catch {
    // 拦截器已处理错误提示
  }
}

// ---------- 节点交互 ----------
const selectedNode = ref<GraphNode | null>(null)

// 节点详情关联的边列表
const relatedEdges = computed<GraphEdge[]>(() => {
  if (!selectedNode.value) return []
  const name = String(selectedNode.value.name)
  return graph.value.edges.filter(
    (e) => String(e.source) === name || String(e.target) === name,
  )
})

async function handleNodeClick(node: GraphNode) {
  selectedNode.value = node
  // 获取以该节点为中心的 2 跳子图
  const name = String(node.name)
  if (!name) return
  loading.value = true
  try {
    const result = await knowledgeApi.getSubgraph(name, 2)
    graph.value = result || { nodes: [], edges: [] }
  } catch {
    // 失败时保留原图与节点详情
  } finally {
    loading.value = false
  }
}

// ---------- 右键上下文菜单 ----------
const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  node: null as GraphNode | null,
})

function handleNodeRightClick(node: GraphNode, position: { x: number; y: number }) {
  contextMenu.node = node
  contextMenu.x = position.x
  contextMenu.y = position.y
  contextMenu.visible = true
}

function closeContextMenu() {
  contextMenu.visible = false
}

// 从节点 properties 中提取 document_id
function getNodeDocId(node: GraphNode | null): string {
  if (!node) return ''
  const props = (node.properties || {}) as Record<string, unknown>
  // 兼容多种命名
  const raw =
    (props.document_id as string | undefined) ||
    (props.doc_id as string | undefined) ||
    (props.source_doc_id as string | undefined) ||
    ''
  return raw ? String(raw) : ''
}

const deleteDocId = ref<string>('')

async function confirmDeleteNodeGraph() {
  if (!contextMenu.node) return
  const docId = getNodeDocId(contextMenu.node)
  if (!docId) {
    ElMessage.warning('该节点未携带 document_id，无法定位所属文档图谱')
    closeContextMenu()
    return
  }
  deleteDocId.value = docId
  closeContextMenu()
}

// 删除确认弹窗触发
const deleteConfirmVisible = ref(false)
watch(deleteDocId, (val) => {
  if (val) deleteConfirmVisible.value = true
})

async function doDeleteGraph() {
  if (!deleteDocId.value) return
  try {
    const res = await knowledgeApi.deleteGraph(deleteDocId.value)
    ElMessage.success(`删除任务已提交，task_id: ${res.task_id}`)
    selectedNode.value = null
    setTimeout(() => {
      fetchStats()
      fetchGraph()
    }, 2000)
  } catch {
    // 拦截器已处理错误提示
  } finally {
    deleteConfirmVisible.value = false
    deleteDocId.value = ''
  }
}

// 关闭右键菜单：点击页面任意位置
function onDocumentClick() {
  if (contextMenu.visible) closeContextMenu()
}

// ---------- 节点属性表格 ----------
const nodeProperties = computed<Array<{ key: string; value: string }>>(() => {
  if (!selectedNode.value) return []
  const props = (selectedNode.value.properties || {}) as Record<string, unknown>
  return Object.entries(props).map(([key, value]) => ({
    key,
    value: typeof value === 'object' ? JSON.stringify(value) : String(value ?? ''),
  }))
})

// ---------- 初始化 ----------
onMounted(() => {
  fetchGraph()
  fetchStats()
  document.addEventListener('click', onDocumentClick)
})
</script>

<template>
  <div class="knowledge">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">知识图谱</h2>
        <p class="page-desc">文档实体与关系的可视化网络</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openBuildDialog">
          <el-icon><Plus /></el-icon>
          <span>构建图谱</span>
        </el-button>
        <el-popconfirm
          title="确定重建全部知识图谱？该操作可能耗时较长"
          confirm-button-text="重建"
          cancel-button-text="取消"
          confirm-button-type="warning"
          @confirm="handleRebuild"
        >
          <template #reference>
            <el-button type="warning" plain>
              <el-icon><Refresh /></el-icon>
              <span>重建全部图谱</span>
            </el-button>
          </template>
        </el-popconfirm>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="bp-card stat-card">
        <div class="stat-icon stat-nodes">
          <el-icon><DataLine /></el-icon>
        </div>
        <div class="stat-meta">
          <div class="stat-label">节点总数</div>
          <div class="stat-value mono" v-loading="statsLoading">
            {{ stats.total_nodes }}
          </div>
        </div>
      </div>
      <div class="bp-card stat-card">
        <div class="stat-icon stat-edges">
          <el-icon><DataLine /></el-icon>
        </div>
        <div class="stat-meta">
          <div class="stat-label">关系总数</div>
          <div class="stat-value mono" v-loading="statsLoading">
            {{ stats.total_relations }}
          </div>
        </div>
      </div>
      <div class="bp-card stat-card stat-card-wide">
        <div class="stat-icon stat-labels">
          <el-icon><DataLine /></el-icon>
        </div>
        <div class="stat-meta">
          <div class="stat-label">标签分布</div>
          <div class="label-cloud" v-loading="statsLoading">
            <el-tag
              v-for="lb in stats.node_labels"
              :key="lb"
              class="label-chip"
              size="small"
              effect="plain"
              round
            >
              {{ lb }}
            </el-tag>
            <span v-if="!stats.node_labels.length" class="empty-hint mono">
              暂无标签
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 搜索 -->
    <div class="bp-card filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索节点（文档、术语、标准）"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" @click="handleSearch">搜索</el-button>
    </div>

    <!-- 主体：图谱 + 侧边栏 -->
    <div class="main-grid">
      <!-- 图谱画布 -->
      <div class="bp-card graph-card">
        <div class="graph-header">
          <span class="graph-title">图谱视图</span>
          <div class="graph-stats mono">
            <span class="stat-item">节点 <strong>{{ graph.nodes.length }}</strong></span>
            <span class="stat-item">关系 <strong>{{ graph.edges.length }}</strong></span>
          </div>
        </div>
        <div class="graph-canvas" v-loading="loading">
          <GraphViewer
            v-if="graph.nodes.length"
            :nodes="graph.nodes"
            :edges="graph.edges"
            :highlight-names="highlightNames"
            @node-click="handleNodeClick"
            @node-right-click="handleNodeRightClick"
          />
          <div v-else class="graph-empty-wrapper">
            <el-empty
              description="暂无图谱数据，请先解析文档后构建知识图谱"
              :image-size="100"
            />
          </div>
        </div>
      </div>

      <!-- 侧边栏节点详情 -->
      <div class="bp-card side-card">
        <div class="side-header">
          <span class="side-title">节点详情</span>
        </div>
        <div v-if="!selectedNode" class="side-empty">
          <el-empty description="点击节点查看详情" :image-size="80" />
        </div>
        <div v-else class="side-content">
          <div class="detail-section">
            <div class="detail-label">节点名称</div>
            <div class="detail-value mono">{{ selectedNode.name || '—' }}</div>
          </div>
          <div class="detail-section">
            <div class="detail-label">标签</div>
            <div class="label-list">
              <el-tag
                v-for="lb in (selectedNode.labels || [])"
                :key="lb"
                size="small"
                effect="plain"
                round
              >
                {{ lb }}
              </el-tag>
              <span v-if="!selectedNode.labels?.length" class="empty-hint mono">—</span>
            </div>
          </div>
          <div class="detail-section">
            <div class="detail-label">类型</div>
            <div class="detail-value mono">{{ selectedNode.type || selectedNode.label || '—' }}</div>
          </div>
          <div class="detail-section">
            <div class="detail-label">属性</div>
            <el-table
              :data="nodeProperties"
              size="small"
              border
              max-height="220"
              empty-text="无属性"
            >
              <el-table-column prop="key" label="键" width="100" />
              <el-table-column prop="value" label="值" show-overflow-tooltip />
            </el-table>
          </div>
          <div class="detail-section">
            <div class="detail-label">
              关联关系
              <span class="rel-count mono">({{ relatedEdges.length }})</span>
            </div>
            <div class="rel-list">
              <div v-for="(edge, idx) in relatedEdges" :key="idx" class="rel-item">
                <span class="rel-node mono">{{ edge.source }}</span>
                <el-tag size="small" type="info" effect="plain">{{ edge.type }}</el-tag>
                <span class="rel-node mono">{{ edge.target }}</span>
              </div>
              <div v-if="!relatedEdges.length" class="empty-hint mono">暂无关联关系</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 构建图谱对话框 -->
    <el-dialog
      v-model="buildDialogVisible"
      title="构建知识图谱"
      width="520px"
    >
      <el-form label-width="80px" label-position="left">
        <el-form-item label="文档" required>
          <el-select
            v-model="selectedDocId"
            placeholder="请选择已解析完成的文档"
            filterable
            style="width: 100%"
            :loading="buildLoading"
          >
            <el-option
              v-for="doc in buildDocList"
              :key="doc.id"
              :label="doc.title"
              :value="String(doc.id)"
            >
              <div class="doc-option">
                <span class="doc-option-title">{{ doc.title }}</span>
                <span class="doc-option-meta mono">{{ doc.standard_number || '—' }}</span>
              </div>
            </el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="buildDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="buildSubmitting" @click="submitBuild">
          确认构建
        </el-button>
      </template>
    </el-dialog>

    <!-- 删除确认对话框 -->
    <el-dialog
      v-model="deleteConfirmVisible"
      title="删除文档图谱"
      width="420px"
    >
      <div class="delete-confirm">
        <el-icon class="delete-icon"><Delete /></el-icon>
        <p class="delete-text">
          即将删除文档 <code class="mono">{{ deleteDocId }}</code> 关联的全部图谱数据，
          该操作不可恢复，是否继续？
        </p>
      </div>
      <template #footer>
        <el-button @click="deleteConfirmVisible = false">取消</el-button>
        <el-button type="danger" @click="doDeleteGraph">确认删除</el-button>
      </template>
    </el-dialog>

    <!-- 右键上下文菜单 -->
    <div
      v-if="contextMenu.visible"
      class="context-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      @click.stop
    >
      <div class="context-menu-header">
        {{ contextMenu.node?.name }}
      </div>
      <div class="context-menu-item" @click="confirmDeleteNodeGraph">
        <el-icon><Delete /></el-icon>
        <span>删除该文档图谱</span>
      </div>
      <div
        v-if="!getNodeDocId(contextMenu.node)"
        class="context-menu-tip mono"
      >
        节点未携带 document_id
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use 'sass:color';

.knowledge {
  position: relative;
}

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
    gap: 12px;
  }
}

// ---------- 统计卡片 ----------
.stats-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr) 2fr;
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;

  &.stat-card-wide {
    .stat-meta {
      flex: 1;
      min-width: 0;
    }
  }

  .stat-icon {
    width: 44px;
    height: 44px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    flex-shrink: 0;

    &.stat-nodes {
      background-color: rgba(74, 163, 255, 0.15);
      color: #4aa3ff;
    }
    &.stat-edges {
      background-color: rgba(82, 196, 26, 0.15);
      color: #52c41a;
    }
    &.stat-labels {
      background-color: rgba(250, 140, 22, 0.15);
      color: #fa8c16;
    }
  }

  .stat-meta {
    flex: 1;
    min-width: 0;
  }

  .stat-label {
    font-size: var(--fs-xs);
    color: var(--text-secondary);
    margin-bottom: 4px;
  }

  .stat-value {
    font-size: var(--fs-xl);
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.2;
  }
}

.label-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;

  .label-chip {
    font-size: var(--fs-xs);
  }
}

.empty-hint {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}

// ---------- 搜索栏 ----------
.filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;
}

// ---------- 主体网格 ----------
.main-grid {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 16px;
  align-items: stretch;
}

.graph-card {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.graph-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-base);

  .graph-title {
    font-weight: 600;
    color: var(--text-primary);
  }

  .graph-stats {
    display: flex;
    gap: 20px;
    font-size: var(--fs-xs);
    color: var(--text-secondary);

    strong {
      color: var(--accent-primary);
      font-weight: 600;
      margin-left: 4px;
    }
  }
}

.graph-canvas {
  height: calc(100vh - 460px);
  min-height: 420px;
  background-color: var(--bg-base);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  position: relative;
}

.graph-empty-wrapper {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

// ---------- 侧边栏 ----------
.side-card {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 460px);
  min-height: 420px;
  overflow: hidden;
}

.side-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-base);

  .side-title {
    font-weight: 600;
    color: var(--text-primary);
  }
}

.side-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.side-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.detail-section {
  margin-bottom: 18px;

  .detail-label {
    font-size: var(--fs-xs);
    color: var(--text-secondary);
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;

    .rel-count {
      color: var(--accent-primary);
    }
  }

  .detail-value {
    font-size: var(--fs-sm);
    color: var(--text-primary);
    word-break: break-all;
  }
}

.label-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rel-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-xs);
  padding: 6px 8px;
  background: var(--bg-base);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-light);

  .rel-node {
    flex: 1;
    color: var(--text-primary);
    word-break: break-all;
    min-width: 0;
  }
}

// ---------- 构建对话框 ----------
.doc-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;

  .doc-option-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .doc-option-meta {
    font-size: var(--fs-xs);
    color: var(--text-muted);
    flex-shrink: 0;
  }
}

// ---------- 删除确认 ----------
.delete-confirm {
  display: flex;
  align-items: flex-start;
  gap: 12px;

  .delete-icon {
    font-size: 24px;
    color: var(--accent-danger, #ff4d4f);
    flex-shrink: 0;
    margin-top: 2px;
  }

  .delete-text {
    margin: 0;
    color: var(--text-primary);
    line-height: 1.6;

    code {
      color: var(--accent-primary);
      background: var(--bg-base);
      padding: 2px 6px;
      border-radius: var(--radius-sm);
    }
  }
}

// ---------- 右键菜单 ----------
.context-menu {
  position: fixed;
  z-index: 3000;
  min-width: 200px;
  background: var(--bg-surface, #1a2332);
  border: 1px solid var(--border-base, #2a3548);
  border-radius: var(--radius-md, 6px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  padding: 4px;

  .context-menu-header {
    padding: 8px 12px;
    font-size: var(--fs-sm);
    color: var(--text-primary);
    border-bottom: 1px solid var(--border-light, #1f2a3a);
    margin-bottom: 4px;
    font-weight: 600;
    word-break: break-all;
  }

  .context-menu-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    color: var(--text-primary);
    font-size: var(--fs-sm);
    cursor: pointer;
    border-radius: var(--radius-sm, 4px);
    transition: background-color 0.15s;

    &:hover {
      background-color: var(--bg-base, #0f1623);
      color: var(--accent-danger, #ff4d4f);
    }
  }

  .context-menu-tip {
    padding: 6px 12px;
    font-size: var(--fs-xs);
    color: var(--text-muted);
  }
}

// ---------- 响应式 ----------
@media (max-width: 1100px) {
  .main-grid {
    grid-template-columns: 1fr;
  }

  .side-card {
    max-height: none;
    min-height: 0;
  }

  .stats-row {
    grid-template-columns: 1fr 1fr;
  }

  .stat-card-wide {
    grid-column: span 2;
  }
}
</style>
