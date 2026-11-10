import { useEffect, type ReactNode } from 'react'
import { Navigate, Outlet, createBrowserRouter, useLocation, useParams } from 'react-router-dom'
import { isAuthenticated, useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/stores/rbac'
import AppShell from '@/layouts/AppShell'
import LoginPage from '@/views/LoginPage'
import DashboardPage from '@/views/DashboardPage'
import ProfilePage from '@/views/ProfilePage'
import ModuleLayout from '@/views/ModuleLayout'
import ModulePlaceholderPage from '@/views/ModulePlaceholderPage'
import KbOverviewPage from '@/views/KbOverviewPage'
import KbDocumentsPage from '@/views/KbDocumentsPage'
import KbTasksPage from '@/views/KbTasksPage'
import KbDocumentViewerPage from '@/views/KbDocumentViewerPage'
import KbStructuredExtractionPage from '@/views/KbStructuredExtractionPage'
import KbExtractionDetailPage from '@/views/KbExtractionDetailPage'
import ApiKeysPage from '@/views/ApiKeysPage'
import DictionaryPage from '@/views/DictionaryPage'
import UsersPage from '@/views/admin/UsersPage'
import AuditLogsPage from '@/views/admin/AuditLogsPage'
import ShareResultPage from '@/views/ShareResultPage'
import IntegrationTaskResultPage from '@/views/IntegrationTaskResultPage'
import NotFoundPage from '@/views/NotFoundPage'
import ForbiddenPage from '@/views/ForbiddenPage'
import HelpPage from '@/views/HelpPage'
import AboutPage from '@/views/AboutPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const {
    user,
    initialized,
    requireAuth,
    fetchUser,
    loadPublicConfig,
  } = useAuthStore()

  useEffect(() => {
    if (requireAuth === null) {
      void loadPublicConfig()
    }
  }, [requireAuth, loadPublicConfig])

  useEffect(() => {
    if (requireAuth === null) return
    if ((isAuthenticated() || requireAuth === false) && !initialized) {
      void fetchUser()
    }
  }, [requireAuth, initialized, fetchUser])

  if (requireAuth === null) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background-soft">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }
  if (requireAuth && !isAuthenticated()) {
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

/** 旧知识库链接重定向到标准拆分模块。 */
function LegacyKbRedirect() {
  const location = useLocation()
  const rest = location.pathname.replace(/^\/kb(\/[^/]+)?/, '')
  const target = rest === '/extractions' ? '/standard/extraction' : `/standard${rest}`
  return <Navigate to={`${target}${location.search}`} replace />
}

/** 旧独立抽取链接重定向到标准拆分抽取详情。 */
function LegacyExtractionRedirect() {
  const { documentId } = useParams<{ documentId: string }>()
  return <Navigate to={`/standard/extraction/${documentId}`} replace />
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
      { path: 'api-keys', element: <ApiKeysPage /> },
      { path: 'orders', element: <ModulePlaceholderPage moduleKey="order_parse" /> },
      { path: 'certificates', element: <ModulePlaceholderPage moduleKey="certificate_parse" /> },
      { path: 'outsource', element: <ModulePlaceholderPage moduleKey="outsource_report" /> },
      {
        path: 'admin/users',
        element: (
          <RequirePermission code="user.view">
            <UsersPage />
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
    path: '/standard',
    element: (
      <RequireAuth>
        <ModuleLayout moduleKey="standard_split" />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <KbOverviewPage /> },
      { path: 'documents', element: <KbDocumentsPage /> },
      { path: 'extraction', element: <KbStructuredExtractionPage /> },
      { path: 'extraction/:documentId', element: <KbExtractionDetailPage /> },
      { path: 'dictionary', element: <Navigate to="categories" replace /> },
      { path: 'dictionary/categories', element: <DictionaryPage dictionaryType="categories" /> },
      { path: 'dictionary/items', element: <DictionaryPage dictionaryType="items" /> },
      { path: 'dictionary/methods', element: <DictionaryPage dictionaryType="methods" /> },
      { path: 'tasks', element: <KbTasksPage /> },
    ],
  },
  {
    path: '/standard/documents/:docId/viewer',
    element: (
      <RequireAuth>
        <KbDocumentViewerPage />
      </RequireAuth>
    ),
  },
  {
    path: '/share/:token',
    element: <ShareResultPage />,
  },
  {
    path: '/integration/task/:taskId',
    element: <IntegrationTaskResultPage />,
  },
  // 旧路由兼容
  { path: '/kb', element: <Navigate to="/standard" replace /> },
  { path: '/kb/:kbId/*', element: <LegacyKbRedirect /> },
  { path: '/extraction/:kbId/:documentId', element: <LegacyExtractionRedirect /> },
  { path: '/jobs/:jobId', element: <Navigate to="/" replace /> },
  { path: '/403', element: <ForbiddenPage /> },
  { path: '*', element: <NotFoundPage /> },
])
