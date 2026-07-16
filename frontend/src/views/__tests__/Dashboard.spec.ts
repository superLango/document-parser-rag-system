import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Dashboard from '../Dashboard/index.vue'
import type { DashboardStats } from '@/api/types'

// Mock 仪表盘统计 API
vi.mock('@/api/modules/dashboard', () => ({
  dashboardApi: {
    getStats: vi.fn(),
  },
}))

// 导入 mock 后的模块，用于在测试中配置返回值
import { dashboardApi } from '@/api/modules/dashboard'

// 构造模拟统计数据
const mockStats: DashboardStats = {
  documents_count: 42,
  tasks_count: 15,
  schemas_count: 8,
  terms_count: 100,
  success_rate: 0.9,
  recent_documents: [],
  recent_tasks: [],
}

describe('Dashboard 仪表盘', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(dashboardApi.getStats).mockResolvedValue(mockStats)
  })

  it('组件能正常挂载', async () => {
    const wrapper = mount(Dashboard)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.dashboard').exists()).toBe(true)
  })

  it('页头标题正确渲染', async () => {
    const wrapper = mount(Dashboard)
    await flushPromises()

    expect(wrapper.find('.page-title').text()).toBe('仪表盘')
    expect(wrapper.find('.page-desc').text()).toBe('系统运行概览与近期活动')
  })

  it('统计数据正确展示', async () => {
    const wrapper = mount(Dashboard)
    await flushPromises()

    // 验证统计卡片数量为 4
    const statCards = wrapper.findAll('.stat-card')
    expect(statCards).toHaveLength(4)

    // 验证统计数值
    const statValues = wrapper.findAll('.stat-value')
    expect(statValues[0].text()).toContain('42')
    expect(statValues[1].text()).toContain('15')
    expect(statValues[2].text()).toContain('8')
    expect(statValues[3].text()).toContain('100')

    // 验证卡片标签
    const statLabels = wrapper.findAll('.stat-label')
    expect(statLabels[0].text()).toBe('文档总数')
    expect(statLabels[1].text()).toBe('解析任务')
    expect(statLabels[2].text()).toBe('抽取 Schema')
    expect(statLabels[3].text()).toBe('术语条目')
  })
})
