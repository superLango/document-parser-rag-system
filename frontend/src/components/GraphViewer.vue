<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import cytoscape, {
  type Core,
  type ElementDefinition,
  type CoseLayoutOptions,
  type StylesheetJsonBlock,
  type NodeSingular,
  type EdgeSingular,
} from 'cytoscape'
import { Network } from 'lucide-vue-next'
import type { GraphNode, GraphEdge } from '@/api/types'

interface Props {
  /** 图节点列表 */
  nodes: GraphNode[]
  /** 图边列表 */
  edges: GraphEdge[]
  /** 高亮节点名称集合（如搜索结果） */
  highlightNames?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  highlightNames: () => [],
})

const emit = defineEmits<{
  (e: 'node-click', data: GraphNode): void
  (e: 'node-right-click', data: GraphNode, position: { x: number; y: number }): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let cy: Core | null = null

// ---------- 标签 / 关系配色 ----------
// 节点标签（取 labels[0]）→ 颜色
const LABEL_COLORS: Record<string, string> = {
  Entity: '#4aa3ff',
  Term: '#52c41a',
  Standard: '#fa8c16',
  Document: '#13c2c2',
  Material: '#eb2f96',
  Organization: '#722ed1',
  Person: '#eb7e1b',
}

// 关系类型 → 颜色
const RELATION_COLORS: Record<string, string> = {
  CONTAINS: '#4aa3ff',
  REFERENCES: '#52c41a',
  EXECUTES: '#fa8c16',
  DEFINES: '#722ed1',
  RELATED_TO: '#8c8c8c',
  HAS_TERM: '#13c2c2',
}

const DEFAULT_NODE_COLOR = '#5a6d8c'
const DEFAULT_EDGE_COLOR = '#3a4a63'
const HIGHLIGHT_COLOR = '#fadb14'

function colorForNode(node: GraphNode): string {
  const label = node.labels?.[0] || node.label || node.type || ''
  return LABEL_COLORS[label] || DEFAULT_NODE_COLOR
}

function colorForEdge(edge: GraphEdge): string {
  return RELATION_COLORS[edge.type] || DEFAULT_EDGE_COLOR
}

function buildElements(): ElementDefinition[] {
  // 先过滤掉 name/id 为空的无效节点
  const validNodes = props.nodes.filter((n) => {
    const name = n.name ?? String(n.id ?? '')
    return name && name.trim() !== '' && name !== 'undefined' && name !== 'null'
  })

  const nodeIds = new Set<string>()
  const nodeDefs: ElementDefinition[] = validNodes.map((n) => {
    const name = String(n.name ?? n.id).trim()
    // 确保 id 唯一（同名节点加后缀）
    let id = name
    let suffix = 1
    while (nodeIds.has(id)) {
      id = `${name}__${suffix++}`
    }
    nodeIds.add(id)
    return {
      group: 'nodes' as const,
      data: {
        id,
        label: name,
        name,
        raw: n,
      },
    }
  })

  // 过滤掉 source/target 为空的无效边
  const edgeDefs: ElementDefinition[] = props.edges
    .filter((e) => {
      const source = String(e.source ?? '').trim()
      const target = String(e.target ?? '').trim()
      if (!source || !target) return false
      if (source === 'undefined' || source === 'null') return false
      if (target === 'undefined' || target === 'null') return false
      return true
    })
    .map((e, idx) => {
      let source = String(e.source).trim()
      let target = String(e.target).trim()
      // 如果精确 ID 不存在，尝试用原名匹配（兼容后端返回vid与前端生成id不一致的情况）
      if (!nodeIds.has(source)) {
        // 查找以 source 开头的节点 id（处理 __后缀 的情况）
        const match = [...nodeIds].find((nid) => nid === source || nid.startsWith(source + '__'))
        if (match) source = match
      }
      if (!nodeIds.has(target)) {
        const match = [...nodeIds].find((nid) => nid === target || nid.startsWith(target + '__'))
        if (match) target = match
      }
      return {
        group: 'edges' as const,
        data: {
          id: `e-${idx}-${source}->${target}`,
          source,
          target,
          label: e.type || e.label || 'RELATED_TO',
          raw: e,
        },
      }
    })
    .filter((e) => nodeIds.has(e.data.source) && nodeIds.has(e.data.target))

  return [...nodeDefs, ...edgeDefs]
}

function buildStyle(): StylesheetJsonBlock[] {
  return [
    {
      selector: 'node',
      style: {
        'background-color': (ele: NodeSingular) =>
          colorForNode(ele.data('raw') as GraphNode),
        'label': 'data(label)',
        'color': '#c5cee0',
        'font-size': 12,
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 6,
        'text-outline-color': '#0f1623',
        'text-outline-width': 2,
        'width': 36,
        'height': 36,
        'border-width': 2,
        'border-color': '#1f2a3a',
        'border-opacity': 0.6,
      },
    },
    {
      selector: 'edge',
      style: {
        'line-color': (ele: EdgeSingular) =>
          colorForEdge(ele.data('raw') as GraphEdge),
        'target-arrow-color': (ele: EdgeSingular) =>
          colorForEdge(ele.data('raw') as GraphEdge),
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        'curve-style': 'bezier',
        'width': 1.5,
        'label': 'data(label)',
        'font-size': 10,
        'color': '#7a8aa5',
        'text-rotation': 'autorotate',
        'text-background-color': '#0f1623',
        'text-background-opacity': 0.7,
        'text-background-padding': '2',
        'text-background-shape': 'roundrectangle',
      },
    },
    {
      selector: 'node.highlight',
      style: {
        'background-color': HIGHLIGHT_COLOR,
        'border-color': HIGHLIGHT_COLOR,
        'border-width': 3,
        'color': '#fff',
        'font-weight': 700,
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': '#fff',
        'border-width': 3,
      },
    },
  ]
}

const coseLayoutOptions: CoseLayoutOptions = {
  name: 'cose',
  animate: false, // 关闭动画，直接展示最终布局，避免长时间动画阻塞
  padding: 30,
  randomize: true,
  componentSpacing: 100,
  nodeRepulsion: 6000,
  idealEdgeLength: 80,
  edgeElasticity: 0.45,
  gravity: 0.25,
  numIter: 300, // 从1500减少到300，大幅降低布局计算时间
  coolingFactor: 0.95, // 添加冷却因子加速收敛
}

function applyLayout() {
  if (!cy) return
  const layout = cy.layout(coseLayoutOptions)
  layout.run()
}

function refreshHighlight() {
  if (!cy) return
  cy.nodes().removeClass('highlight')
  const names = props.highlightNames || []
  if (names.length === 0) return
  names.forEach((name) => {
    cy!.getElementById(String(name)).addClass('highlight')
  })
}

function initCytoscape() {
  if (!containerRef.value) return
  cy = cytoscape({
    container: containerRef.value,
    elements: buildElements(),
    style: buildStyle(),
    layout: coseLayoutOptions,
    wheelSensitivity: 0.2,
    minZoom: 0.2,
    maxZoom: 3,
  })

  // 节点点击
  cy.on('tap', 'node', (event) => {
    const node = event.target
    const raw = node.data('raw') as GraphNode
    emit('node-click', raw)
  })

  // 节点右键 → 弹出上下文菜单
  cy.on('cxttap', 'node', (event) => {
    const node = event.target
    const raw = node.data('raw') as GraphNode
    // 使用渲染坐标 + 容器偏移转换为页面坐标
    const rendered = node.renderedPosition()
    const rect = containerRef.value!.getBoundingClientRect()
    emit('node-right-click', raw, {
      x: rect.left + rendered.x,
      y: rect.top + rendered.y,
    })
  })
}

// 监听数据变化 → 重建图谱
watch(
  () => [props.nodes, props.edges],
  async () => {
    if (!cy) return
    // 使用 setTimeout 异步执行，避免阻塞UI线程
    setTimeout(() => {
      if (!cy) return
      cy.elements().remove()
      cy.add(buildElements())
      applyLayout()
      refreshHighlight()
    }, 0)
  },
  { deep: false },
)

watch(
  () => props.highlightNames,
  () => refreshHighlight(),
  { deep: true },
)

onMounted(async () => {
  await nextTick()
  // 使用 setTimeout 延迟初始化，让页面先完成其他内容的渲染，避免阻塞路由切换
  setTimeout(() => {
    initCytoscape()
    refreshHighlight()
  }, 50)
})

onBeforeUnmount(() => {
  if (cy) {
    cy.destroy()
    cy = null
  }
})

// 暴露给父组件：fit 视图
defineExpose({
  fit: () => cy?.fit(undefined, 40),
  center: () => cy?.center(),
})
</script>

<template>
  <div class="relative size-full">
    <div ref="containerRef" class="size-full min-h-[400px] bg-zinc-900" />
    <div
      v-if="!nodes.length"
      class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 py-12 text-center text-zinc-300"
    >
      <div class="flex size-12 items-center justify-center rounded-full bg-zinc-800 text-zinc-400">
        <Network class="size-6" :stroke-width="1.25" />
      </div>
      <div class="space-y-1">
        <p class="text-sm font-medium text-zinc-200">暂无图谱数据</p>
        <p class="max-w-sm text-xs text-zinc-400">
          请构建图谱或选择文档后查看节点与关系
        </p>
      </div>
    </div>
  </div>
</template>
