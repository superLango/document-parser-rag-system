import { Braces } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export interface PromptTestResult {
  system: string
  user: string
}

interface Props {
  result: PromptTestResult | null
  catName?: string
}

export default function TestPanel({ result, catName }: Props) {
  return (
    <div className="flex h-full min-h-[260px] flex-col rounded-lg border p-2">
      <p className="flex items-center gap-1 px-1 pb-1 text-xs font-medium text-muted-foreground">
        <Braces className="h-3.5 w-3.5" />
        测试效果
      </p>
      {!result ? (
        <div className="flex flex-1 items-center justify-center px-1 py-6 text-center text-xs text-muted-foreground">
          点击“测试组装”按钮预览占位符组装后的效果
        </div>
      ) : (
        <div className="flex-1 space-y-3 overflow-auto">
          {catName && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium">当前类别</span>
              <Badge variant="outline">{catName}</Badge>
            </div>
          )}
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">System 提示词</p>
            <pre className="whitespace-pre-wrap rounded-md border bg-muted/40 p-2 font-mono text-xs" data-testid="test-system">{result.system || '（空）'}</pre>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">User 提示词（组装后）</p>
            <pre className="whitespace-pre-wrap rounded-md border bg-muted/40 p-2 font-mono text-xs" data-testid="test-user">{result.user || '（空）'}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
