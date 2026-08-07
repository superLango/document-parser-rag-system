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
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
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
  Sparkles,
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
import { confirm } from '@/composables/useConfirm'

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

// AbortController集合：跟踪所有活跃请求，组件卸载时统一取消
const activeControllers = new Set<AbortController>()

function createAbortSignal() {
  const controller = new AbortController()
  activeControllers.add(controller)
  // 请求完成后从集合中移除
  const signal = controller.signal
  signal.addEventListener('abort', () => activeControllers.delete(controller), { once: true })
  return { signal }
}

function abortAllRequests() {
  for (const controller of activeControllers) {
    controller.abort()
  }
  activeControllers.clear()
}

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
    const res = await kbApi.getGraph(kbId.value, 100, createAbortSignal())
    nodes.value = (res.nodes as Record<string, unknown>[]).map(mapNode)
    edges.value = (res.edges as Record<string, unknown>[]).map(mapEdge)
  } catch (err: any) {
    if (err?.code !== 'ERR_CANCELED' && err?.name !== 'CanceledError') {
      nodes.value = []
      edges.value = []
    }
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    stats.value = await kbApi.graphStats(kbId.value, createAbortSignal())
  } catch (err: any) {
    if (err?.code !== 'ERR_CANCELED' && err?.name !== 'CanceledError') {
      stats.value = null
    }
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
    }, createAbortSignal())
    const searchNodes = (res.nodes as Record<string, unknown>[]).map(mapNode)
    highlightNames.value = searchNodes.map((n) => n.name)
    if (searchNodes.length === 0) {
      toast.info('未找到匹配节点')
    }
  } catch (err: any) {
    if (err?.code !== 'ERR_CANCELED' && err?.name !== 'CanceledError') {
      // 错误已由拦截器提示
    }
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
  if (!await confirm('确定重建整个知识图谱？这将清除并重新构建所有文档的图谱数据。')) return
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
    const res = await kbApi.getSubgraph(kbId.value, entity, 2, createAbortSignal())
    nodes.value = (res.nodes as Record<string, unknown>[]).map(mapNode)
    edges.value = (res.edges as Record<string, unknown>[]).map(mapEdge)
    highlightNames.value = [entity]
    toast.success('已加载子图', entity)
  } catch (err: any) {
    if (err?.code !== 'ERR_CANCELED' && err?.name !== 'CanceledError') {
      // 错误已由拦截器提示
    }
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

const labelColors: Record<string, { bg: string; text: string; glow: string }> = {
  Entity: { bg: 'from-cyan-500/20 to-blue-500/20', text: 'text-cyan-500 dark:text-cyan-400', glow: 'shadow-cyan-500/20' },
  Person: { bg: 'from-purple-500/20 to-pink-500/20', text: 'text-purple-500 dark:text-purple-400', glow: 'shadow-purple-500/20' },
  Organization: { bg: 'from-emerald-500/20 to-teal-500/20', text: 'text-emerald-500 dark:text-emerald-400', glow: 'shadow-emerald-500/20' },
  Location: { bg: 'from-orange-500/20 to-amber-500/20', text: 'text-orange-500 dark:text-orange-400', glow: 'shadow-orange-500/20' },
  Concept: { bg: 'from-violet-500/20 to-indigo-500/20', text: 'text-violet-500 dark:text-violet-400', glow: 'shadow-violet-500/20' },
}

function getLabelColor(label: string) {
  return labelColors[label] || { bg: 'from-muted/50 to-muted/30', text: 'text-muted-foreground', glow: 'shadow-muted/20' }
}

onMounted(() => {
  fetchGraph()
  fetchStats()
})

onBeforeUnmount(() => {
  // 组件卸载（路由切换）时取消所有正在进行的请求
  abortAllRequests()
})
</script>

<template>
  <div class="relative min-h-screen">
    <!-- 科技感背景装饰 -->
    <div class="pointer-events-none fixed inset-0 overflow-hidden">
      <div class="absolute -top-40 -right-40 h-80 w-80 rounded-full bg-cyan-500/5 blur-3xl" />
      <div class="absolute top-1/3 -left-40 h-96 w-96 rounded-full bg-blue-500/5 blur-3xl" />
      <div class="absolute -bottom-40 right-1/3 h-72 w-72 rounded-full bg-violet-500/5 blur-3xl" />
    </div>

    <PageHeader title="知识图谱" :description="`知识库：${kbStore.currentKb?.name || ''}`">
      <template #actions>
        <Button
          variant="outline"
          class="group relative overflow-hidden border-cyan-500/30 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 transition-all duration-300 hover:border-cyan-400/50 hover:shadow-lg hover:shadow-cyan-500/20 hover:-translate-y-0.5"
          @click="() => { fetchGraph(); fetchStats() }"
        >
          <div class="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-cyan-400/10 to-transparent transition-transform duration-500 group-hover:translate-x-full" />
          <RefreshCw class="relative size-4 text-cyan-500 dark:text-cyan-400 transition-colors group-hover:text-cyan-600 dark:group-hover:text-cyan-300" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          <span class="relative ml-2">刷新</span>
        </Button>
        <Button
          v-if="isEditor"
          variant="outline"
          class="group relative overflow-hidden border-violet-500/30 bg-gradient-to-r from-violet-500/10 to-purple-500/10 transition-all duration-300 hover:border-violet-400/50 hover:shadow-lg hover:shadow-violet-500/20 hover:-translate-y-0.5"
          @click="rebuildGraph"
        >
          <div class="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-violet-400/10 to-transparent transition-transform duration-500 group-hover:translate-x-full" />
          <Hammer class="relative size-4 text-violet-500 dark:text-violet-400 transition-colors group-hover:text-violet-600 dark:group-hover:text-violet-300" :stroke-width="1.5" />
          <span class="relative ml-2">重建图谱</span>
        </Button>
      </template>
    </PageHeader>

    <div class="relative grid grid-cols-1 gap-5 lg:grid-cols-[240px_1fr]">
      <!-- 左侧统计面板 -->
      <div class="space-y-4">
        <!-- 节点数卡片 -->
        <Card class="group relative overflow-hidden border-cyan-500/20 bg-card/90 backdrop-blur-xl transition-all duration-300 hover:border-cyan-400/40 hover:shadow-xl hover:shadow-cyan-500/10 hover:-translate-y-1 dark:bg-gradient-to-br dark:from-slate-900/80 dark:via-slate-800/50 dark:to-slate-900/80">
          <div class="absolute inset-0 bg-gradient-to-br from-cyan-500/5 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
          <div class="absolute top-0 left-0 h-px w-full bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent" />
          <CardContent class="relative p-4">
            <div class="flex items-center gap-3">
              <div class="relative flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/20 shadow-lg shadow-cyan-500/20 transition-transform duration-300 group-hover:scale-110">
                <div class="absolute inset-0 rounded-xl bg-cyan-400/20 blur-md opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                <Network class="relative size-5 text-cyan-500 dark:text-cyan-400" :stroke-width="1.5" />
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">节点数</p>
                <p class="mt-0.5 font-mono text-2xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-cyan-500 to-blue-500 dark:from-cyan-400 dark:to-blue-400 tabular-nums">
                  {{ nodeCount }}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 关系数卡片 -->
        <Card class="group relative overflow-hidden border-emerald-500/20 bg-card/90 backdrop-blur-xl transition-all duration-300 hover:border-emerald-400/40 hover:shadow-xl hover:shadow-emerald-500/10 hover:-translate-y-1 dark:bg-gradient-to-br dark:from-slate-900/80 dark:via-slate-800/50 dark:to-slate-900/80">
          <div class="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
          <div class="absolute top-0 left-0 h-px w-full bg-gradient-to-r from-transparent via-emerald-400/50 to-transparent" />
          <CardContent class="relative p-4">
            <div class="flex items-center gap-3">
              <div class="relative flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-600/20 shadow-lg shadow-emerald-500/20 transition-transform duration-300 group-hover:scale-110">
                <div class="absolute inset-0 rounded-xl bg-emerald-400/20 blur-md opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                <Share2 class="relative size-5 text-emerald-500 dark:text-emerald-400" :stroke-width="1.5" />
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">关系数</p>
                <p class="mt-0.5 font-mono text-2xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-emerald-500 to-teal-500 dark:from-emerald-400 dark:to-teal-400 tabular-nums">
                  {{ edgeCount }}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 标签类型卡片 -->
        <Card class="group relative overflow-hidden border-violet-500/20 bg-card/90 backdrop-blur-xl transition-all duration-300 hover:border-violet-400/40 hover:shadow-xl hover:shadow-violet-500/10 hover:-translate-y-1 dark:bg-gradient-to-br dark:from-slate-900/80 dark:via-slate-800/50 dark:to-slate-900/80">
          <div class="absolute inset-0 bg-gradient-to-br from-violet-500/5 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
          <div class="absolute top-0 left-0 h-px w-full bg-gradient-to-r from-transparent via-violet-400/50 to-transparent" />
          <CardContent class="relative p-4">
            <div class="flex items-center gap-3">
              <div class="relative flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-600/20 shadow-lg shadow-violet-500/20 transition-transform duration-300 group-hover:scale-110">
                <div class="absolute inset-0 rounded-xl bg-violet-400/20 blur-md opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                <Layers class="relative size-5 text-violet-500 dark:text-violet-400" :stroke-width="1.5" />
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">标签类型</p>
                <p class="mt-0.5 font-mono text-2xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-violet-500 to-purple-500 dark:from-violet-400 dark:to-purple-400 tabular-nums">
                  {{ labelStats.length }}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 标签分布卡片 -->
        <Card v-if="labelStats.length > 0" class="group relative overflow-hidden border-border/60 bg-card/90 backdrop-blur-xl transition-all duration-300 hover:border-border/80 dark:border-slate-700/50 dark:bg-gradient-to-br dark:from-slate-900/80 dark:via-slate-800/50 dark:to-slate-900/80 dark:hover:border-slate-600/70">
          <div class="absolute top-0 left-0 h-px w-full bg-gradient-to-r from-transparent via-muted-foreground/30 to-transparent dark:via-slate-500/30" />
          <CardContent class="relative p-4">
            <div class="mb-3 flex items-center gap-2">
              <Sparkles class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
              <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">标签分布</p>
            </div>
            <div class="space-y-2.5">
              <div
                v-for="[label, count] in labelStats"
                :key="label"
                class="group/item relative flex items-center justify-between rounded-lg bg-gradient-to-r px-2.5 py-2 transition-all duration-200 hover:from-muted/50 hover:to-transparent dark:hover:from-slate-800/50"
                :class="getLabelColor(label).bg"
              >
                <div class="flex items-center gap-2">
                  <div class="size-2 rounded-full shadow-sm" :class="[getLabelColor(label).text.replace('text-', 'bg-'), getLabelColor(label).glow]" />
                  <Badge
                    variant="outline"
                    class="border-0 bg-transparent px-0 text-[11px] font-medium"
                    :class="getLabelColor(label).text"
                  >
                    {{ label }}
                  </Badge>
                </div>
                <span class="font-mono text-xs font-semibold tabular-nums text-foreground/90 dark:text-slate-300">{{ count }}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <!-- 右侧图谱区域 -->
      <Card class="group relative overflow-hidden border-border/60 bg-card/95 backdrop-blur-xl shadow-2xl shadow-black/10 dark:border-slate-700/50 dark:bg-gradient-to-br dark:from-slate-900/90 dark:via-slate-800/70 dark:to-slate-900/90 dark:shadow-black/20">
        <div class="absolute top-0 left-0 h-px w-full bg-gradient-to-r from-transparent via-cyan-400/30 to-transparent" />
        <CardContent class="relative p-0">
          <!-- 工具栏 -->
          <div class="flex items-center gap-3 border-b border-border/60 bg-muted/30 p-3 backdrop-blur-sm dark:border-slate-700/50 dark:bg-gradient-to-r dark:from-slate-800/50 dark:via-slate-900/50 dark:to-slate-800/50">
            <div class="relative min-w-[240px] flex-1">
              <Search class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70 transition-colors duration-200 dark:text-slate-500" :stroke-width="1.5" :class="{ 'text-cyan-500 dark:text-cyan-400': searchKeyword }" />
              <Input
                v-model="searchKeyword"
                placeholder="搜索节点名称..."
                class="h-10 rounded-xl border-border/60 bg-card/80 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground/70 transition-all duration-200 focus:border-cyan-500/50 focus:bg-card focus:shadow-lg focus:shadow-cyan-500/10 focus:ring-cyan-500/20 dark:border-slate-700/50 dark:bg-slate-900/60 dark:text-slate-200 dark:placeholder:text-slate-500 dark:focus:bg-slate-900/80"
                @keyup.enter="handleSearch"
              />
              <div class="absolute bottom-0 left-1/2 h-px w-0 -translate-x-1/2 bg-gradient-to-r from-transparent via-cyan-400 to-transparent transition-all duration-300 focus-within:w-[calc(100%-24px)]" />
            </div>
            <Button
              v-if="searchKeyword"
              variant="ghost"
              size="icon"
              class="size-10 rounded-xl text-muted-foreground transition-all duration-200 hover:bg-muted hover:text-rose-500 dark:text-slate-400 dark:hover:bg-slate-800/80 dark:hover:text-rose-400"
              @click="clearSearch"
            >
              <X class="size-4" :stroke-width="1.5" />
            </Button>
            <Button
              variant="outline"
              size="default"
              class="relative overflow-hidden rounded-xl border-cyan-500/30 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 px-4 transition-all duration-300 hover:border-cyan-400/50 hover:shadow-lg hover:shadow-cyan-500/20 disabled:opacity-50"
              :disabled="searching"
              @click="handleSearch"
            >
              <div class="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-cyan-400/10 to-transparent transition-transform duration-500 hover:translate-x-full" />
              <Loader2 v-if="searching" class="relative size-4 animate-spin text-cyan-500 dark:text-cyan-400" :stroke-width="1.5" />
              <Search v-else class="relative size-4 text-cyan-500 dark:text-cyan-400" :stroke-width="1.5" />
              <span class="relative ml-2 text-sm">搜索</span>
            </Button>
            <Button
              variant="outline"
              size="icon"
              class="size-10 rounded-xl border-border/70 bg-muted/50 text-muted-foreground transition-all duration-200 hover:border-border hover:bg-muted/80 hover:text-foreground hover:shadow-lg dark:border-slate-600/50 dark:bg-slate-800/50 dark:text-slate-400 dark:hover:border-slate-500 dark:hover:bg-slate-700/60 dark:hover:text-slate-200"
              @click="fitView"
            >
              <Maximize2 class="size-4" :stroke-width="1.5" />
            </Button>
          </div>

          <!-- 图谱容器 -->
          <div class="relative h-[650px]">
            <!-- 网格背景装饰 -->
            <div class="pointer-events-none absolute inset-0 opacity-[0.03] dark:opacity-[0.03]" style="background-image: linear-gradient(rgba(148, 163, 184, 0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(148, 163, 184, 0.3) 1px, transparent 1px); background-size: 40px 40px;" />

            <!-- 加载状态 -->
            <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm dark:bg-slate-900/60">
              <div class="flex flex-col items-center gap-4">
                <div class="relative">
                  <div class="absolute inset-0 animate-ping rounded-full bg-cyan-500/20" />
                  <div class="absolute inset-2 animate-pulse rounded-full bg-cyan-500/30" />
                  <div class="relative flex size-16 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500/20 to-blue-600/20 shadow-xl shadow-cyan-500/30">
                    <Loader2 class="size-8 animate-spin text-cyan-500 dark:text-cyan-400" :stroke-width="1.5" />
                  </div>
                </div>
                <div class="flex flex-col items-center gap-1">
                  <p class="text-sm font-medium text-foreground/90 dark:text-slate-300">加载图谱数据</p>
                  <p class="text-xs text-muted-foreground/70 dark:text-slate-500">正在构建知识网络...</p>
                </div>
                <div class="h-1 w-48 overflow-hidden rounded-full bg-muted dark:bg-slate-800">
                  <div class="h-full w-1/2 animate-pulse rounded-full bg-gradient-to-r from-cyan-500 via-blue-500 to-violet-500" />
                </div>
              </div>
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
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        leave-active-class="transition-all duration-200 ease-in"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
      >
        <div
          v-if="drawerOpen"
          class="fixed inset-0 z-[1400] flex justify-end"
        >
          <div class="absolute inset-0 bg-background/80 backdrop-blur-md dark:bg-slate-950/70" @click="drawerOpen = false" />
          <Transition
            enter-active-class="transition-all duration-300 ease-out"
            leave-active-class="transition-all duration-200 ease-in"
            enter-from-class="translate-x-full opacity-0"
            leave-to-class="translate-x-full opacity-0"
          >
            <Card
              v-if="drawerOpen"
              class="relative m-4 h-fit w-96 overflow-hidden border-border/60 bg-card/98 shadow-2xl shadow-black/20 backdrop-blur-xl dark:border-slate-700/50 dark:bg-gradient-to-br dark:from-slate-900/95 dark:via-slate-800/90 dark:to-slate-900/95 dark:shadow-black/50"
            >
              <div class="absolute top-0 left-0 h-px w-full bg-gradient-to-r from-transparent via-cyan-400/40 to-transparent" />
              <div class="absolute right-0 top-0 h-full w-px bg-gradient-to-b from-cyan-400/30 via-violet-400/20 to-transparent" />
              <CardContent class="relative p-5">
                <div class="mb-5 flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <div class="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-600/20">
                      <Network class="size-4 text-cyan-500 dark:text-cyan-400" :stroke-width="1.5" />
                    </div>
                    <h3 class="text-sm font-semibold text-foreground dark:text-slate-200">节点详情</h3>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-8 rounded-lg text-muted-foreground transition-all duration-200 hover:bg-muted hover:text-foreground dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    @click="drawerOpen = false"
                  >
                    <X class="size-4" :stroke-width="1.5" />
                  </Button>
                </div>
                <div v-if="selectedNode" class="space-y-5 text-sm">
                  <!-- 节点名称 -->
                  <div class="rounded-xl border border-border/60 bg-muted/30 p-4 dark:border-slate-700/50 dark:bg-gradient-to-br dark:from-slate-800/50 dark:to-slate-900/50">
                    <span class="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 dark:text-slate-500">名称</span>
                    <p class="mt-1.5 text-lg font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-500 to-blue-500 dark:from-cyan-400 dark:to-blue-400">
                      {{ selectedNode.name }}
                    </p>
                  </div>

                  <!-- 标签 -->
                  <div v-if="selectedNode.labels?.length">
                    <span class="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 dark:text-slate-500">标签</span>
                    <div class="mt-2 flex flex-wrap gap-1.5">
                      <Badge
                        v-for="l in selectedNode.labels"
                        :key="l"
                        variant="secondary"
                        :class="`rounded-lg border px-2.5 py-1 text-[10px] font-medium transition-all duration-200 hover:scale-105 ${getLabelColor(l).text} ${getLabelColor(l).bg} border-current/20`"
                      >
                        {{ l }}
                      </Badge>
                    </div>
                  </div>

                  <!-- 类型 -->
                  <div v-if="selectedNode.type" class="rounded-xl border border-border/60 bg-muted/30 p-4 dark:border-slate-700/50 dark:bg-gradient-to-br dark:from-slate-800/50 dark:to-slate-900/50">
                    <span class="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 dark:text-slate-500">类型</span>
                    <p class="mt-1.5 font-mono text-sm text-foreground/90 dark:text-slate-300">{{ selectedNode.type }}</p>
                  </div>

                  <!-- 属性 -->
                  <div v-if="selectedNode.properties">
                    <span class="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 dark:text-slate-500">属性</span>
                    <div class="mt-2 rounded-xl border border-border/60 bg-muted/30 p-4 dark:border-slate-700/50 dark:bg-gradient-to-br dark:from-slate-800/50 dark:to-slate-900/50">
                      <dl class="space-y-2.5">
                        <div
                          v-for="(val, key) in selectedNode.properties"
                          :key="key"
                          class="flex items-start gap-3 rounded-lg p-2 transition-colors duration-200 hover:bg-muted/80 dark:hover:bg-slate-800/60"
                        >
                          <dt class="shrink-0 font-mono text-xs font-medium text-violet-500 dark:text-violet-400">{{ key }}</dt>
                          <dd class="break-all font-mono text-xs leading-relaxed text-foreground/90 dark:text-slate-300">{{ formatValue(val) }}</dd>
                        </div>
                      </dl>
                    </div>
                  </div>

                  <!-- 操作按钮 -->
                  <Button
                    variant="outline"
                    class="group relative w-full overflow-hidden rounded-xl border-cyan-500/30 bg-gradient-to-r from-cyan-500/10 via-blue-500/10 to-cyan-500/10 py-5 text-sm font-medium transition-all duration-300 hover:border-cyan-400/50 hover:shadow-lg hover:shadow-cyan-500/20 hover:-translate-y-0.5"
                    @click="fetchSubgraph(selectedNode.name)"
                  >
                    <div class="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-cyan-400/20 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
                    <Network class="relative mr-2 size-4 text-cyan-500 dark:text-cyan-400 transition-transform duration-200 group-hover:scale-110" :stroke-width="1.5" />
                    <span class="relative bg-gradient-to-r from-cyan-600 to-blue-600 bg-clip-text text-transparent dark:from-cyan-300 dark:to-blue-300">查看子图（2 跳）</span>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </Transition>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
