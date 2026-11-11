import { Link } from 'react-router-dom'
import { ShieldX } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function ForbiddenPage() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background-soft p-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-warning/10 text-warning">
        <ShieldX className="h-8 w-8" strokeWidth={1.5} />
      </div>
      <h1 className="text-2xl font-semibold">403 · 权限不足</h1>
      <p className="max-w-sm text-sm text-muted-foreground">该页面仅超级管理员可访问，如需权限请联系系统管理员。</p>
      <Link to="/">
        <Button>返回工作台</Button>
      </Link>
    </div>
  )
}
