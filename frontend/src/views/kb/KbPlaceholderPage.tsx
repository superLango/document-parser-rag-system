import { Construction } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'

export default function KbPlaceholderPage({
  title,
  description,
}: {
  title: string
  description?: string
}) {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="知识库" title={title} description={description} />
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-20 text-center">
          <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-50 text-warning">
            <Construction className="h-8 w-8" strokeWidth={1.5} />
          </span>
          <p className="text-sm font-medium">模块开发中</p>
          <p className="max-w-md text-xs leading-5 text-muted-foreground">
            该模块将在对应阶段迁移实现，当前为占位页面。主流程将按迁移计划逐步开放。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
