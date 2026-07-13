import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 应用全局状态
 * 管理侧边栏折叠、全局加载、主题等
 */
export const useAppStore = defineStore('app', () => {
  // 侧边栏是否折叠
  const sidebarCollapsed = ref(false)

  // 全局加载状态
  const loading = ref(false)

  // 主题（预留，当前固定深色）
  const theme = ref<'dark'>('dark')

  // 切换侧边栏
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  // 设置加载状态
  function setLoading(value: boolean) {
    loading.value = value
  }

  return {
    sidebarCollapsed,
    loading,
    theme,
    toggleSidebar,
    setLoading,
  }
})
