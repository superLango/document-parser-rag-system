<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { documentApi } from '@/api/modules/document'
import type { Document as Doc } from '@/api/types'

const route = useRoute()
const docId = Number(route.params.id)

const loading = ref(true)
const document = ref<Doc | null>(null)
const activeTab = ref('extracted')

async function fetchDocument() {
  loading.value = true
  try {
    document.value = await documentApi.getDetail(docId)
  } catch {
    document.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchDocument)
</script>

<template>
  <div class="parser">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">解析查看</h2>
        <p class="page-desc">
          <span class="mono" v-if="document">DOC-{{ document.id }}</span>
          <span v-else>加载中…</span>
        </p>
      </div>
    </div>

    <!-- 双栏布局 -->
    <div class="parser-grid">
      <!-- 左栏：文档预览占位 -->
      <div class="bp-card viewer-pane">
        <div class="pane-header">
          <span class="pane-title">文档预览</span>
          <span class="mono pane-meta" v-if="document">{{ document.page_count }} 页</span>
        </div>
        <div class="pane-body viewer-body" v-loading="loading">
          <div v-if="document" class="pdf-placeholder">
            <div class="placeholder-page" v-for="i in Math.min(document.page_count, 3)" :key="i">
              <div class="page-line" v-for="l in 8" :key="l" :style="{ width: `${60 + (l * 4) % 35}%` }"></div>
            </div>
          </div>
          <el-empty v-else description="无法加载文档" :image-size="60" />
        </div>
      </div>

      <!-- 右栏：解析结果 -->
      <div class="bp-card result-pane">
        <div class="pane-header">
          <el-tabs v-model="activeTab" class="result-tabs">
            <el-tab-pane label="抽取数据" name="extracted" />
            <el-tab-pane label="原始文本" name="text" />
            <el-tab-pane label="结构化" name="structured" />
          </el-tabs>
        </div>
        <div class="pane-body result-body" v-loading="loading">
          <template v-if="activeTab === 'extracted'">
            <div class="result-section">
              <div class="section-label mono">STANDARD</div>
              <div class="section-content">{{ document?.standard_number || '—' }}</div>
            </div>
            <div class="result-section">
              <div class="section-label mono">TITLE</div>
              <div class="section-content">{{ document?.title || '—' }}</div>
            </div>
            <div class="result-section">
              <div class="section-label mono">TYPE</div>
              <div class="section-content">{{ document?.doc_type || '—' }}</div>
            </div>
          </template>
          <template v-else-if="activeTab === 'text'">
            <div class="raw-text mono">等待解析完成后显示原始文本内容…</div>
          </template>
          <template v-else>
            <div class="raw-text">等待解析完成后显示结构化数据…</div>
          </template>
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

.parser-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  height: calc(100vh - 200px);
  min-height: 400px;
}

.pane-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-base);

  .pane-title {
    font-weight: 600;
    color: var(--text-primary);
  }

  .pane-meta {
    font-size: var(--fs-xs);
    color: var(--text-muted);
  }
}

.pane-body {
  padding: 20px;
  overflow-y: auto;
  height: calc(100% - 49px);
}

// 文档预览占位
.viewer-body {
  background-color: var(--bg-base);
}

.pdf-placeholder {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: center;
}

.placeholder-page {
  width: 100%;
  max-width: 420px;
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-sm);
  padding: 24px 20px;

  .page-line {
    height: 8px;
    background: var(--border-base);
    border-radius: 2px;
    margin-bottom: 12px;
  }
}

// 结果面板
.result-tabs {
  flex: 1;

  :deep(.el-tabs__header) {
    margin: 0;
  }
  :deep(.el-tabs__nav-wrap)::after {
    background-color: var(--border-base);
  }
}

.result-section {
  margin-bottom: 20px;

  .section-label {
    font-size: var(--fs-xs);
    color: var(--accent-primary);
    margin-bottom: 6px;
    letter-spacing: 0.05em;
  }

  .section-content {
    font-size: var(--fs-sm);
    color: var(--text-primary);
    padding: 8px 12px;
    background: var(--bg-base);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-light);
  }
}

.raw-text {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  line-height: 1.7;
}
</style>
