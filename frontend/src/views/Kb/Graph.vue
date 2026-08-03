<script setup lang="ts">
/**
 * 知识库知识图谱可视化
 *
 * 功能：图谱展示/节点搜索/子图查询/统计/构建/重建/删除
 * 数据隔离：/kbs/{kb_id}/graph，后端按 KB 分 graph space
 * 权限：viewer 可查看；editor+ 可构建/重建/删除
 *
 * 复用 components/GraphViewer.vue（cytoscape）
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Share2,
  RefreshCw,
  Loader2,
  Search,
  Maximize2,
  Trash2,
  Hammer,
  Layers,
  X,
  Network,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import GraphViewer from '@/components/GraphViewer.vue'
import type { GraphNode, GraphEdge } from '@/api/types'

const route = useRoute()
const kbStore = useKbStore()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const loading = ref(true)
const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const stats = ref<Record<string, unknown> | null>(null)
const highlightNames = ref<string[]>([])
const searchKeyword = ref('')
const searching = ref(false)

// 选中节点
const selectedNode = ref<GraphNode | null>(null)
const drawerOpen = ref(false)

// 图谱查看器引用
const graphViewerRef = ref<InstanceType<typeof GraphViewer> | null>(null)

/** 将 API 返回的原始节点转换为 GraphNode */
function mapNode(raw: Record<string, unknown>): GraphNode {
  return {
    id: String(raw.id ?? raw.vid ?? raw.name ?? ''),
    name: String(raw.name ?? raw.id ?? ''),
    labels: Array.isArray(raw.labels) ? raw.labels as string[] : (raw.label ? [String(raw.label)] : ['Entity']),
    type: raw.type ? String(raw.type) : undefined,
    label: raw.label ? String(raw.label) : undefined,
    properties: raw.properties as Record<string, unknown> | undefined,
  }
}

/** 将 API 返回的原始边转换为 GraphEdge */
function mapEdge(raw: Record<string, unknown>): GraphEdge {
  return {
    source: String(raw.source ?? raw.from ?? ''),
    target: String(raw.target ?? raw.to ?? ''),
    type: String(raw.type ?? raw.rel_type ?? 'RELATED_TO'),
    label: raw.rel_type ? String(raw.rel_type) : undefined,
    id: raw.id ? String(raw.id) : undefined,
  }
}

async function fetchGraph() {
  loading.value = true
  try {
    const res = await kbApi.getGraph(kbId.value, 100)
    nodes.value = (res.nodes as Record<string, unknown>[]).map(mapNode)
    edges.value = (res.edges as Record<string, unknown>[]).map(mapEdge)
  } catch {
    nodes.value = []
    edges.value = []
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    stats.value = await kbApi.graphStats(kbId.value)
  } catch {
    stats.value = null
  }
}

async function handleSearch() {
  if (!searchKeyword.value.trim()) {
    highlightNames.value = []
    return
  }
  searching.value = true
  try {
    const res = await kbApi.searchGraphNodes(kbId.value, {
      name: searchKeyword.value,
      limit: 20,
    })
    const searchNodes = (res.nodes as Record<string, unknown>[]).map(mapNode)
    highlightNames.value = searchNodes.map((n) => n.name)
    if (searchNodes.length === 0) {
      toast.info('未找到匹配节点')
    }
  } catch {
    // 错误已由拦截器提示
  } finally {
    searching.value = false
  }
}

function clearSearch() {
  searchKeyword.value = ''
  highlightNames.value = []
}

function onNodeClick(node: GraphNode) {
  selectedNode.value = node
  drawerOpen.value = true
}

function fitView() {
  graphViewerRef.value?.fit()
}

async function rebuildGraph() {
  if (!confirm('确定重建整个知识图谱？这将清除并重新构建所有文档的图谱数据。')) return
  try {
    const res = await kbApi.rebuildGraph(kbId.value)
    toast.success('重建任务已提交', `任务 ID: ${res.task_id.slice(0, 8)}`)
  } catch {
    // 错误已由拦截器提示
  }
}

async function fetchSubgraph(entity: string) {
  if (!entity) return
  loading.value = true
  try {
    const res = await kbApi.getSubgraph(kbId.value, entity, 2)
    nodes.value = (res.nodes as Record<string, unknown>[]).map(mapNode)
    edges.value = (res.edges as Record<string, unknown>[]).map(mapEdge)
    highlightNames.value = [entity]
    toast.success('已加载子图', entity)
  } catch {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

const nodeCount = computed(() => nodes.value.length)
const edgeCount = computed(() => edges.value.length)

const labelStats = computed(() => {
  const counts: Record<string, number> = {}
  nodes.value.forEach((n) => {
    const label = n.labels?.[0] || n.label || 'Entity'
    counts[label] = (counts[label] || 0) + 1
  })
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
})

function formatValue(val: unknown): string {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

onMounted(() => {
  fetchGraph()
  fetchStats()
})
</script>

<template>
  <div>
    <PageHeader title="知识图谱" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button variant="outline" @click="() => { fetchGraph(); fetchStats() }">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button v-if="isEditor" variant="outline" @click="rebuildGraph">
          <Hammer class="size-4" :stroke-width="1.5" />
          重建图谱
        </Button>
      </template>
    </PageHeader>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-[200px_1fr]">
      <!-- 左侧统计面板 -->
      <div class="space-y-3">
        <Card>
          <CardContent class="p-3">
            <div class="flex items-center gap-2">
              <div class="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Network class="size-4" :stroke-width="1.5" />
              </div>
              <div>
                <p class="text-xs text-muted-foreground">节点数</p>
                <p class="text-lg font-semibold text-foreground">{{ nodeCount }}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="p-3">
            <div class="flex items-center gap-2">
              <div class="flex size-8 items-center justify-center rounded-md bg-info/10 text-info">
                <Share2 class="size-4" :stroke-width="1.5" />
              </div>
              <div>
                <p class="text-xs text-muted-foreground">关系数</p>
                <p class="text-lg font-semibold text-foreground">{{ edgeCount }}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="p-3">
            <div class="flex items-center gap-2">
              <div class="flex size-8 items-center justify-center rounded-md bg-success/10 text-success">
                <Layers class="size-4" :stroke-width="1.5" />
              </div>
              <div>
                <p class="text-xs text-muted-foreground">标签类型</p>
                <p class="text-lg font-semibold text-foreground">{{ labelStats.length }}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 标签分布 -->
        <Card v-if="labelStats.length > 0">
          <CardContent class="p-3">
            <p class="mb-2 text-xs font-medium text-muted-foreground">标签分布</p>
            <div class="space-y-1.5">
              <div v-for="[label, count] in labelStats" :key="label" class="flex items-center justify-between text-xs">
                <Badge variant="outline" class="text-[10px]">{{ label }}</Badge>
                <span class="text-muted-foreground">{{ count }}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <!-- 右侧图谱区域 -->
      <Card class="overflow-hidden">
        <CardContent class="p-0">
          <!-- 工具栏 -->
          <div class="flex items-center gap-2 border-b border-border bg-background p-2">
            <div class="relative min-w-[200px] flex-1">
              <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
              <Input
                v-model="searchKeyword"
                placeholder="搜索节点名称..."
                class="h-8 pl-8"
                @keyup.enter="handleSearch"
              />
            </div>
            <Button v-if="searchKeyword" variant="ghost" size="sm" @click="clearSearch">
              <X class="size-4" :stroke-width="1.5" />
            </Button>
            <Button variant="outline" size="sm" :disabled="searching" @click="handleSearch">
              <Loader2 v-if="searching" class="size-4 animate-spin" :stroke-width="1.5" />
              <Search v-else class="size-4" :stroke-width="1.5" />
              搜索
            </Button>
            <Button variant="outline" size="sm" @click="fitView">
              <Maximize2 class="size-4" :stroke-width="1.5" />
              适应
            </Button>
          </div>

          <!-- 图谱容器 -->
          <div class="relative h-[600px]">
            <div v-if="loading" class="flex h-full items-center justify-center">
              <Skeleton class="size-full" />
            </div>
            <GraphViewer
              v-else-if="nodeCount > 0"
              ref="graphViewerRef"
              :nodes="nodes"
              :edges="edges"
              :highlight-names="highlightNames"
              @node-click="onNodeClick"
            />
            <EmptyState
              v-else
              :icon="Share2"
              title="暂无图谱数据"
              description="解析文档后将自动构建知识图谱，或点击「重建图谱」"
              class="py-12"
            />
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 节点详情抽屉 -->
    <Teleport to="body">
      <div
        v-if="drawerOpen"
        class="fixed inset-0 z-[1400] flex justify-end"
      >
        <div class="absolute inset-0 bg-background/70 backdrop-blur-sm" @click="drawerOpen = false" />
        <Card class="relative m-4 h-fit w-80 shadow-xl">
          <CardContent class="p-4">
            <div class="mb-3 flex items-center justify-between">
              <h3 class="text-sm font-medium">节点详情</h3>
              <Button variant="ghost" size="sm" @click="drawerOpen = false">
                <X class="size-4" :stroke-width="1.5" />
              </Button>
            </div>
            <div v-if="selectedNode" class="space-y-3 text-sm">
              <div>
                <span class="text-xs text-muted-foreground">名称</span>
                <p class="font-medium text-foreground">{{ selectedNode.name }}</p>
              </div>
              <div v-if="selectedNode.labels?.length">
                <span class="text-xs text-muted-foreground">标签</span>
                <div class="mt-1 flex flex-wrap gap-1">
                  <Badge v-for="l in selectedNode.labels" :key="l" variant="secondary" class="text-[10px]">{{ l }}</Badge>
                </div>
              </div>
              <div v-if="selectedNode.type">
                <span class="text-xs text-muted-foreground">类型</span>
                <p>{{ selectedNode.type }}</p>
              </div>
              <div v-if="selectedNode.properties">
                <span class="text-xs text-muted-foreground">属性</span>
                <dl class="mt-1 space-y-1">
                  <div v-for="(val, key) in selectedNode.properties" :key="key" class="flex gap-2 text-xs">
                    <dt class="shrink-0 font-mono text-muted-foreground">{{ key }}:</dt>
                    <dd class="break-all text-foreground">{{ formatValue(val) }}</dd>
                  </div>
                </dl>
              </div>
              <Button variant="outline" size="sm" class="w-full" @click="fetchSubgraph(selectedNode.name)">
                <Network class="size-4" :stroke-width="1.5" />
                查看子图（2 跳）
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </Teleport>
  </div>
</template>
