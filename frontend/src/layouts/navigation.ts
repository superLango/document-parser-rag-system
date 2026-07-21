import {
  LayoutDashboard,
  FileText,
  Eye,
  Braces,
  FileSearch,
  BookOpen,
  Network,
  FolderOpen,
  ListChecks,
  MessageSquare,
  Settings,
  type LucideIcon,
} from 'lucide-vue-next'

/**
 * 主导航项配置
 * 与 router/index.ts 中的路由对应
 */
export interface NavItem {
  path: string
  title: string
  icon: LucideIcon
  description?: string
  /** 关键字，用于 Command Palette 搜索 */
  keywords?: string[]
}

export const navItems: NavItem[] = [
  {
    path: '/',
    title: '仪表盘',
    icon: LayoutDashboard,
    description: '系统概览与最近活动',
    keywords: ['dashboard', 'overview', '仪表盘', '首页'],
  },
  {
    path: '/documents',
    title: '文档管理',
    icon: FileText,
    description: '上传、查看、管理待解析文档',
    keywords: ['document', 'file', '文档', '上传'],
  },
  {
    path: '/schemas',
    title: '抽取 Schema',
    icon: Braces,
    description: '配置结构化抽取字段定义',
    keywords: ['schema', 'extraction', '抽取', '模板'],
  },
  {
    path: '/extraction',
    title: '文档抽取',
    icon: FileSearch,
    description: '基于 LangExtract 的结构化字段抽取',
    keywords: ['extraction', 'langextract', '抽取', '结构化'],
  },
  {
    path: '/terms',
    title: '术语库',
    icon: BookOpen,
    description: '管理行业术语词典与同义词',
    keywords: ['term', 'glossary', '术语', '词典'],
  },
  {
    path: '/knowledge',
    title: '知识图谱',
    icon: Network,
    description: '实体关系图谱可视化与编辑',
    keywords: ['knowledge', 'graph', '知识图谱', '实体'],
  },
  {
    path: '/kb',
    title: '知识库',
    icon: FolderOpen,
    description: 'RAG 向量知识库管理',
    keywords: ['kb', 'rag', 'knowledge base', '知识库', '向量'],
  },
  {
    path: '/tasks',
    title: '任务管理',
    icon: ListChecks,
    description: '查看异步任务执行状态与队列',
    keywords: ['task', 'queue', '任务', '队列'],
  },
  {
    path: '/qa',
    title: '智能问答',
    icon: MessageSquare,
    description: '基于 RAG 的智能问答与引用',
    keywords: ['qa', 'chat', '问答', '对话'],
  },
  {
    path: '/settings',
    title: '系统设置',
    icon: Settings,
    description: '应用偏好与系统状态',
    keywords: ['settings', 'config', '设置', '偏好'],
  },
]

/**
 * 通过 path 查找 NavItem
 */
export function findNavItem(path: string): NavItem | undefined {
  // 精确匹配
  if (path === '/') return navItems.find((i) => i.path === '/')
  // 前缀匹配（处理 /documents/123 这类子路由）
  const seg = `/${path.split('/')[1]}`
  return navItems.find((i) => i.path === seg)
}

export { LayoutDashboard, FileText, Eye, Braces, FileSearch, BookOpen, Network, FolderOpen, ListChecks, MessageSquare, Settings }
