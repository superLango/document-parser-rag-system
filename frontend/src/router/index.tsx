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
import WorkspacesPage from '@/views/WorkspacesPage'
import ApiKeysPage from '@/views/ApiKeysPage'
import InvitationsPage from '@/views/InvitationsPage'
import UsersPage from '@/views/admin/UsersPage'
import RolesPage from '@/views/admin/RolesPage'
import AuditLogsPage from '@/views/admin/AuditLogsPage'
import NotFoundPage from '@/views/NotFoundPage'
import ForbiddenPage from '@/views/ForbiddenPage'

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
  { path: '/403', element: <ForbiddenPage /> },
  { path: '*', element: <NotFoundPage /> },
])
