import { Hourglass, RefreshCcw, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useAuthStore } from '@/stores/auth'
import { isPending } from '@/stores/rbac'
import { Navigate } from 'react-router-dom'

export default function PendingPage() {
  const user = useAuthStore((s) => s.user)
  const fetchUser = useAuthStore((s) => s.fetchUser)

  if (!isPending(user)) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="animate-fade-up w-full max-w-md">
        <CardContent className="flex flex-col items-center gap-4 p-10 text-center">
          <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong shadow-soft">
            <Hourglass className="h-8 w-8" strokeWidth={1.5} />
          </span>
          <div>
            <h2 className="font-display text-xl font-semibold tracking-tight">账号待审批</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              你的账号正在等待管理员审批。审批通过后即可访问工作台与知识库，
              期间可修改个人资料与密码。
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-emerald-100 bg-muted/60 px-3.5 py-2 text-xs text-muted-foreground">
            <ShieldCheck className="h-4 w-4 text-primary" />
            当前状态：待审批（pending）
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              void fetchUser()
              window.location.reload()
            }}
          >
            <RefreshCcw className="h-4 w-4" />
            刷新审批状态
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
