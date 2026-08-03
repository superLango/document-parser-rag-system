import {
  FolderOpen,
  Settings,
  UserCircle,
  ShieldCheck,
  ScrollText,
  LayoutDashboard,
  HelpCircle,
  Info,
  type LucideIcon,
} from 'lucide-vue-next'

/**
 * 主导航项配置（KB 中心架构）
 *
 * HansonDOC RAG 以知识库为隔离边界，所有文档/抽取/问答/配置均在知识库内进行，
 * 因此主导航仅保留「知识库」入口与「系统设置」。进入知识库后由 KbLayout
 * 提供二级导航（概览/文档/抽取/Schema/术语/任务/图谱/配置/问答/成员）。
 */
export interface NavItem {
  path: string
  title: string
  icon: LucideIcon
  description?: string
  /** 关键字，用于 Command Palette 搜索 */
  keywords?: string[]
  /** 是否需要超级管理员权限 */
  superuserOnly?: boolean
}

/** 主导航（所有登录用户可见） */
export const navItems: NavItem[] = [
  {
    path: '/dashboard',
    title: '仪表盘',
    icon: LayoutDashboard,
    description: '跨知识库全局统计与趋势',
    keywords: ['dashboard', 'stats', '仪表盘', '统计', '趋势', '图表'],
  },
  {
    path: '/kbs',
    title: '知识库',
    icon: FolderOpen,
    description: '以知识库为隔离边界的垂直领域文档智能产品',
    keywords: ['kb', 'rag', 'knowledge base', '知识库', '向量', '隔离', '文档', '抽取', '问答'],
  },
  {
    path: '/settings',
    title: '系统设置',
    icon: Settings,
    description: '应用偏好与系统状态',
    keywords: ['settings', 'config', '设置', '偏好'],
  },
  {
    path: '/profile',
    title: '个人中心',
    icon: UserCircle,
    description: '个人信息与安全设置',
    keywords: ['profile', '个人', '账户', '密码', 'avatar'],
  },
  {
    path: '/help',
    title: '帮助文档',
    icon: HelpCircle,
    description: '系统使用指南与常见问题',
    keywords: ['help', 'docs', '帮助', '文档', '指南', 'faq'],
  },
  {
    path: '/about',
    title: '关于',
    icon: Info,
    description: '系统信息与技术栈',
    keywords: ['about', '关于', '系统', '信息', 'version'],
  },
]

/** 管理员导航（仅超级管理员可见） */
export const adminNavItems: NavItem[] = [
  {
    path: '/admin/users',
    title: '用户管理',
    icon: ShieldCheck,
    description: '管理系统用户、角色与状态',
    keywords: ['users', 'admin', '用户', '管理', '超管', '权限'],
    superuserOnly: true,
  },
  {
    path: '/admin/audit-logs',
    title: '审计日志',
    icon: ScrollText,
    description: '查看系统操作审计记录',
    keywords: ['audit', 'log', '审计', '日志', '操作记录'],
    superuserOnly: true,
  },
]

/** 所有导航项（含管理员），用于 Command Palette 搜索 */
export const allNavItems: NavItem[] = [...navItems, ...adminNavItems]

/**
 * 通过 path 查找 NavItem
 */
export function findNavItem(path: string): NavItem | undefined {
  // 精确匹配
  if (path === '/' || path === '/kbs') return navItems.find((i) => i.path === '/kbs')
  // 管理员路径
  if (path.startsWith('/admin')) {
    return adminNavItems.find((i) => path.startsWith(i.path))
  }
  // 前缀匹配（处理 /kbs/xxx 等子路由）
  const seg = `/${path.split('/')[1]}`
  return allNavItems.find((i) => i.path === seg)
}

export { FolderOpen, Settings, UserCircle, ShieldCheck, ScrollText, LayoutDashboard, HelpCircle, Info }
