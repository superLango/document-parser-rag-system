import type { Dispatch, FormEvent, SetStateAction } from 'react'
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Pencil,
  Plus,
  RefreshCcw,
  Search,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserX,
  UserCheck,
  KeyRound,
} from 'lucide-react'
import { usersApi } from '@/api/modules/users'
import { rolesApi } from '@/api/modules/roles'
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
import { PasswordStrengthMeter } from '@/components/PasswordStrengthMeter'
import { formatDateTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import type { Role, RoleBrief, User } from '@/api/types'

interface UserForm {
  username: string
  email: string
  password: string
  full_name: string
  phone: string
  department: string
  is_superuser: boolean
  role_codes: string[]
}

const emptyForm: UserForm = {
  username: '',
  email: '',
  password: '',
  full_name: '',
  phone: '',
  department: '',
  is_superuser: false,
  role_codes: ['member'],
}

export default function UsersPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const { data: rolesData } = useQuery({
    queryKey: ['roles'],
    queryFn: rolesApi.list,
    retry: false,
  })

  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [activeFilter, setActiveFilter] = useState('')

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['users', page, pageSize, search, activeFilter],
    queryFn: () =>
      usersApi.list({
        page,
        page_size: pageSize,
        keyword: search || undefined,
        is_active: activeFilter === '' ? undefined : activeFilter === 'true',
      }),
  })

  const [editing, setEditing] = useState<User | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<UserForm>(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null)

  const list = useMemo(() => data?.items ?? [], [data])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['users'] })
    void refetch()
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await usersApi.create({
        username: form.username,
        email: form.email || undefined,
        password: form.password,
        full_name: form.full_name || undefined,
        phone: form.phone || undefined,
        department: form.department || undefined,
        is_superuser: form.is_superuser,
        role_codes: form.role_codes,
      })
      toast('success', '用户已创建')
      setCreating(false)
      setForm(emptyForm)
      invalidate()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleUpdate(e: FormEvent) {
    e.preventDefault()
    if (!editing) return
    setSubmitting(true)
    try {
      await usersApi.update(editing.id, {
        email: form.email || undefined,
        full_name: form.full_name || undefined,
        phone: form.phone || undefined,
        department: form.department || undefined,
        is_active: editing.is_active,
        is_superuser: form.is_superuser,
        role_codes: form.role_codes,
      })
      toast('success', '用户已更新')
      setEditing(null)
      invalidate()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleActive(user: User) {
    try {
      await usersApi.setActive(user.id, !user.is_active)
      toast('success', user.is_active ? '已禁用该用户' : '已启用该用户')
      invalidate()
    } catch (err) {
      toast('error', '操作失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function toggleSuperuser(user: User) {
    try {
      await usersApi.setSuperuser(user.id, !user.is_superuser)
      toast('success', user.is_superuser ? '已取消超管权限' : '已设为超管')
      invalidate()
    } catch (err) {
      toast('error', '操作失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleResetPassword(e: FormEvent) {
    e.preventDefault()
    if (!resetTarget) return
    setSubmitting(true)
    try {
      await usersApi.resetPassword(resetTarget.id, resetPassword)
      toast('success', '密码已重置', `用户 ${resetTarget.username} 的密码已更新`)
      setResetTarget(null)
      setResetPassword('')
    } catch (err) {
      toast('error', '重置失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await usersApi.delete(deleteTarget.id)
      toast('success', '用户已删除', `用户 ${deleteTarget.username} 已软删除`)
      setDeleteTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function approvePending(user: User) {
    try {
      await usersApi.approve(user.id)
      toast('success', '用户已审批通过', `${user.username} 已成为普通成员`)
      invalidate()
    } catch (err) {
      toast('error', '审批失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  function openEdit(user: User) {
    setEditing(user)
    setForm({
      username: user.username,
      email: user.email ?? '',
      password: '',
      full_name: user.full_name ?? '',
      phone: user.phone ?? '',
      department: user.department ?? '',
      is_superuser: user.is_superuser,
      role_codes:
        user.roles?.map((r) => r.code) ??
        (user.is_superuser ? ['super_admin'] : ['member']),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="用户管理"
        description="管理系统用户、启用状态与超级管理员权限"
        actions={
          <Button onClick={() => { setCreating(true); setForm(emptyForm) }}>
            <Plus className="h-4 w-4" />
            新建用户
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
                  placeholder="搜索用户名 / 邮箱 / 姓名"
                />
              </div>
              <Button type="submit" variant="secondary">搜索</Button>
            </form>
            <Select
              className="w-full sm:w-40"
              value={activeFilter}
              onChange={(e) => {
                setActiveFilter(e.target.value)
                setPage(1)
              }}
            >
              <option value="">全部状态</option>
              <option value="true">已启用</option>
              <option value="false">已禁用</option>
            </Select>
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
                <TableHead>用户名</TableHead>
                <TableHead>姓名 / 邮箱</TableHead>
                <TableHead>部门</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>最近登录</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7}><Skeleton className="h-16 w-full" /></TableCell>
                </TableRow>
              ) : list.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
                    暂无用户
                  </TableCell>
                </TableRow>
              ) : (
                list.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">{user.username}</TableCell>
                    <TableCell>
                      <p>{user.full_name || '—'}</p>
                      <p className="text-xs text-muted-foreground">{user.email || '—'}</p>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{user.department || '—'}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(user.roles?.length
                          ? user.roles
                          : user.is_superuser
                            ? [{ id: '', code: 'super_admin', name: '超管', is_system: true } as RoleBrief]
                            : [{ id: '', code: 'member', name: '普通用户', is_system: true } as RoleBrief]
                        ).map((r) => (
                          <Badge
                            key={r.code}
                            variant={r.code === 'super_admin' ? 'success' : r.code === 'pending' ? 'warning' : 'outline'}
                          >
                            {r.code === 'super_admin' ? <ShieldCheck className="h-3 w-3" /> : null}
                            {r.name}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? 'success' : 'destructive'}>
                        {user.is_active ? '启用' : '禁用'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(user.last_login_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {user.roles?.some((r) => r.code === 'pending') ? (
                          <Button
                            variant="ghost"
                            size="icon"
                            title="审批通过"
                            className="text-success"
                            onClick={() => approvePending(user)}
                          >
                            <ShieldCheck className="h-4 w-4" />
                          </Button>
                        ) : null}
                        <Button variant="ghost" size="icon" title="编辑" onClick={() => openEdit(user)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          title={user.is_superuser ? '取消超管' : '设为超管'}
                          disabled={currentUser?.id === user.id}
                          onClick={() => toggleSuperuser(user)}
                        >
                          {user.is_superuser ? <ShieldOff className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          title={user.is_active ? '禁用' : '启用'}
                          disabled={currentUser?.id === user.id}
                          onClick={() => toggleActive(user)}
                        >
                          {user.is_active ? <UserX className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}
                        </Button>
                        <Button variant="ghost" size="icon" title="重置密码" onClick={() => { setResetTarget(user); setResetPassword('') }}>
                          <KeyRound className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          title="删除"
                          className="text-destructive"
                          disabled={currentUser?.id === user.id}
                          onClick={() => setDeleteTarget(user)}
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
          <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} onPageChange={setPage} />
        </CardContent>
      </Card>

      {/* 新建用户 */}
      <Dialog
        open={creating}
        onOpenChange={setCreating}
        title="新建用户"
        description="创建后用户可使用该密码直接登录"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreating(false)}>取消</Button>
            <Button type="submit" form="user-form" disabled={submitting}>
              {submitting ? '创建中...' : '创建用户'}
            </Button>
          </>
        }
      >
        <UserFormFields
          form={form}
          setForm={setForm}
          onSubmit={handleCreate}
          showPassword
          roles={rolesData}
        />
      </Dialog>

      {/* 编辑用户 */}
      <Dialog
        open={editing !== null}
        onOpenChange={(open) => { if (!open) setEditing(null) }}
        title={`编辑用户：${editing?.username ?? ''}`}
        description="仅可修改资料与角色信息，密码请使用“重置密码”"
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
            <Button type="submit" form="user-form" disabled={submitting}>
              {submitting ? '保存中...' : '保存'}
            </Button>
          </>
        }
      >
        <UserFormFields
          form={form}
          setForm={setForm}
          onSubmit={handleUpdate}
          showPassword={false}
          roles={rolesData}
        />
      </Dialog>

      {/* 重置密码 */}
      <Dialog
        open={resetTarget !== null}
        onOpenChange={(open) => { if (!open) setResetTarget(null) }}
        title={`重置密码：${resetTarget?.username ?? ''}`}
        description="重置后旧密码立即失效，请通知用户使用新密码登录"
        footer={
          <>
            <Button variant="outline" onClick={() => setResetTarget(null)}>取消</Button>
            <Button type="submit" form="reset-form" disabled={submitting}>
              {submitting ? '重置中...' : '确认重置'}
            </Button>
          </>
        }
      >
        <form id="reset-form" onSubmit={handleResetPassword} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="reset_password">新密码</Label>
            <Input
              id="reset_password"
              type="password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
            />
            <PasswordStrengthMeter password={resetPassword} />
          </div>
        </form>
      </Dialog>

      {/* 删除确认 */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="删除用户"
        description={`确认删除用户「${deleteTarget?.username ?? ''}」？删除为软删除，不可登录，历史审计数据保留。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete}>确认删除</Button>
          </>
        }
      />
    </div>
  )
}

interface UserFormFieldsProps {
  form: UserForm
  setForm: Dispatch<SetStateAction<UserForm>>
  onSubmit: (e: FormEvent) => void
  showPassword: boolean
  roles?: Role[]
}

function UserFormFields({ form, setForm, onSubmit, showPassword, roles }: UserFormFieldsProps) {
  return (
    <form id="user-form" onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="u-username">用户名</Label>
        <Input
          id="u-username"
          value={form.username}
          onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
          disabled={!showPassword}
          placeholder="3-50 个字符"
        />
      </div>
      {showPassword ? (
        <div className="space-y-1.5">
          <Label htmlFor="u-password">初始密码</Label>
          <Input
            id="u-password"
            type="password"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          />
          <PasswordStrengthMeter password={form.password} />
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor="u-email">邮箱</Label>
        <Input
          id="u-email"
          type="email"
          value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="u-full-name">姓名</Label>
          <Input
            id="u-full-name"
            value={form.full_name}
            onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="u-phone">手机号</Label>
          <Input
            id="u-phone"
            value={form.phone}
            onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="u-department">部门</Label>
        <Input
          id="u-department"
          value={form.department}
          onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
        />
      </div>
      {roles && roles.length > 0 ? (
        <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-3">
          <Label>系统角色</Label>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {roles.map((role) => (
              <label key={role.code} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.role_codes.includes(role.code)}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...form.role_codes, role.code]
                      : form.role_codes.filter((c) => c !== role.code)
                    setForm((f) => ({
                      ...f,
                      role_codes: next,
                      is_superuser: next.includes('super_admin'),
                    }))
                  }}
                  className="h-4 w-4 rounded border-input accent-emerald-600"
                />
                {role.name}
                {role.is_system ? <span className="text-xs text-muted-foreground">内置</span> : null}
              </label>
            ))}
          </div>
        </div>
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.is_superuser}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              is_superuser: e.target.checked,
              role_codes: e.target.checked ? ['super_admin'] : ['member'],
            }))
          }
          className="h-4 w-4 rounded border-input accent-emerald-600"
        />
        超级管理员（等价分配 super_admin 角色）
      </label>
    </form>
  )
}
