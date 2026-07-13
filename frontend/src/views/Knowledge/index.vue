<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { knowledgeApi } from '@/api/modules/knowledge'
import type { KnowledgeGraph } from '@/api/types'

const loading = ref(true)
const graph = ref<KnowledgeGraph>({ nodes: [], edges: [] })

const query = reactive({
  keyword: '',
})

async function fetchGraph() {
  loading.value = true
  try {
    const result = await knowledgeApi.getGraph({ limit: 50 })
    graph.value = result || { nodes: [], edges: [] }
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
    const result = await knowledgeApi.search(query.keyword)
    graph.value = result || { nodes: [], edges: [] }
  } catch {
    graph.value = { nodes: [], edges: [] }
  } finally {
    loading.value = false
  }
}

onMounted(fetchGraph)
</script>

<template>
  <div class="knowledge">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">知识图谱</h2>
        <p class="page-desc">文档实体与关系的可视化网络</p>
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
        <!-- Cytoscape 集成占位 -->
        <div class="graph-placeholder">
          <div class="placeholder-grid">
            <div
              v-for="n in Math.min(graph.nodes.length, 0)"
              :key="n"
              class="placeholder-node"
            ></div>
          </div>
          <el-empty v-if="!loading && !graph.nodes.length" description="暂无图谱数据，请先解析文档构建知识图谱" :image-size="100" />
          <div v-else-if="!loading && graph.nodes.length" class="graph-hint mono">
            <span>图谱渲染组件（Cytoscape）集成预留位</span>
          </div>
        </div>
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
}

.graph-card {
  overflow: hidden;
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
  height: calc(100vh - 280px);
  min-height: 400px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
}

.graph-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.graph-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
</style>
