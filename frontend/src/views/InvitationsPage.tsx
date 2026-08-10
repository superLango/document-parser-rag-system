import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Inbox, MailCheck } from 'lucide-react'
import { kbApi } from '@/api/modules/kb'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'

const roleLabels: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

export default function InvitationsPage() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['kb-invitations'],
    queryFn: kbApi.myInvitations,
  })

  async function accept(token: string, kbName: string) {
    try {
      await kbApi.acceptInvitation(token)
      toast('success', '已加入知识库', `你已成为「${kbName}」成员`)
      void queryClient.invalidateQueries({ queryKey: ['kb-invitations'] })
      void queryClient.invalidateQueries({ queryKey: ['kb-list'] })
    } catch (err) {
      toast('error', '接受失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="资源"
        title="我的邀请"
        description="处理知识库协作邀请，接受后即可访问对应知识库"
      />

      <Card>
        <CardContent className="p-6">
          {isLoading ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : (data ?? []).length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-primary">
                <Inbox className="h-7 w-7" strokeWidth={1.5} />
              </span>
              <p className="text-sm font-medium">暂无待处理的邀请</p>
              <p className="text-xs text-muted-foreground">
                知识库管理员发送邀请后会出现在这里
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {(data ?? []).map((inv) => (
                <div
                  key={inv.id}
                  className="flex flex-col gap-3 rounded-xl border border-border bg-muted/30 p-4 sm:flex-row sm:items-center"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                    <MailCheck className="h-5 w-5" strokeWidth={1.7} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{inv.kb_name || '知识库'}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      邀请人：{inv.inviter_username || '—'} · 有效期至{' '}
                      {formatDateTime(inv.expires_at)}
                    </p>
                  </div>
                  <Badge variant="success">{roleLabels[inv.role] ?? inv.role}</Badge>
                  <Button size="sm" onClick={() => accept(inv.token, inv.kb_name || '知识库')}>
                    接受邀请
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
