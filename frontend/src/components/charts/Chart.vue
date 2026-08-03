<script setup lang="ts">
/**
 * 通用 Chart.js 封装组件。
 *
 * 基于 chart.js 4.x，支持 line/bar/doughnut/pie/polarArea/radar 类型。
 * 通过 ref 获取 canvas 上下文，onMounted 创建实例，onBeforeUnmount 销毁，
 * watch data/options 变化时重建图表。
 *
 * 用法：
 *   <Chart type="line" :data="lineData" :options="lineOptions" />
 */
import {
  ref,
  onMounted,
  onBeforeUnmount,
  watch,
  shallowRef,
} from 'vue'
import {
  Chart,
  type ChartConfiguration,
  type ChartData,
  type ChartOptions,
  type ChartType,
} from 'chart.js/auto'

const props = withDefaults(
  defineProps<{
    type: ChartType
    data: ChartData
    options?: ChartOptions
    height?: number
    class?: string
  }>(),
  { height: 240 },
)

const canvasRef = ref<HTMLCanvasElement | null>(null)
const chartInstance = shallowRef<Chart | null>(null)

function buildConfig(): ChartConfiguration {
  return {
    type: props.type,
    data: props.data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'bottom',
          labels: { color: 'rgb(148, 163, 184)', font: { size: 11 } },
        },
        tooltip: {
          backgroundColor: 'rgba(15, 22, 35, 0.95)',
          titleColor: '#fff',
          bodyColor: '#c5cee0',
          borderColor: 'rgba(74, 163, 255, 0.3)',
          borderWidth: 1,
        },
      },
      ...(props.options ?? {}),
    },
  }
}

function render() {
  if (!canvasRef.value) return
  chartInstance.value?.destroy()
  chartInstance.value = new Chart(canvasRef.value, buildConfig())
}

onMounted(render)

onBeforeUnmount(() => {
  chartInstance.value?.destroy()
  chartInstance.value = null
})

watch(
  () => [props.data, props.options],
  () => render(),
  { deep: true },
)
</script>

<template>
  <div :class="['relative w-full', props.class]" :style="{ height: `${height}px` }">
    <canvas ref="canvasRef" />
  </div>
</template>
