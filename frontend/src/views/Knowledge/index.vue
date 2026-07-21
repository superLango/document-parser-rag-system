<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import {
  Search,
  Plus,
  RefreshCw,
  Trash2,
  Share2,
  Network,
  GitBranch,
  Tag,
  Loader2,
  AlertTriangle,
  X,
  MousePointerClick,
} from 'lucide-vue-next'
import { knowledgeApi } from '@/api/modules/knowledge'
import { documentApi } from '@/api/modules/document'
import type { KnowledgeGraph, GraphNode, GraphEdge, Document as DocType } from '@/api/types'
import GraphViewer from '@/components/GraphViewer.vue'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'

// ---------- 图谱数据 ----------
const loading = ref(true)
const graph = ref<KnowledgeGraph>({ nodes: [], edges: [] })
const query = reactive({ keyword: '' })
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
    highlightNames.value = graph.value.nodes.map((n) => String(n.name))
  } catch {
    graph.value = { nodes: [], edges: [] }
  } finally {
    loading.value = false
  }
}

// ---------- 统计 ----------
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
    // 错误已处理
  } finally {
    statsLoading.value = false
  }
}

// ---------- 构建图谱 ----------
const buildDialogVisible = ref(false)
const buildLoading = ref(false)
const buildSubmitting = ref(false)
const buildDocList = ref<DocType[]>([])
const ALL_DOC_VALUE = '__none__'
const selectedDocId = ref<string>(ALL_DOC_VALUE)

const docOptions = computed(() => [
  { value: ALL_DOC_VALUE, label: '请选择文档' },
  ...buildDocList.value.map((d) => ({
    value: String(d.id),
    label: d.filename,
  })),
])

async function openBuildDialog() {
  buildDialogVisible.value = true
  selectedDocId.value = ALL_DOC_VALUE
  buildLoading.value = true
  try {
    const res = await documentApi.getList({ status: 'completed', page_size: 100 })
    buildDocList.value = res.items || []
  } catch {
    buildDocList.value = []
  } finally {
    buildLoading.value = false
  }
}

async function submitBuild() {
  if (selectedDocId.value === ALL_DOC_VALUE) {
    toast.warning('请选择文档', '需要选择已解析完成的文档')
    return
  }
  buildSubmitting.value = true
  try {
    const res = await knowledgeApi.buildGraph(selectedDocId.value)
    toast.success('已提交', `图谱构建任务已提交（task_id: ${res.task_id}）`)
    buildDialogVisible.value = false
    setTimeout(() => {
      fetchStats()
      fetchGraph()
    }, 2000)
  } catch {
    // 错误已处理
  } finally {
    buildSubmitting.value = false
  }
}

// ---------- 重建全部 ----------
const rebuildDialogVisible = ref(false)
const rebuilding = ref(false)

async function confirmRebuild() {
  rebuilding.value = true
  try {
    const res = await knowledgeApi.rebuildGraph()
    toast.success('已提交', `重建任务已提交（task_id: ${res.task_id}）`)
    rebuildDialogVisible.value = false
    setTimeout(() => {
      fetchStats()
      fetchGraph()
    }, 2000)
  } catch {
    // 错误已处理
  } finally {
    rebuilding.value = false
  }
}

// ---------- 节点交互 ----------
const selectedNode = ref<GraphNode | null>(null)

const relatedEdges = computed<GraphEdge[]>(() => {
  if (!selectedNode.value) return []
  const name = String(selectedNode.value.name)
  return graph.value.edges.filter(
    (e) => String(e.source) === name || String(e.target) === name,
  )
})

const nodeProperties = computed<Array<{ key: string; value: string }>>(() => {
  if (!selectedNode.value) return []
  const props = (selectedNode.value.properties || {}) as Record<string, unknown>
  return Object.entries(props).map(([key, value]) => ({
    key,
    value: typeof value === 'object' ? JSON.stringify(value) : String(value ?? ''),
  }))
})

async function handleNodeClick(node: GraphNode) {
  selectedNode.value = node
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

function getNodeDocId(node: GraphNode | null): string {
  if (!node) return ''
  const props = (node.properties || {}) as Record<string, unknown>
  const raw =
    (props.document_id as string | undefined) ||
    (props.doc_id as string | undefined) ||
    (props.source_doc_id as string | undefined) ||
    ''
  return raw ? String(raw) : ''
}

const deleteDocId = ref<string>('')
const deleteDialogVisible = ref(false)

function openDeleteFromContext() {
  if (!contextMenu.node) return
  const docId = getNodeDocId(contextMenu.node)
  if (!docId) {
    toast.warning('无法删除', '该节点未携带 document_id，无法定位所属文档图谱')
    closeContextMenu()
    return
  }
  deleteDocId.value = docId
  closeContextMenu()
  deleteDialogVisible.value = true
}

async function confirmDeleteGraph() {
  if (!deleteDocId.value) return
  try {
    const res = await knowledgeApi.deleteGraph(deleteDocId.value)
    toast.success('已提交', `删除任务已提交（task_id: ${res.task_id}）`)
    selectedNode.value = null
    deleteDialogVisible.value = false
    setTimeout(() => {
      fetchStats()
      fetchGraph()
    }, 2000)
  } catch {
    // 错误已处理
  } finally {
    deleteDocId.value = ''
  }
}

function onDocumentClick() {
  if (contextMenu.visible) closeContextMenu()
}

onMounted(() => {
  fetchGraph()
  fetchStats()
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
})
</script>

<template>
  <div class="relative">
    <PageHeader title="知识图谱" description="文档实体与关系的可视化网络">
      <template #actions>
        <Button variant="outline" @click="rebuildDialogVisible = true">
          <RefreshCw class="size-4" :stroke-width="1.5" />
          重建全部
        </Button>
        <Button @click="openBuildDialog">
          <Plus class="size-4" :stroke-width="1.5" />
          构建图谱
        </Button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div class="mb-4 grid grid-cols-1 gap-4 md:grid-cols-3">
      <Card>
        <CardContent class="flex items-center gap-3 p-4">
          <div class="flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Network class="size-5" :stroke-width="1.5" />
          </div>
          <div class="flex-1">
            <p class="text-xs text-muted-foreground">节点总数</p>
            <Skeleton v-if="statsLoading" class="mt-1 h-6 w-16" />
            <p v-else class="font-mono text-2xl font-semibold text-foreground">
              {{ stats.total_nodes }}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent class="flex items-center gap-3 p-4">
          <div class="flex size-10 items-center justify-center rounded-md bg-success/10 text-success">
            <GitBranch class="size-5" :stroke-width="1.5" />
          </div>
          <div class="flex-1">
            <p class="text-xs text-muted-foreground">关系总数</p>
            <Skeleton v-if="statsLoading" class="mt-1 h-6 w-16" />
            <p v-else class="font-mono text-2xl font-semibold text-foreground">
              {{ stats.total_relations }}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent class="p-4">
          <div class="flex items-center gap-3">
            <div class="flex size-10 items-center justify-center rounded-md bg-warning/10 text-warning">
              <Tag class="size-5" :stroke-width="1.5" />
            </div>
            <div class="flex-1">
              <p class="text-xs text-muted-foreground">标签分布</p>
              <Skeleton v-if="statsLoading" class="mt-1 h-6 w-full" />
              <p v-else-if="!stats.node_labels.length" class="text-sm text-muted-foreground">
                暂无标签
              </p>
            </div>
          </div>
          <div
            v-if="!statsLoading && stats.node_labels.length"
            class="mt-2 flex flex-wrap gap-1"
          >
            <Badge
              v-for="lb in stats.node_labels"
              :key="lb"
              variant="outline"
              class="text-[10px]"
            >
              {{ lb }}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 搜索栏 -->
    <Card class="mb-4">
      <CardContent class="flex gap-2 p-3">
        <div class="relative flex-1">
          <Search
            class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            :stroke-width="1.5"
          />
          <Input
            v-model="query.keyword"
            placeholder="搜索节点（文档、术语、标准）"
            class="pl-9"
            @keyup.enter="handleSearch"
          />
        </div>
        <Button class="sm:w-[88px]" @click="handleSearch">
          <Search class="size-4" :stroke-width="1.5" />
          搜索
        </Button>
      </CardContent>
    </Card>

    <!-- 主体：图谱 + 侧边栏 -->
    <div class="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_360px]">
      <!-- 图谱画布 -->
      <Card class="flex flex-col overflow-hidden">
        <div
          class="flex items-center justify-between border-b border-border px-4 py-3"
        >
          <div class="flex items-center gap-2">
            <Share2 class="size-4 text-primary" :stroke-width="1.5" />
            <span class="text-sm font-medium text-foreground">图谱视图</span>
          </div>
          <div class="flex items-center gap-4 text-xs text-muted-foreground">
            <span>
              节点
              <strong class="ml-1 font-mono text-primary">{{ graph.nodes.length }}</strong>
            </span>
            <span>
              关系
              <strong class="ml-1 font-mono text-primary">{{ graph.edges.length }}</strong>
            </span>
          </div>
        </div>

        <div class="relative min-h-[480px] flex-1 bg-muted/20">
          <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-background/60">
            <Loader2 class="size-6 animate-spin text-primary" :stroke-width="1.5" />
          </div>

          <GraphViewer
            v-if="graph.nodes.length"
            :nodes="graph.nodes"
            :edges="graph.edges"
            :highlight-names="highlightNames"
            @node-click="handleNodeClick"
            @node-right-click="handleNodeRightClick"
          />

          <div v-else-if="!loading" class="absolute inset-0 flex items-center justify-center">
            <EmptyState
              :icon="Share2"
              title="暂无图谱数据"
              description="请先解析文档后构建知识图谱"
            />
          </div>
        </div>
      </Card>

      <!-- 侧边栏节点详情 -->
      <Card class="flex flex-col overflow-hidden">
        <div class="border-b border-border px-4 py-3">
          <div class="flex items-center gap-2">
            <MousePointerClick class="size-4 text-primary" :stroke-width="1.5" />
            <span class="text-sm font-medium text-foreground">节点详情</span>
          </div>
        </div>

        <div v-if="!selectedNode" class="flex flex-1 items-center justify-center p-8">
          <EmptyState
            :icon="MousePointerClick"
            title="点击节点查看详情"
            description="点击图谱中的节点查看详细信息与关联关系"
          />
        </div>

        <div v-else class="flex-1 overflow-y-auto p-4">
          <!-- 节点名称 -->
          <div class="mb-4">
            <p class="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              节点名称
            </p>
            <p class="break-all font-mono text-sm font-medium text-foreground">
              {{ selectedNode.name || '-' }}
            </p>
          </div>

          <!-- 标签 -->
          <div class="mb-4">
            <p class="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              标签
            </p>
            <div v-if="selectedNode.labels?.length" class="flex flex-wrap gap-1">
              <Badge
                v-for="lb in selectedNode.labels"
                :key="lb"
                variant="secondary"
                class="text-[10px]"
              >
                {{ lb }}
              </Badge>
            </div>
            <span v-else class="text-sm text-muted-foreground">-</span>
          </div>

          <!-- 类型 -->
          <div class="mb-4">
            <p class="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              类型
            </p>
            <p class="font-mono text-sm text-foreground">
              {{ selectedNode.type || selectedNode.label || '-' }}
            </p>
          </div>

          <!-- 属性 -->
          <div class="mb-4">
            <p class="mb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              属性
            </p>
            <div
              v-if="nodeProperties.length"
              class="overflow-hidden rounded-md border border-border"
            >
              <div class="divide-y divide-border">
                <div
                  v-for="prop in nodeProperties"
                  :key="prop.key"
                  class="grid grid-cols-3 gap-2 px-2 py-1.5 text-xs"
                >
                  <span class="font-mono text-muted-foreground">{{ prop.key }}</span>
                  <span class="col-span-2 break-all text-foreground" :title="prop.value">
                    {{ prop.value }}
                  </span>
                </div>
              </div>
            </div>
            <p v-else class="text-sm text-muted-foreground">无属性</p>
          </div>

          <!-- 关联关系 -->
          <div>
            <div class="mb-1.5 flex items-center gap-2">
              <p class="text-[10px] uppercase tracking-wide text-muted-foreground">
                关联关系
              </p>
              <Badge variant="secondary" class="text-[10px]">
                {{ relatedEdges.length }}
              </Badge>
            </div>
            <div v-if="relatedEdges.length" class="space-y-1.5">
              <div
                v-for="(edge, idx) in relatedEdges"
                :key="idx"
                class="flex items-center gap-2 rounded-md border border-border bg-muted/20 p-2 text-xs"
              >
                <span class="flex-1 break-all font-mono text-foreground" :title="edge.source">
                  {{ edge.source }}
                </span>
                <Badge variant="outline" class="shrink-0 text-[10px]">
                  {{ edge.type }}
                </Badge>
                <span class="flex-1 break-all text-right font-mono text-foreground" :title="edge.target">
                  {{ edge.target }}
                </span>
              </div>
            </div>
            <p v-else class="text-sm text-muted-foreground">暂无关联关系</p>
          </div>
        </div>
      </Card>
    </div>

    <!-- 构建图谱 Dialog -->
    <Dialog
      :open="buildDialogVisible"
      title="构建知识图谱"
      description="选择已解析完成的文档构建图谱"
      class="max-w-lg"
      @update:open="(v) => (buildDialogVisible = v)"
    >
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>选择文档 <span class="text-danger">*</span></Label>
          <Select
            v-model="selectedDocId"
            :options="docOptions"
            placeholder="请选择文档"
            :disabled="buildLoading"
          />
        </div>

        <div v-if="buildDocList.length" class="rounded-md border border-border bg-muted/20 p-3">
          <p class="text-xs font-medium text-muted-foreground">
            已解析文档共 {{ buildDocList.length }} 个
          </p>
        </div>

        <div class="flex items-start gap-3 rounded-md border border-primary/30 bg-primary/5 p-3">
          <AlertTriangle class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
          <p class="text-xs text-muted-foreground">
            构建图谱会从文档抽取实体与关系并写入 Neo4j。该任务异步执行，完成后图谱视图会自动刷新。
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="buildDialogVisible = false">取消</Button>
        <Button
          :disabled="buildSubmitting || selectedDocId === ALL_DOC_VALUE"
          @click="submitBuild"
        >
          <Loader2 v-if="buildSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ buildSubmitting ? '提交中...' : '确认构建' }}
        </Button>
      </div>
    </Dialog>

    <!-- 重建全部 Dialog -->
    <Dialog
      :open="rebuildDialogVisible"
      title="重建全部知识图谱"
      description="该操作将清空现有图谱并重新构建"
      @update:open="(v) => (rebuildDialogVisible = v)"
    >
      <div class="flex items-start gap-3 rounded-md border border-warning/30 bg-warning/5 p-3">
        <AlertTriangle class="mt-0.5 size-4 shrink-0 text-warning" :stroke-width="1.5" />
        <div class="flex-1 space-y-1 text-sm">
          <p class="font-medium text-foreground">确认重建全部图谱？</p>
          <p class="text-xs text-muted-foreground">
            该操作将清空所有现有图谱数据，重新扫描所有已解析文档并构建图谱。任务异步执行，可能耗时较长。
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="rebuildDialogVisible = false">取消</Button>
        <Button
          variant="destructive"
          :disabled="rebuilding"
          @click="confirmRebuild"
        >
          <Loader2 v-if="rebuilding" class="size-4 animate-spin" :stroke-width="1.5" />
          <RefreshCw v-else class="size-4" :stroke-width="1.5" />
          确认重建
        </Button>
      </div>
    </Dialog>

    <!-- 删除确认 Dialog -->
    <Dialog
      :open="deleteDialogVisible"
      title="删除文档图谱"
      description="将删除该文档关联的全部图谱数据"
      @update:open="(v) => (deleteDialogVisible = v)"
    >
      <div class="flex items-start gap-3 rounded-md border border-danger/30 bg-danger/5 p-3">
        <X class="mt-0.5 size-4 shrink-0 text-danger" :stroke-width="1.5" />
        <div class="flex-1 space-y-1 text-sm">
          <p class="text-foreground">
            即将删除文档
            <code class="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-xs text-danger">
              {{ deleteDocId }}
            </code>
            关联的全部图谱数据
          </p>
          <p class="text-xs text-muted-foreground">
            该操作不可恢复，是否继续？
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="deleteDialogVisible = false">取消</Button>
        <Button variant="destructive" @click="confirmDeleteGraph">
          <Trash2 class="size-4" :stroke-width="1.5" />
          确认删除
        </Button>
      </div>
    </Dialog>

    <!-- 右键上下文菜单 -->
    <Teleport to="body">
      <div
        v-if="contextMenu.visible"
        class="fixed z-[2000] min-w-[200px] rounded-md border border-border bg-popover p-1 shadow-lg"
        :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
        @click.stop
      >
        <div class="border-b border-border px-3 py-2">
          <p class="break-all text-sm font-medium text-foreground">
            {{ contextMenu.node?.name }}
          </p>
        </div>
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
          @click="openDeleteFromContext"
        >
          <Trash2 class="size-4" :stroke-width="1.5" />
          删除该文档图谱
        </button>
        <p
          v-if="!getNodeDocId(contextMenu.node)"
          class="px-3 py-1.5 text-[10px] text-muted-foreground"
        >
          节点未携带 document_id
        </p>
      </div>
    </Teleport>
  </div>
</template>
