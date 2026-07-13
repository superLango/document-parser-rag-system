import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

// 路由配置：7 个业务页面 + 登录页
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
        name: 'Dashboard',
        component: () => import('@/views/Dashboard/index.vue'),
        meta: { title: '仪表盘', icon: 'Odometer' },
      },
      {
        path: 'documents',
        name: 'Documents',
        component: () => import('@/views/Documents/index.vue'),
        meta: { title: '文档管理', icon: 'Document' },
      },
      {
        path: 'parser/:id',
        name: 'Parser',
        component: () => import('@/views/Parser/index.vue'),
        meta: { title: '解析查看', icon: 'View', hidden: true },
      },
      {
        path: 'schemas',
        name: 'Schemas',
        component: () => import('@/views/Schemas/index.vue'),
        meta: { title: '抽取 Schema', icon: 'SetUp' },
      },
      {
        path: 'terms',
        name: 'Terms',
        component: () => import('@/views/Terms/index.vue'),
        meta: { title: '术语库', icon: 'Collection' },
      },
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: () => import('@/views/Knowledge/index.vue'),
        meta: { title: '知识图谱', icon: 'Share' },
      },
      {
        path: 'qa',
        name: 'QA',
        component: () => import('@/views/QA/index.vue'),
        meta: { title: '智能问答', icon: 'ChatDotRound' },
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
    document.title = `${to.meta.title} · 文档智能解析系统`
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
