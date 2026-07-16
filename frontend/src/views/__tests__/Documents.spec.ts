import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Documents from '../Documents/index.vue'

// Mock vue-router
vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
}))

// Mock 文档 API
vi.mock('@/api/modules/document', () => ({
  documentApi: {
    getList: vi.fn().mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    }),
    upload: vi.fn(),
    remove: vi.fn(),
    getDetail: vi.fn(),
  },
}))

// Mock 任务 API
vi.mock('@/api/modules/task', () => ({
  taskApi: {
    submit: vi.fn(),
    getList: vi.fn(),
  },
}))

// Mock Schema API
vi.mock('@/api/modules/schema', () => ({
  schemaApi: {
    getList: vi.fn().mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    }),
  },
}))

describe('Documents 文档管理', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('组件能正常挂载', async () => {
    const wrapper = mount(Documents)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.documents').exists()).toBe(true)
  })

  it('文档表格存在', async () => {
    const wrapper = mount(Documents)
    await flushPromises()
    // 验证 el-table 组件已渲染
    expect(wrapper.find('.el-table').exists()).toBe(true)
  })

  it('上传按钮存在', async () => {
    const wrapper = mount(Documents)
    await flushPromises()
    // 验证页头中的上传按钮
    const uploadBtn = wrapper.find('.page-header .el-button')
    expect(uploadBtn.exists()).toBe(true)
    expect(uploadBtn.text()).toContain('上传文档')
  })
})
