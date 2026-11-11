import { Link } from 'react-router-dom'
import { FileQuestion } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function NotFoundPage() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background-soft p-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-secondary text-primary">
        <FileQuestion className="h-8 w-8" strokeWidth={1.5} />
      </div>
      <h1 className="text-2xl font-semibold">404 · 页面不存在</h1>
      <p className="max-w-sm text-sm text-muted-foreground">你访问的页面不存在或已被移动。</p>
      <Link to="/">
        <Button>返回工作台</Button>
      </Link>
    </div>
  )
}
