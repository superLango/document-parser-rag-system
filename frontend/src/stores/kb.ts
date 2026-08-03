import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { KnowledgeBase } from '@/api/types'

/**
 * 知识库上下文状态管理
 *
 * 管理当前进入的知识库上下文，供 KBLayout 及子页面共享。
 * 进入知识库时由 KBLayout 调用 setCurrent 设置。
 */
export const useKbStore = defineStore('kb', () => {
  // 当前知识库
  const currentKb = ref<KnowledgeBase | null>(null)

  // 设置当前知识库
  function setCurrent(kb: KnowledgeBase | null) {
    currentKb.value = kb
  }

  // 清除当前知识库（退出知识库时）
  function clear() {
    currentKb.value = null
  }

  return {
    currentKb,
    setCurrent,
    clear,
  }
})
