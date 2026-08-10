import type { CSSProperties, FormEvent } from 'react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { UserCombobox } from '@/components/UserCombobox'
import type { KbItem, KbRole, UserSearchItem } from '@/api/types'

const roleLabels: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

interface MemberSeed extends UserSearchItem {
  role: KbRole
}

interface KbForm {
  name: string
  description: string
}

const emptyForm: KbForm = { name: '', description: '' }

export default function KnowledgeBasesPage() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<KbForm>(emptyForm)
  const [members, setMembers] = useState<MemberSeed[]>([])
  const [memberUser, setMemberUser] = useState<UserSearchItem | null>(null)
  const [memberRole, setMemberRole] = useState<KbRole>('viewer')
  const [submitting, setSubmitting] = useState(false)
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
    if (!memberUser || !memberUser.username) return
    if (members.some((m) => m.username === memberUser.username)) {
      toast('warning', '成员已添加', `${memberUser.username} 已在初始成员列表中`)
      return
    }
    setMembers((prev) => [...prev, { ...memberUser, role: memberRole }])
    setMemberUser(null)
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
        members: members.map((m) => ({ username: m.username, role: m.role })),
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
      setMemberUser(null)
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
description="以知识库为隔离边界的垂直领域文档智能产品"
        actions={
          <Button
            onClick={() => {
              setCreating(true)
              setForm(emptyForm)
              setMembers([])
              setMemberUser(null)
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
              onMembers={() => navigate(`/kb/${kb.id}/members`)}
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
            <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-end">
              <div>
                <Label>成员</Label>
                <UserCombobox value={memberUser} onSelect={setMemberUser} />
              </div>
              <div>
                <Label>权限</Label>
                <Select
                  className="w-full sm:w-32"
                  value={memberRole}
                  onChange={(e) => setMemberRole(e.target.value as KbRole)}
                >
                  <option value="viewer">查看者</option>
                  <option value="editor">编辑者</option>
                  <option value="admin">管理员</option>
                </Select>
              </div>
              <Button
                type="button"
                variant="secondary"
                onClick={addMemberSeed}
                disabled={!memberUser?.username}
                className="sm:mb-px"
              >
                添加
              </Button>
            </div>
            {members.length > 0 ? (
              <div className="space-y-1.5 pt-1">
                {members.map((m) => (
                  <div
                    key={m.username}
                    className="flex items-center gap-3 rounded-lg border border-border bg-white/70 px-3 py-2 shadow-soft"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 text-xs font-semibold text-primary-strong">
                      {(m.full_name || m.username || 'U').slice(0, 1).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{m.full_name || m.username}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        @{m.username}
                        {m.department ? ` · ${m.department}` : ''}
                      </p>
                    </div>
                    <Badge variant="outline">{roleLabels[m.role]}</Badge>
                    <button
                      type="button"
                      onClick={() => removeMemberSeed(m.username)}
                      className="rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
                      aria-label={`移除 ${m.username}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                从系统现有成员中选择，可添加多人；创建后将发送邀请
              </p>
            )}
          </div>
        </form>
      </Dialog>

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
  const navigate = useNavigate()
  const canManage = kb.my_role === 'owner' || kb.my_role === 'admin'
  return (
    <Card
      interactive
      onClick={() => navigate(`/kb/${kb.id}`)}
      className="animate-fade-up group relative flex cursor-pointer flex-col overflow-hidden"
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
            <Button
              variant="ghost"
              size="sm"
              title="成员管理"
              onClick={(e) => {
                e.stopPropagation()
                onMembers()
              }}
            >
              <Users className="h-4 w-4" />
              成员
            </Button>
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                title="删除"
                className="text-destructive"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete()
                }}
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
