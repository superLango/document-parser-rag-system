import type { CSSProperties, FormEvent } from 'react'
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Crown,
  Database,
  Plus,
  RefreshCcw,
  Search,
  Trash2,
  Users,
  UserPlus,
  X,
} from 'lucide-react'
import { kbApi } from '@/api/modules/kb'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import type { KbItem, KbMemberItem, KbRole } from '@/api/types'

const roleLabels: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

interface MemberSeed {
  username: string
  role: KbRole
}

interface KbForm {
  name: string
  description: string
}

const emptyForm: KbForm = { name: '', description: '' }

export default function KnowledgeBasesPage() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<KbForm>(emptyForm)
  const [members, setMembers] = useState<MemberSeed[]>([])
  const [memberUsername, setMemberUsername] = useState('')
  const [memberRole, setMemberRole] = useState<KbRole>('viewer')
  const [submitting, setSubmitting] = useState(false)
  const [membersTarget, setMembersTarget] = useState<KbItem | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<KbItem | null>(null)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['kb-list', page, search],
    queryFn: () => kbApi.list({ page, page_size: 20, keyword: search || undefined }),
  })

  const list = useMemo(() => data?.items ?? [], [data])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['kb-list'] })
    void refetch()
  }

  function addMemberSeed() {
    const username = memberUsername.trim()
    if (!username) return
    if (members.some((m) => m.username === username)) {
      toast('warning', '成员已添加', `${username} 已在初始成员列表中`)
      return
    }
    setMembers((prev) => [...prev, { username, role: memberRole }])
    setMemberUsername('')
  }

  function removeMemberSeed(username: string) {
    setMembers((prev) => prev.filter((m) => m.username !== username))
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const created = await kbApi.create({
        name: form.name,
        description: form.description || undefined,
        members,
      })
      const invited = created.invited?.length ?? 0
      const failed = created.failed_invites ?? []
      if (invited > 0) {
        toast('success', '知识库已创建', `已向 ${invited} 位成员发送邀请`)
      } else {
        toast('success', '知识库已创建')
      }
      if (failed.length > 0) {
        toast(
          'warning',
          `${failed.length} 位成员邀请失败`,
          failed.map((f) => `${f.username}：${f.error}`).join('；'),
        )
      }
      setCreating(false)
      setForm(emptyForm)
      setMembers([])
      invalidate()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await kbApi.remove(deleteTarget.id)
      toast('success', '知识库已删除', `已删除「${deleteTarget.name}」`)
      setDeleteTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="资源"
        title="知识库"
        description="以知识库为隔离边界与协作入口，成员按角色访问"
        actions={
          <Button
            onClick={() => {
              setCreating(true)
              setForm(emptyForm)
              setMembers([])
              setMemberUsername('')
            }}
          >
            <Plus className="h-4 w-4" />
            新建知识库
          </Button>
        }
      />

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <form
              className="flex flex-1 gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setPage(1)
                setSearch(keyword)
              }}
            >
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索知识库名称"
                />
              </div>
              <Button type="submit" variant="secondary">搜索</Button>
            </form>
            <Button variant="ghost" size="icon" onClick={() => invalidate()} disabled={isFetching} aria-label="刷新">
              <RefreshCcw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </CardContent>
      </Card>

      {isLoading ? (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} className="h-48 rounded-2xl" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-primary">
              <Database className="h-7 w-7" strokeWidth={1.5} />
            </span>
            <p className="text-sm font-medium">暂无知识库</p>
            <p className="text-xs text-muted-foreground">创建第一个知识库，开始文档智能协作</p>
            <Button onClick={() => { setCreating(true); setForm(emptyForm); setMembers([]) }}>
              <Plus className="h-4 w-4" />
              新建知识库
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((kb, index) => (
            <KbCard
              key={kb.id}
              kb={kb}
              delay={Math.min(index, 6) * 70}
              onMembers={() => setMembersTarget(kb)}
              onDelete={() => setDeleteTarget(kb)}
            />
          ))}
        </div>
      )}

      {list.length > 0 ? (
        <div className="flex justify-center">
          <Pagination page={page} pageSize={20} total={data?.total ?? 0} onPageChange={setPage} />
        </div>
      ) : null}

      {/* 新建知识库（含初始成员管理，无领域模板） */}
      <Dialog
        open={creating}
        onOpenChange={setCreating}
        title="新建知识库"
        description="创建后你自动成为所有者，可同时邀请初始成员"
        className="max-w-2xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreating(false)}>取消</Button>
            <Button type="submit" form="kb-form" disabled={submitting}>
              {submitting ? '创建中...' : '创建知识库'}
            </Button>
          </>
        }
      >
        <form id="kb-form" onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="kb-name">名称</Label>
            <Input
              id="kb-name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="如：产品文档库"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kb-desc">描述</Label>
            <Input
              id="kb-desc"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="知识库用途说明（可选）"
            />
          </div>

          <div className="space-y-2 rounded-xl border border-border bg-muted/40 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <UserPlus className="h-4 w-4 text-primary" />
              初始成员
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="flex-1">
                <Input
                  value={memberUsername}
                  onChange={(e) => setMemberUsername(e.target.value)}
                  placeholder="输入成员用户名"
                />
              </div>
              <Select
                className="w-full sm:w-32"
                value={memberRole}
                onChange={(e) => setMemberRole(e.target.value as KbRole)}
              >
                <option value="viewer">查看者</option>
                <option value="editor">编辑者</option>
                <option value="admin">管理员</option>
              </Select>
              <Button type="button" variant="secondary" onClick={addMemberSeed} disabled={!memberUsername.trim()}>
                添加
              </Button>
            </div>
            {members.length > 0 ? (
              <div className="flex flex-wrap gap-2 pt-1">
                {members.map((m) => (
                  <span
                    key={m.username}
                    className="inline-flex items-center gap-1.5 rounded-full border border-emerald-100 bg-white/80 px-2.5 py-1 text-xs shadow-soft"
                  >
                    @{m.username}
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                      {roleLabels[m.role]}
                    </Badge>
                    <button
                      type="button"
                      onClick={() => removeMemberSeed(m.username)}
                      className="text-muted-foreground transition-colors hover:text-destructive"
                      aria-label={`移除 ${m.username}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">可暂不邀请，创建后在成员管理中补充</p>
            )}
          </div>
        </form>
      </Dialog>

      {membersTarget ? (
        <MembersDialog kb={membersTarget} onClose={() => setMembersTarget(null)} />
      ) : null}

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="删除知识库"
        description={`确认删除「${deleteTarget?.name ?? ''}」？删除后不可恢复，成员关系一并移除。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={() => void handleDelete()}>确认删除</Button>
          </>
        }
      />
    </div>
  )
}

function KbCard({
  kb,
  delay,
  onMembers,
  onDelete,
}: {
  kb: KbItem
  delay: number
  onMembers: () => void
  onDelete: () => void
}) {
  const canManage = kb.my_role === 'owner' || kb.my_role === 'admin'
  return (
    <Card
      interactive
      className="animate-fade-up group relative flex flex-col overflow-hidden"
      style={{ animationDelay: `${delay}ms` } as CSSProperties}
    >
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-teal-400 to-emerald-300 opacity-70 transition-opacity group-hover:opacity-100" />
      <CardContent className="flex flex-1 flex-col gap-3 p-5 pt-6">
        <div className="flex items-start justify-between gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong shadow-soft transition-transform duration-200 group-hover:scale-105">
            <Database className="h-6 w-6" strokeWidth={1.6} />
          </span>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            <Badge variant={kb.my_role === 'owner' ? 'success' : 'outline'}>
              {kb.my_role === 'owner' ? <Crown className="h-3 w-3" /> : null}
              {kb.my_role ? roleLabels[kb.my_role] ?? kb.my_role : '—'}
            </Badge>
            <Badge variant="secondary">
              <Users className="h-3 w-3" /> {kb.member_count} 人
            </Badge>
          </div>
        </div>

        <div className="min-w-0">
          <h3 className="font-display text-lg font-semibold tracking-tight">{kb.name}</h3>
          <p className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-muted-foreground">
            {kb.description || '暂无描述'}
          </p>
        </div>

        <div className="mt-auto flex items-center justify-between border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">{formatDateTime(kb.created_at)}</p>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" title="成员管理" onClick={onMembers}>
              <Users className="h-4 w-4" />
              成员
            </Button>
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                title="删除"
                className="text-destructive"
                onClick={onDelete}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function MembersDialog({ kb, onClose }: { kb: KbItem; onClose: () => void }) {
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin'
  const isOwner = user?.is_superuser || kb.my_role === 'owner'

  const { data: members, isLoading, refetch } = useQuery({
    queryKey: ['kb-members', kb.id],
    queryFn: () => kbApi.listMembers(kb.id),
  })
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<KbRole>('viewer')
  const [submitting, setSubmitting] = useState(false)
  const [transferTarget, setTransferTarget] = useState<KbMemberItem | null>(null)

  async function handleInvite(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await kbApi.invite(kb.id, { username, role })
      toast('success', '邀请已发送', `已邀请 ${username} 加入知识库`)
      setUsername('')
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
      void refetch()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function removeMember(member: KbMemberItem) {
    try {
      await kbApi.removeMember(kb.id, member.user_id)
      toast('success', '成员已移除')
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
      toast('success', '所有权已转移', `「${kb.name}」所有者已变更为 ${transferTarget.username}`)
      setTransferTarget(null)
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['kb-list'] })
    } catch (err) {
      toast('error', '转移失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <>
      <Dialog
        open
        onOpenChange={onClose}
        title={`成员管理：${kb.name}`}
        description="邀请成员、调整角色或转移所有权"
        className="max-w-2xl"
      >
        {canManage ? (
          <form onSubmit={handleInvite} className="mb-4 flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3 sm:flex-row">
            <div className="flex-1">
              <Label htmlFor="invite-username">用户名</Label>
              <Input
                id="invite-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="输入成员用户名"
              />
            </div>
            <div>
              <Label>角色</Label>
              <Select
                className="w-full sm:w-32"
                value={role}
                onChange={(e) => setRole(e.target.value as KbRole)}
              >
                <option value="viewer">查看者</option>
                <option value="editor">编辑者</option>
                <option value="admin">管理员</option>
              </Select>
            </div>
            <Button type="submit" disabled={submitting || !username.trim()} className="self-end">
              {submitting ? '发送中...' : '发送邀请'}
            </Button>
          </form>
        ) : null}

        {isLoading ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : (
          <div className="space-y-2">
            {(members ?? []).map((member) => (
              <div
                key={member.id}
                className="flex items-center gap-3 rounded-xl border border-border px-3 py-2.5"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 text-sm font-semibold text-primary-strong">
                  {(member.full_name || member.username || 'U').slice(0, 1).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {member.full_name || member.username}
                    {member.role === 'owner' ? (
                      <Crown className="ml-1 inline h-3.5 w-3.5 text-warning" />
                    ) : null}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    @{member.username} · {member.status === 'invited' ? '待接受' : roleLabels[member.role]}
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
                {isOwner && member.role !== 'owner' && member.status === 'active' ? (
                  <Button variant="outline" size="sm" onClick={() => setTransferTarget(member)}>
                    转移所有权
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Dialog>

      <Dialog
        open={transferTarget !== null}
        onOpenChange={(open) => { if (!open) setTransferTarget(null) }}
        title="转移所有权"
        description={`确认将「${kb.name}」的所有权转移给 ${transferTarget?.username ?? ''}？转移后你将变为管理员。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setTransferTarget(null)}>取消</Button>
            <Button onClick={() => void handleTransfer()}>确认转移</Button>
          </>
        }
      />
    </>
  )
}
