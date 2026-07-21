import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

// 路由配置：10 个业务页面 + 登录页
// 阶段 3 已完成：Dashboard / Documents / Parser / Tasks
// 阶段 4 已完成：Schemas / Terms / Terms/Review / Knowledge / KnowledgeBase
// 阶段 5 已完成：QA / Settings
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
      {
        path: '',
        alias: '/dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard/index.vue'),
        meta: { title: '仪表盘' },
      },
      {
        path: 'documents',
        name: 'Documents',
        component: () => import('@/views/Documents/index.vue'),
        meta: { title: '文档管理' },
      },
      {
        path: 'parser/:id',
        name: 'Parser',
        component: () => import('@/views/Parser/index.vue'),
        meta: { title: '解析查看', hidden: true },
      },
      {
        path: 'schemas',
        name: 'Schemas',
        component: () => import('@/views/Schemas/index.vue'),
        meta: { title: '抽取 Schema' },
      },
      {
        path: 'extraction',
        name: 'Extraction',
        component: () => import('@/views/Extraction/index.vue'),
        meta: { title: '文档抽取' },
      },
      {
        path: 'extraction/:id',
        name: 'ExtractionWorkspace',
        component: () => import('@/views/Extraction/Workspace.vue'),
        meta: { title: '抽取操作' },
      },
      {
        path: 'terms',
        name: 'Terms',
        component: () => import('@/views/Terms/index.vue'),
        meta: { title: '术语库' },
      },
      {
        path: 'terms/review',
        name: 'TermReview',
        component: () => import('@/views/Terms/Review.vue'),
        meta: { title: '术语审核' },
      },
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: () => import('@/views/Knowledge/index.vue'),
        meta: { title: '知识图谱' },
      },
      {
        path: 'kb',
        name: 'KnowledgeBase',
        component: () => import('@/views/KnowledgeBase/index.vue'),
        meta: { title: '知识库管理', requiresAuth: true },
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('@/views/Tasks/index.vue'),
        meta: { title: '任务管理' },
      },
      {
        path: 'qa',
        name: 'QA',
        component: () => import('@/views/QA/index.vue'),
        meta: { title: '智能问答' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings/index.vue'),
        meta: { title: '系统设置' },
      },
    ],
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

// 全局前置守卫：鉴权
router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  // 设置标题
  if (to.meta.title) {
    document.title = `${to.meta.title} · Hansight`
  }
  // 公开路由直接放行
  if (to.meta.public) {
    return next()
  }
  // 未登录跳转登录页
  if (!auth.isAuthenticated) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }
  next()
})

export default router
