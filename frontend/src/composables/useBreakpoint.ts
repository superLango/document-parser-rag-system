import { ref, computed, onMounted, onUnmounted } from 'vue'

/**
 * 响应式断点定义（与 Tailwind 默认断点对齐）。
 *
 * - sm:  640px
 * - md:  768px
 * - lg:  1024px
 * - xl:  1280px
 * - 2xl: 1536px
 */
const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
} as const

export type Breakpoint = keyof typeof BREAKPOINTS

/**
 * 响应式断点 composable。
 *
 * 监听窗口尺寸变化，提供移动端/平板/桌面端的响应式判断，
 * 用于条件渲染、布局切换等场景。
 *
 * 用法：
 *   const { isMobile, isDesktop, isAtLeast } = useBreakpoint()
 *
 * 注意：SSR 安全——首次渲染以窗口不存在时回退到桌面宽度（1280）。
 */
export function useBreakpoint() {
  const width = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)

  function update() {
    if (typeof window !== 'undefined') {
      width.value = window.innerWidth
    }
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      width.value = window.innerWidth
      window.addEventListener('resize', update, { passive: true })
    }
  })

  onUnmounted(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('resize', update)
    }
  })

  /** 移动端：< md (768px) */
  const isMobile = computed(() => width.value < BREAKPOINTS.md)
  /** 平板：md (768px) ~ lg (1024px) */
  const isTablet = computed(
    () => width.value >= BREAKPOINTS.md && width.value < BREAKPOINTS.lg,
  )
  /** 桌面端：>= lg (1024px) */
  const isDesktop = computed(() => width.value >= BREAKPOINTS.lg)

  /** 判断当前宽度是否达到指定断点 */
  function isAtLeast(bp: Breakpoint): boolean {
    return width.value >= BREAKPOINTS[bp]
  }

  return { width, isMobile, isTablet, isDesktop, isAtLeast }
}
