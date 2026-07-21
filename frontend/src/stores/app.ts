import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

/**
 * 应用全局状态
 * 管理侧边栏折叠、全局加载、主题（light/dark/system）等
 */
export const useAppStore = defineStore('app', () => {
  // 侧边栏是否折叠
  const sidebarCollapsed = ref(false)

  // 全局加载状态
  const loading = ref(false)

  // 移动端抽屉式侧边栏是否打开（lg 以下使用）
  const mobileDrawerOpen = ref(false)

  // 命令面板是否打开
  const commandPaletteOpen = ref(false)

  // 主题模式：'light' | 'dark' | 'system'
  const themeMode = ref<'light' | 'dark' | 'system'>(
    (localStorage.getItem('theme-mode') as 'light' | 'dark' | 'system') || 'system',
  )

  // 系统当前是否偏好深色（监听 prefers-color-scheme）
  const systemPrefersDark = ref(
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : false,
  )

  // 实际生效的主题（system 解析为 light 或 dark）
  const resolvedTheme = computed<'light' | 'dark'>(() => {
    if (themeMode.value === 'system') {
      return systemPrefersDark.value ? 'dark' : 'light'
    }
    return themeMode.value
  })

  // 将主题应用到 <html> 根元素（Tailwind v4 dark mode via .dark class）
  function applyTheme(theme: 'light' | 'dark') {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    if (theme === 'dark') root.classList.add('dark')
    else root.classList.remove('dark')
    root.style.colorScheme = theme
  }

  // 监听系统主题变化（仅 system 模式下生效）
  if (typeof window !== 'undefined') {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      systemPrefersDark.value = e.matches
    }
    // 兼容性：优先使用 addEventListener
    if (mql.addEventListener) mql.addEventListener('change', handler)
    else mql.addListener(handler)
  }

  // 监听实际主题变化，同步到 DOM
  watch(
    resolvedTheme,
    (theme) => {
      applyTheme(theme)
    },
    { immediate: true },
  )

  // 持久化主题模式选择
  watch(themeMode, (mode) => {
    localStorage.setItem('theme-mode', mode)
  })

  // 切换侧边栏
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  // 设置加载状态
  function setLoading(value: boolean) {
    loading.value = value
  }

  // 设置主题模式
  function setThemeMode(mode: 'light' | 'dark' | 'system') {
    themeMode.value = mode
  }

  // 在 light/dark 之间切换（system 视当前 resolvedTheme 决定切换目标）
  function toggleTheme() {
    const next = resolvedTheme.value === 'dark' ? 'light' : 'dark'
    themeMode.value = next
  }

  // 设置移动抽屉状态
  function setMobileDrawer(open: boolean) {
    mobileDrawerOpen.value = open
  }

  // 设置命令面板状态
  function setCommandPalette(open: boolean) {
    commandPaletteOpen.value = open
  }

  // 打开命令面板
  function openCommandPalette() {
    commandPaletteOpen.value = true
  }

  return {
    sidebarCollapsed,
    loading,
    themeMode,
    resolvedTheme,
    mobileDrawerOpen,
    commandPaletteOpen,
    toggleSidebar,
    setLoading,
    setThemeMode,
    toggleTheme,
    setMobileDrawer,
    setCommandPalette,
    openCommandPalette,
  }
})
