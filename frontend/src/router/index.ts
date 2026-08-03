import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import KbLayout from '@/layouts/KbLayout.vue'

// 路由配置（KB 中心架构）：
// 根路径重定向到知识库列表，所有文档/抽取/问答/配置均在知识库内进行
// /kbs/:kb_id 下由 KbLayout 提供二级导航
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: DefaultLayout,
    children: [
      // 根路径重定向到知识库列表
      {
        path: '',
        redirect: { name: 'KbList' },
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '仪表盘' },
      },
      // 知识库列表（主入口）
      {
        path: 'kbs',
        name: 'KbList',
        component: () => import('@/views/Kb/List.vue'),
        meta: { title: '知识库' },
      },
      // 新建知识库向导
      {
        path: 'kbs/create',
        name: 'KbCreate',
        component: () => import('@/views/Kb/Create.vue'),
        meta: { title: '新建知识库' },
      },
      // 系统设置
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings/index.vue'),
        meta: { title: '系统设置' },
      },
      // 个人中心
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/Profile.vue'),
        meta: { title: '个人中心' },
      },
      // 帮助文档（阶段 4 - 帮助文档）
      {
        path: 'help',
        name: 'Help',
        component: () => import('@/views/Help.vue'),
        meta: { title: '帮助文档' },
      },
      {
        path: 'about',
        name: 'About',
        component: () => import('@/views/About.vue'),
        meta: { title: '关于' },
      },
      // ---------- 系统管理（超管专属） ----------
      {
        path: 'admin/users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/Users.vue'),
        meta: { title: '用户管理', superuserOnly: true },
      },
      {
        path: 'admin/audit-logs',
        name: 'AdminAuditLogs',
        component: () => import('@/views/admin/AuditLogs.vue'),
        meta: { title: '审计日志', superuserOnly: true },
      },
    ],
  },
  // 知识库内布局（独立全屏布局，非 DefaultLayout 子路由）
  {
    path: '/kbs/:kb_id',
    component: KbLayout,
    children: [
      {
        path: '',
        name: 'KbOverview',
        component: () => import('@/views/Kb/Overview.vue'),
        meta: { title: '知识库概览' },
      },
      {
        path: 'documents',
        name: 'KbDocuments',
        component: () => import('@/views/Kb/Documents.vue'),
        meta: { title: '文档管理' },
      },
      {
        path: 'documents/:doc_id/view',
        name: 'KbDocumentViewer',
        component: () => import('@/views/Kb/DocumentViewer.vue'),
        meta: { title: '文档查看', fullscreen: true },
      },
      {
        path: 'search',
        name: 'KbSearch',
        component: () => import('@/views/Kb/Search.vue'),
        meta: { title: '全文搜索' },
      },
      {
        path: 'extraction',
        name: 'KbExtraction',
        component: () => import('@/views/Kb/Extraction.vue'),
        meta: { title: '结构化抽取' },
      },
      {
        path: 'schemas',
        name: 'KbSchemas',
        component: () => import('@/views/Kb/Schemas.vue'),
        meta: { title: 'Schema 管理' },
      },
      {
        path: 'terms',
        name: 'KbTerms',
        component: () => import('@/views/Kb/Terms.vue'),
        meta: { title: '术语库' },
      },
      {
        path: 'tasks',
        name: 'KbTasks',
        component: () => import('@/views/Kb/Tasks.vue'),
        meta: { title: '任务监控' },
      },
      {
        path: 'graph',
        name: 'KbGraph',
        component: () => import('@/views/Kb/Graph.vue'),
        meta: { title: '知识图谱' },
      },
      {
        path: 'config',
        name: 'KbConfig',
        component: () => import('@/views/Kb/Config.vue'),
        meta: { title: '配置中心' },
      },
      {
        path: 'qa',
        name: 'KbQA',
        component: () => import('@/views/Kb/QA.vue'),
        meta: { title: '智能问答' },
      },
      {
        path: 'members',
        name: 'KbMembers',
        component: () => import('@/views/Kb/Members.vue'),
        meta: { title: '成员管理' },
      },
    ],
  },
  // ---------- 错误页（阶段 4 - 错误边界） ----------
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/error/Forbidden.vue'),
    meta: { public: true, title: '权限不足' },
  },
  {
    path: '/500',
    name: 'ServerError',
    component: () => import('@/views/error/ServerError.vue'),
    meta: { public: true, title: '服务器错误' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
    meta: { public: true, title: '页面未找到' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// 全局前置守卫：鉴权 + 超管路由保护
router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  // 设置标题
  if (to.meta.title) {
    document.title = `${to.meta.title} · HansonDOC RAG`
  }
  // 公开路由直接放行
  if (to.meta.public) {
    return next()
  }
  // 未登录跳转登录页
  if (!auth.isAuthenticated) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }
  // 超管专属路由保护
  if (to.meta.superuserOnly && !auth.isSuperuser) {
    return next({ name: 'KbList' })
  }
  next()
})

export default router
