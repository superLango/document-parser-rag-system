import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
      },
      {
        path: 'documents',
        name: 'Documents',
        component: () => import('@/views/DocumentsView.vue'),
      },
      {
        path: 'parser',
        name: 'Parser',
        component: () => import('@/views/ParserView.vue'),
      },
      {
        path: 'schemas',
        name: 'Schemas',
        component: () => import('@/views/SchemasView.vue'),
      },
      {
        path: 'terms',
        name: 'Terms',
        component: () => import('@/views/TermsView.vue'),
      },
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: () => import('@/views/KnowledgeView.vue'),
      },
      {
        path: 'qa',
        name: 'QA',
        component: () => import('@/views/QaView.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
