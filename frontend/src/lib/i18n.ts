/**
 * 轻量级国际化工具（P3-9 i18n）。
 *
 * 不引入 vue-i18n 依赖，基于 Vue reactive 实现简单的翻译函数。
 * 支持嵌套键（如 ``t('common.save')``），未匹配时回退到键名本身。
 *
 * 用法：
 *   import { t, setLocale, getLocale } from '@/lib/i18n'
 *   t('common.save')  // → '保存'（zh-CN）或 'Save'（en-US）
 *   setLocale('en-US')
 *
 * 支持 locales：
 *   - zh-CN（默认，产品主要语言）
 *   - en-US（基础英文）
 */
import { reactive, computed } from 'vue'
import zhCN from '@/locales/zh-CN'
import enUS from '@/locales/en-US'

type Locale = 'zh-CN' | 'en-US'

const messages: Record<Locale, Record<string, unknown>> = {
  'zh-CN': zhCN as unknown as Record<string, unknown>,
  'en-US': enUS as unknown as Record<string, unknown>,
}

const state = reactive({
  locale: (localStorage.getItem('locale') as Locale) || 'zh-CN',
})

/**
 * 按点号路径从嵌套对象中取值。
 * 如 ``getNested(obj, 'common.save')`` → ``obj.common.save``
 */
function getNested(obj: Record<string, unknown>, path: string): unknown {
  const keys = path.split('.')
  let current: unknown = obj
  for (const key of keys) {
    if (current && typeof current === 'object' && key in current) {
      current = (current as Record<string, unknown>)[key]
    } else {
      return undefined
    }
  }
  return current
}

/**
 * 翻译函数。
 *
 * @param key 嵌套键（如 ``'common.save'``）。
 * @param params 可选的插值参数（替换 ``{name}`` 占位符）。
 * @returns 翻译后的字符串，未匹配时回退到键名。
 */
export function t(key: string, params?: Record<string, string | number>): string {
  const msg = getNested(messages[state.locale], key)
  let text: string
  if (typeof msg === 'string') {
    text = msg
  } else {
    // 回退到 zh-CN，最后回退到键名
    const fallback = getNested(messages['zh-CN'], key)
    text = typeof fallback === 'string' ? fallback : key
  }
  // 简单插值：{name} → params.name
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
    }
  }
  return text
}

/**
 * 切换当前语言并持久化。
 */
export function setLocale(locale: Locale): void {
  state.locale = locale
  localStorage.setItem('locale', locale)
  document.documentElement.lang = locale
}

/**
 * 获取当前语言。
 */
export function getLocale(): Locale {
  return state.locale
}

/**
 * 响应式 locale（供组件监听语言切换）。
 */
export const locale = computed(() => state.locale)

/**
 * 可用语言列表。
 */
export const availableLocales: { value: Locale; label: string }[] = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en-US', label: 'English' },
]
