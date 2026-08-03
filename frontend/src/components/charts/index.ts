/**
 * 图表语义组件（基于 Chart.vue 薄包装）。
 *
 * 导出 LineChart / BarChart / DonutChart 三个语义组件，
 * 调用方传 data/options 即可，无需指定 type。
 */
import { defineComponent, h } from 'vue'
import Chart from './Chart.vue'
import type { ChartData, ChartOptions } from 'chart.js/auto'

const wrap = (type: 'line' | 'bar' | 'doughnut') =>
  defineComponent({
    name: type === 'line' ? 'LineChart' : type === 'bar' ? 'BarChart' : 'DonutChart',
    props: {
      data: { type: Object as () => ChartData, required: true },
      options: { type: Object as () => ChartOptions, default: () => ({}) },
      height: { type: Number, default: 240 },
      class: { type: String, default: '' },
    },
    setup(props) {
      return () =>
        h(Chart, {
          type,
          data: props.data,
          options: props.options,
          height: props.height,
          class: props.class,
        })
    },
  })

export const LineChart = wrap('line')
export const BarChart = wrap('bar')
export const DonutChart = wrap('doughnut')
export { Chart as default }
