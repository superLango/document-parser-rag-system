import { useEffect, type ReactNode } from 'react'
import {
  Navigate,
  Outlet,
  createBrowserRouter,
  useLocation,
} from 'react-router-dom'
import { isAuthenticated, useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/stores/rbac'
import AppShell from '@/layouts/AppShell'
import LoginPage from '@/views/LoginPage'
import DashboardPage from '@/views/DashboardPage'
import ProfilePage from '@/views/ProfilePage'
import PendingPage from '@/views/PendingPage'
import KnowledgeBasesPage from '@/views/KnowledgeBasesPage'
import KbDetailLayout from '@/views/kb/KbDetailLayout'
import KbOverviewPage from '@/views/kb/KbOverviewPage'
import KbMembersPage from '@/views/kb/KbMembersPage'
import KbResourcesPage from '@/views/kb/KbResourcesPage'
import KbDocumentsPage from '@/views/kb/KbDocumentsPage'
import KbTasksPage from '@/views/kb/KbTasksPage'
import KbDocumentViewerPage from '@/views/kb/KbDocumentViewerPage'
import KbPlaceholderPage from '@/views/kb/KbPlaceholderPage'
import WorkspacesPage from '@/views/WorkspacesPage'
import ApiKeysPage from '@/views/ApiKeysPage'
import InvitationsPage from '@/views/InvitationsPage'
import UsersPage from '@/views/admin/UsersPage'
import RolesPage from '@/views/admin/RolesPage'
import AuditLogsPage from '@/views/admin/AuditLogsPage'
import NotFoundPage from '@/views/NotFoundPage'
import ForbiddenPage from '@/views/ForbiddenPage'
import HelpPage from '@/views/HelpPage'
import AboutPage from '@/views/AboutPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { user, initialized, fetchUser } = useAuthStore()

  useEffect(() => {
    if (isAuthenticated() && !initialized) {
      void fetchUser()
    }
  }, [initialized, fetchUser])

  if (!isAuthenticated()) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname)}`} replace />
  }
  if (!initialized && !user) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background-soft">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }
  return <>{children}</>
}

function KbDetailRoute() {
  return (
    <RequireAuth>
      <KbDetailLayout />
    </RequireAuth>
  )
}

function RequirePermission({ code, children }: { code: string; children: ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!hasPermission(user, code)) {
    return <Navigate to="/403" replace />
  }
  return <>{children}</>
}

function AppLayout() {
  return (
    <RequireAuth>
      <AppShell>
        <Outlet />
      </AppShell>
    </RequireAuth>
  )
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'help', element: <HelpPage /> },
      { path: 'about', element: <AboutPage /> },
      { path: 'pending', element: <PendingPage /> },
      { path: 'kb', element: <KnowledgeBasesPage /> },
      { path: 'kb/invitations', element: <InvitationsPage /> },
      { path: 'workspaces', element: <WorkspacesPage /> },
      { path: 'api-keys', element: <ApiKeysPage /> },
      {
        path: 'admin/users',
        element: (
          <RequirePermission code="user.view">
            <UsersPage />
          </RequirePermission>
        ),
      },
      {
        path: 'admin/roles',
        element: (
          <RequirePermission code="role.view">
            <RolesPage />
          </RequirePermission>
        ),
      },
      {
        path: 'admin/audit-logs',
        element: (
          <RequirePermission code="audit.view">
            <AuditLogsPage />
          </RequirePermission>
        ),
      },
    ],
  },
  {
    path: '/kb/:kbId/documents/:docId/viewer',
    element: <KbDocumentViewerPage />,
  },
  {
    path: '/kb/:kbId',
    element: <KbDetailRoute />,
    children: [
      { index: true, element: <KbOverviewPage /> },
      { path: 'documents', element: <KbDocumentsPage /> },
      { path: 'vector-search', element: <KbPlaceholderPage title="向量搜索" description="向量检索与混合检索调试（迁移阶段开放）" /> },
      { path: 'extraction', element: <KbPlaceholderPage title="结构化抽取" description="Schema 驱动的结构化抽取（迁移阶段开放）" /> },
      { path: 'extraction-config', element: <KbPlaceholderPage title="抽取配置·专业术语集" description="Schema/Prompt 模板与术语集管理（迁移阶段开放）" /> },
      { path: 'tasks', element: <KbTasksPage /> },
      { path: 'graph', element: <KbPlaceholderPage title="知识图谱" description="实体关系图谱与子图查询（迁移阶段开放）" /> },
      { path: 'qa', element: <KbPlaceholderPage title="知识问答" description="混合检索问答与溯源（迁移阶段开放）" /> },
      { path: 'resources', element: <KbResourcesPage /> },
      { path: 'members', element: <KbMembersPage /> },
    ],
  },
  { path: '/403', element: <ForbiddenPage /> },
  { path: '*', element: <NotFoundPage /> },
])
