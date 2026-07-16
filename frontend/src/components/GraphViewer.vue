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
  const nodeDefs: ElementDefinition[] = props.nodes.map((n) => {
    const name = String(n.name ?? n.id)
    return {
      group: 'nodes' as const,
      data: {
        id: name,
        label: name,
        name,
        raw: n,
      },
    }
  })

  // 边 id 必须唯一：source->target->type 组合
  const edgeDefs: ElementDefinition[] = props.edges.map((e, idx) => {
    const source = String(e.source)
    const target = String(e.target)
    return {
      group: 'edges' as const,
      data: {
        id: `e-${idx}-${source}->${target}`,
        source,
        target,
        label: e.type,
        raw: e,
      },
    }
  })

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
  animate: true,
  animationDuration: 600,
  padding: 30,
  randomize: true,
  componentSpacing: 80,
  nodeRepulsion: 8000,
  idealEdgeLength: 100,
  edgeElasticity: 0.45,
  gravity: 0.25,
  numIter: 1500,
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
    cy.elements().remove()
    cy.add(buildElements())
    applyLayout()
    refreshHighlight()
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
  initCytoscape()
  refreshHighlight()
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
  <div class="graph-viewer">
    <div ref="containerRef" class="cy-container" />
    <el-empty
      v-if="!nodes.length"
      class="graph-empty"
      description="暂无图谱数据"
      :image-size="80"
    />
  </div>
</template>

<style scoped lang="scss">
.graph-viewer {
  position: relative;
  width: 100%;
  height: 100%;
}

.cy-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
  background-color: var(--bg-base, #0f1623);
}

.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
</style>
