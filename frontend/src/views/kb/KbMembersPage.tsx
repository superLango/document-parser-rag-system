import type { FormEvent } from 'react'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Crown, Trash2 } from 'lucide-react'
import { kbApi } from '@/api/modules/kb'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { UserCombobox } from '@/components/UserCombobox'
import { useAuthStore } from '@/stores/auth'
import type { KbMemberItem, KbRole, UserSearchItem } from '@/api/types'
import { useKbDetail } from './KbDetailLayout'

export default function KbMembersPage() {
  const { kb, refetch } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin'
  const isOwner = user?.is_superuser || kb.my_role === 'owner'

  const { data: members, isLoading, refetch: refetchMembers } = useQuery({
    queryKey: ['kb-members', kb.id],
    queryFn: () => kbApi.listMembers(kb.id),
  })
  const [selected, setSelected] = useState<UserSearchItem | null>(null)
  const [role, setRole] = useState<KbRole>('viewer')
  const [submitting, setSubmitting] = useState(false)
  const [transferTarget, setTransferTarget] = useState<KbMemberItem | null>(null)

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    if (!selected?.username) return
    setSubmitting(true)
    try {
      await kbApi.invite(kb.id, { username: selected.username, role })
      toast('success', '邀请已发送', `已邀请 @${selected.username} 加入知识库`)
      setSelected(null)
      void refetchMembers()
      void refetch()
    } catch (err) {
      toast('error', '邀请失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  async function changeRole(member: KbMemberItem, nextRole: KbRole) {
    try {
      await kbApi.setMemberRole(kb.id, member.user_id, nextRole)
      toast('success', '角色已更新')
      void refetchMembers()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function removeMember(member: KbMemberItem) {
    try {
      await kbApi.removeMember(kb.id, member.user_id)
      toast('success', '成员已移除')
      void refetchMembers()
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['kb-list'] })
    } catch (err) {
      toast('error', '移除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleTransfer() {
    if (!transferTarget) return
    try {
      await kbApi.transfer(kb.id, transferTarget.user_id)
      toast('success', '所有权已转移', `所有者已变更为 @${transferTarget.username}`)
      setTransferTarget(null)
      void refetchMembers()
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['kb-list'] })
    } catch (err) {
      toast('error', '转移失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="成员"
        title="知识库成员"
        description="按角色管理成员访问权限，所有者可通过转移变更"
      />

      {canManage ? (
        <Card>
          <CardContent className="p-4">
            <form onSubmit={handleAdd} className="grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-end">
              <div>
                <Label>成员</Label>
                <UserCombobox value={selected} onSelect={setSelected} placeholder="搜索系统现有用户" />
              </div>
              <div>
                <Label>权限</Label>
                <Select className="w-full sm:w-32" value={role} onChange={(e) => setRole(e.target.value as KbRole)}>
                  <option value="viewer">查看者</option>
                  <option value="editor">编辑者</option>
                  <option value="admin">管理员</option>
                </Select>
              </div>
              <Button type="submit" disabled={submitting || !selected?.username} className="sm:mb-px">
                {submitting ? '发送中...' : '添加成员'}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6"><Skeleton className="h-40 w-full rounded-xl" /></div>
          ) : (
            <div className="divide-y divide-border">
              {(members ?? []).map((member) => (
                <div key={member.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 text-sm font-semibold text-primary-strong">
                    {(member.full_name || member.username || 'U').slice(0, 1).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 text-sm font-medium">
                      {member.full_name || member.username}
                      {member.role === 'owner' ? <Crown className="h-3.5 w-3.5 text-warning" /> : null}
                      {member.status === 'invited' ? (
                        <Badge variant="warning">待接受</Badge>
                      ) : (
                        <Badge variant="success">已加入</Badge>
                      )}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      @{member.username}
                      {member.department ? ` · ${member.department}` : ''}
                      {member.email ? ` · ${member.email}` : ''}
                    </p>
                  </div>
                  {member.status === 'active' && member.role !== 'owner' && canManage ? (
                    <>
                      <Select
                        className="w-28"
                        value={member.role}
                        onChange={(e) => changeRole(member, e.target.value as KbRole)}
                      >
                        <option value="viewer">查看者</option>
                        <option value="editor">编辑者</option>
                        <option value="admin">管理员</option>
                      </Select>
                      <Button
                        variant="ghost"
                        size="icon"
                        title="移除"
                        className="text-destructive"
                        onClick={() => removeMember(member)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </>
                  ) : null}
                  {isOwner && member.status === 'active' && member.role !== 'owner' ? (
                    <Button variant="outline" size="sm" onClick={() => setTransferTarget(member)}>
                      转移所有权
                    </Button>
                  ) : null}
                </div>
              ))}
              {(members ?? []).length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">暂无成员</p>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={transferTarget !== null}
        onOpenChange={(open) => { if (!open) setTransferTarget(null) }}
        title="转移所有权"
        description={`确认将「${kb.name}」的所有权转移给 @${transferTarget?.username ?? ''}？转移后你将变为管理员。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setTransferTarget(null)}>取消</Button>
            <Button onClick={() => void handleTransfer()}>确认转移</Button>
          </>
        }
      />
    </div>
  )
}
