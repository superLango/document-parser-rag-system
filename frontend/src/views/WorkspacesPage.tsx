import type { FormEvent } from 'react'
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  RefreshCcw,
  Search,
  Trash2,
  Users,
  UsersRound,
  Crown,
} from 'lucide-react'
import { workspacesApi } from '@/api/modules/workspaces'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import type { GroupItem, Workspace, WorkspaceMemberItem } from '@/api/types'

const roleLabels: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

interface WsForm {
  name: string
  code: string
  description: string
}

const emptyForm: WsForm = { name: '', code: '', description: '' }

export default function WorkspacesPage() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<WsForm>(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [membersTarget, setMembersTarget] = useState<Workspace | null>(null)
  const [groupsTarget, setGroupsTarget] = useState<Workspace | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['ws-list', page, search],
    queryFn: () => workspacesApi.list({ page, page_size: 20, keyword: search || undefined }),
  })
  const list = useMemo(() => data?.items ?? [], [data])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['ws-list'] })
    void refetch()
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await workspacesApi.create({
        name: form.name,
        code: form.code,
        description: form.description || undefined,
      })
      toast('success', '工作空间已创建')
      setCreating(false)
      setForm(emptyForm)
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
      await workspacesApi.remove(deleteTarget.id)
      toast('success', '工作空间已删除', `已删除「${deleteTarget.name}」`)
      setDeleteTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="组织"
        title="工作空间"
        description="以工作空间组织成员与群组，群组授权按并集生效（FastGPT 模式）"
        actions={
          <Button onClick={() => { setCreating(true); setForm(emptyForm) }}>
            <Plus className="h-4 w-4" />
            新建工作空间
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
                  placeholder="搜索工作空间名称"
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

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>编码</TableHead>
                <TableHead>成员</TableHead>
                <TableHead>我的角色</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow><TableCell colSpan={6}><Skeleton className="h-16 w-full" /></TableCell></TableRow>
              ) : list.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                    暂无工作空间
                  </TableCell>
                </TableRow>
              ) : (
                list.map((ws) => (
                  <TableRow key={ws.id}>
                    <TableCell className="font-medium">{ws.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{ws.code}</TableCell>
                    <TableCell>
                      <Badge variant="secondary"><Users className="h-3 w-3" /> {ws.member_count} 人</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={ws.my_role === 'owner' ? 'success' : 'outline'}>
                        {ws.my_role === 'owner' ? <Crown className="h-3 w-3" /> : null}
                        {ws.my_role ? roleLabels[ws.my_role] ?? ws.my_role : '—'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{formatDateTime(ws.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="icon" title="成员" onClick={() => setMembersTarget(ws)}>
                          <Users className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" title="群组" onClick={() => setGroupsTarget(ws)}>
                          <UsersRound className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          title="删除"
                          className="text-destructive"
                          onClick={() => setDeleteTarget(ws)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          <Pagination page={page} pageSize={20} total={data?.total ?? 0} onPageChange={setPage} />
        </CardContent>
      </Card>

      <Dialog
        open={creating}
        onOpenChange={setCreating}
        title="新建工作空间"
        description="创建者自动成为所有者"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreating(false)}>取消</Button>
            <Button type="submit" form="ws-form" disabled={submitting}>
              {submitting ? '创建中...' : '创建工作空间'}
            </Button>
          </>
        }
      >
        <form id="ws-form" onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ws-name">名称</Label>
            <Input id="ws-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ws-code">编码</Label>
            <Input
              id="ws-code"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
              placeholder="小写字母/数字/下划线"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ws-desc">描述</Label>
            <Input id="ws-desc" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          </div>
        </form>
      </Dialog>

      {membersTarget ? (
        <WsMembersDialog ws={membersTarget} onClose={() => setMembersTarget(null)} />
      ) : null}
      {groupsTarget ? (
        <GroupsDialog ws={groupsTarget} onClose={() => setGroupsTarget(null)} />
      ) : null}

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="删除工作空间"
        description={`确认删除「${deleteTarget?.name ?? ''}」？其下群组将一并删除。`}
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

function WsMembersDialog({ ws, onClose }: { ws: Workspace; onClose: () => void }) {
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || ws.my_role === 'owner' || ws.my_role === 'admin'
  const isOwner = user?.is_superuser || ws.my_role === 'owner'
  const { data: members, isLoading, refetch } = useQuery({
    queryKey: ['ws-members', ws.id],
    queryFn: () => workspacesApi.listMembers(ws.id),
  })
  const [username, setUsername] = useState('')
  const [role, setRole] = useState('viewer')
  const [transferTarget, setTransferTarget] = useState<WorkspaceMemberItem | null>(null)

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    try {
      await workspacesApi.addMember(ws.id, { username, role })
      toast('success', '成员已添加', `已添加 ${username}`)
      setUsername('')
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['ws-list'] })
    } catch (err) {
      toast('error', '添加失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function changeRole(member: WorkspaceMemberItem, next: string) {
    try {
      await workspacesApi.setMemberRole(ws.id, member.user_id, next)
      toast('success', '角色已更新')
      void refetch()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function removeMember(member: WorkspaceMemberItem) {
    try {
      await workspacesApi.removeMember(ws.id, member.user_id)
      toast('success', '成员已移除')
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['ws-list'] })
    } catch (err) {
      toast('error', '移除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleTransfer() {
    if (!transferTarget) return
    try {
      await workspacesApi.transfer(ws.id, transferTarget.user_id)
      toast('success', '所有权已转移', `${ws.name} 所有者已变更为 ${transferTarget.username}`)
      setTransferTarget(null)
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['ws-list'] })
    } catch (err) {
      toast('error', '转移失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <>
      <Dialog open onOpenChange={onClose} title={`成员管理：${ws.name}`} className="max-w-2xl">
        {canManage ? (
          <form onSubmit={handleAdd} className="mb-4 flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3 sm:flex-row">
            <div className="flex-1">
              <Label htmlFor="ws-invite">用户名</Label>
              <Input id="ws-invite" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="输入成员用户名" />
            </div>
            <div>
              <Label>角色</Label>
              <Select className="w-full sm:w-32" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="viewer">查看者</option>
                <option value="editor">编辑者</option>
                <option value="admin">管理员</option>
              </Select>
            </div>
            <Button type="submit" disabled={!username.trim()} className="self-end">添加成员</Button>
          </form>
        ) : null}
        {isLoading ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : (
          <div className="space-y-2">
            {(members ?? []).map((m) => (
              <div key={m.id} className="flex items-center gap-3 rounded-xl border border-border px-3 py-2.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 text-sm font-semibold text-primary-strong">
                  {(m.full_name || m.username || 'U').slice(0, 1).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{m.full_name || m.username}</p>
                  <p className="truncate text-xs text-muted-foreground">@{m.username}</p>
                </div>
                {m.role !== 'owner' && canManage ? (
                  <>
                    <Select className="w-28" value={m.role} onChange={(e) => changeRole(m, e.target.value)}>
                      <option value="viewer">查看者</option>
                      <option value="editor">编辑者</option>
                      <option value="admin">管理员</option>
                    </Select>
                    <Button variant="ghost" size="icon" title="移除" className="text-destructive" onClick={() => removeMember(m)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                ) : null}
                {isOwner && m.role !== 'owner' ? (
                  <Button variant="outline" size="sm" onClick={() => setTransferTarget(m)}>转移所有权</Button>
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
        description={`确认将「${ws.name}」转移给 ${transferTarget?.username ?? ''}？`}
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

function GroupsDialog({ ws, onClose }: { ws: Workspace; onClose: () => void }) {
  const user = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const canManage = user?.is_superuser || ws.my_role === 'owner' || ws.my_role === 'admin'
  const { data: groups, isLoading, refetch } = useQuery({
    queryKey: ['ws-groups', ws.id],
    queryFn: () => workspacesApi.listGroups(ws.id),
  })
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [groupMembers, setGroupMembers] = useState<GroupItem | null>(null)
  const [kbGrants, setKbGrants] = useState<GroupItem | null>(null)

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    try {
      await workspacesApi.createGroup(ws.id, { name, code })
      toast('success', '群组已创建')
      setName('')
      setCode('')
      void refetch()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleDeleteGroup(group: GroupItem) {
    try {
      await workspacesApi.removeGroup(ws.id, group.id)
      toast('success', '群组已删除')
      void refetch()
      void queryClient.invalidateQueries({ queryKey: ['ws-list'] })
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <>
      <Dialog open onOpenChange={onClose} title={`群组管理：${ws.name}`} className="max-w-2xl">
        {canManage ? (
          <form onSubmit={handleCreate} className="mb-4 flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3 sm:flex-row">
            <div className="flex-1">
              <Label htmlFor="grp-name">名称</Label>
              <Input id="grp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：研发组" />
            </div>
            <div className="flex-1">
              <Label htmlFor="grp-code">编码</Label>
              <Input id="grp-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="rd_group" />
            </div>
            <Button type="submit" disabled={!name.trim() || !code.trim()} className="self-end">创建群组</Button>
          </form>
        ) : null}
        {isLoading ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : (groups ?? []).length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">暂无群组</p>
        ) : (
          <div className="space-y-2">
            {(groups ?? []).map((g) => (
              <div key={g.id} className="flex items-center gap-3 rounded-xl border border-border px-3 py-2.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                  <UsersRound className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{g.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">{g.code} · {g.member_count} 人</p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setGroupMembers(g)}>成员</Button>
                <Button variant="ghost" size="sm" onClick={() => setKbGrants(g)}>知识库授权</Button>
                {canManage ? (
                  <Button variant="ghost" size="icon" title="删除" className="text-destructive" onClick={() => handleDeleteGroup(g)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Dialog>
      {groupMembers ? (
        <GroupMembersDialog ws={ws} group={groupMembers} onClose={() => setGroupMembers(null)} />
      ) : null}
      {kbGrants ? (
        <KbGrantsDialog group={kbGrants} onClose={() => setKbGrants(null)} />
      ) : null}
    </>
  )
}

function GroupMembersDialog({ ws, group, onClose }: { ws: Workspace; group: GroupItem; onClose: () => void }) {
  const { toast } = useToast()
  const { data: members, isLoading, refetch } = useQuery({
    queryKey: ['group-members', group.id],
    queryFn: () => workspacesApi.listGroupMembers(ws.id, group.id),
  })
  const [username, setUsername] = useState('')

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    try {
      await workspacesApi.addGroupMember(ws.id, group.id, username)
      toast('success', '群组成员已添加')
      setUsername('')
      void refetch()
    } catch (err) {
      toast('error', '添加失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleRemove(userId: string, name: string) {
    try {
      await workspacesApi.removeGroupMember(ws.id, group.id, userId)
      toast('success', '成员已移除', `已从群组移除 ${name}`)
      void refetch()
    } catch (err) {
      toast('error', '移除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <Dialog open onOpenChange={onClose} title={`群组成员：${group.name}`}>
      <form onSubmit={handleAdd} className="mb-4 flex gap-2">
        <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="输入用户名" />
        <Button type="submit" disabled={!username.trim()}>添加</Button>
      </form>
      {isLoading ? (
        <Skeleton className="h-32 w-full rounded-xl" />
      ) : (
        <div className="space-y-2">
          {(members ?? []).map((m) => (
            <div key={m.user_id} className="flex items-center justify-between rounded-xl border border-border px-3 py-2.5">
              <div>
                <p className="text-sm font-medium">{m.full_name || m.username}</p>
                <p className="text-xs text-muted-foreground">@{m.username}</p>
              </div>
              <Button variant="ghost" size="sm" className="text-destructive" onClick={() => handleRemove(m.user_id, m.username || '')}>
                移除
              </Button>
            </div>
          ))}
        </div>
      )}
    </Dialog>
  )
}

function KbGrantsDialog({ group, onClose }: { group: GroupItem; onClose: () => void }) {
  const { toast } = useToast()
  const { data: kbs } = useQuery({
    queryKey: ['kb-list-options'],
    queryFn: () => kbApi.list({ page: 1, page_size: 100 }),
  })
  const [kbId, setKbId] = useState('')
  const [role, setRole] = useState('viewer')
  const [grants, setGrants] = useState<import('@/api/types').KbGroupGrantItem[]>([])
  const [loaded, setLoaded] = useState(false)

  async function loadGrants() {
    if (loaded) return
    const kbItems = kbs?.items ?? []
    const all: import('@/api/types').KbGroupGrantItem[] = []
    for (const kb of kbItems) {
      const items = await kbApi.listGroupGrants(kb.id).catch(() => [])
      all.push(...items.filter((g) => g.group_id === group.id))
    }
    setGrants(all)
    setLoaded(true)
  }
  void loadGrants()

  async function handleGrant(e: FormEvent) {
    e.preventDefault()
    try {
      await kbApi.grantGroup(kbId, group.id, role as 'viewer')
      toast('success', '群组授权已更新')
      setLoaded(false)
      setGrants([])
      void loadGrants()
    } catch (err) {
      toast('error', '授权失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleRevoke(grant: import('@/api/types').KbGroupGrantItem) {
    try {
      await kbApi.revokeGroup(grant.kb_id, grant.group_id)
      toast('success', '授权已撤销')
      setGrants((prev) => prev.filter((g) => g.id !== grant.id))
    } catch (err) {
      toast('error', '撤销失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <Dialog open onOpenChange={onClose} title={`知识库授权：${group.name}`} className="max-w-2xl">
      <form onSubmit={handleGrant} className="mb-4 flex flex-col gap-2 rounded-xl border border-border bg-muted/40 p-3 sm:flex-row">
        <div className="flex-1">
          <Label>知识库</Label>
          <Select value={kbId} onChange={(e) => setKbId(e.target.value)}>
            <option value="">选择知识库</option>
            {(kbs?.items ?? []).map((kb) => (
              <option key={kb.id} value={kb.id}>{kb.name}</option>
            ))}
          </Select>
        </div>
        <div>
          <Label>角色</Label>
          <Select className="w-28" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="viewer">查看者</option>
            <option value="editor">编辑者</option>
            <option value="admin">管理员</option>
          </Select>
        </div>
        <Button type="submit" disabled={!kbId} className="self-end">授权</Button>
      </form>
      <div className="space-y-2">
        {grants.map((g) => (
          <div key={g.id} className="flex items-center justify-between rounded-xl border border-border px-3 py-2.5">
            <div>
              <p className="text-sm font-medium">{g.group_name}</p>
              <p className="text-xs text-muted-foreground">知识库 {g.kb_id.slice(0, 8)} · {roleLabels[g.role]}</p>
            </div>
            <Button variant="ghost" size="sm" className="text-destructive" onClick={() => handleRevoke(g)}>撤销</Button>
          </div>
        ))}
        {grants.length === 0 ? <p className="py-4 text-center text-sm text-muted-foreground">暂无授权</p> : null}
      </div>
    </Dialog>
  )
}
