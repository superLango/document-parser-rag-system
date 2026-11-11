import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Loader2, Plus, RefreshCcw, Search, ShieldCheck } from 'lucide-react'
import { usersApi } from '@/api/modules/users'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'
import type { UserAdminItem } from '@/api/types'

export default function UsersPage() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', full_name: '', is_superuser: false })
  const [busy, setBusy] = useState(false)
  const [pwdTarget, setPwdTarget] = useState<UserAdminItem | null>(null)
  const [newPassword, setNewPassword] = useState('')

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['users', search],
    queryFn: () => usersApi.list({ page: 1, page_size: 100, keyword: search || undefined }),
  })

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['users'] })
  }

  async function createUser() {
    setBusy(true)
    try {
      await usersApi.create(form)
      toast('success', '用户已创建', form.username)
      setCreateOpen(false)
      setForm({ username: '', password: '', full_name: '', is_superuser: false })
      invalidate()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(user: UserAdminItem) {
    try {
      await usersApi.setActive(user.id, !user.is_active)
      toast('success', user.is_active ? '已停用' : '已启用', user.username)
      invalidate()
    } catch (err) {
      toast('error', '操作失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function toggleAdmin(user: UserAdminItem) {
    try {
      await usersApi.setSuperuser(user.id, !user.is_superuser)
      toast('success', '角色已更新', `${user.username} → ${user.is_superuser ? '普通用户' : '管理员'}`)
      invalidate()
    } catch (err) {
      toast('error', '操作失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function resetPassword() {
    if (!pwdTarget || newPassword.length < 8) {
      toast('warning', '密码至少 8 位')
      return
    }
    setBusy(true)
    try {
      await usersApi.resetPassword(pwdTarget.id, newPassword)
      toast('success', '密码已重置', pwdTarget.username)
      setPwdTarget(null)
      setNewPassword('')
    } catch (err) {
      toast('error', '重置失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="系统管理"
        title="用户管理"
        description="创建账号、启用停用、调整管理员角色与重置密码"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => invalidate()} className="gap-1.5">
              <RefreshCcw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              刷新
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
              <Plus className="h-4 w-4" />
              新建用户
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="p-4">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              setSearch(keyword)
            }}
          >
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索用户名或姓名"
              />
            </div>
            <Button type="submit" variant="secondary">搜索</Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6"><Skeleton className="h-48 w-full rounded-xl" /></div>
          ) : (
            <Table className="min-w-[760px]">
              <TableHeader>
                <TableRow>
                  <TableHead>用户</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.items ?? []).map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>
                      <p className="text-sm font-medium">{user.full_name || user.username}</p>
                      <p className="text-xs text-muted-foreground">@{user.username}</p>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_superuser ? 'success' : 'secondary'}>
                        {user.is_superuser ? '管理员' : '普通用户'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? 'outline' : 'destructive'}>
                        {user.is_active ? '启用' : '停用'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(user.created_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={() => void toggleActive(user)}>
                          {user.is_active ? '停用' : '启用'}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void toggleAdmin(user)} className="gap-1">
                          <ShieldCheck className="h-3.5 w-3.5" />
                          {user.is_superuser ? '降为普通' : '设为管理员'}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setPwdTarget(user)} className="gap-1">
                          <KeyRound className="h-3.5 w-3.5" />
                          重置密码
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => { if (!open) setCreateOpen(false) }} title="新建用户">
        <div className="space-y-3">
          <div>
            <Label htmlFor="new-username">用户名</Label>
            <Input
              id="new-username"
              value={form.username}
              onChange={(event) => setForm({ ...form, username: event.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="new-display">姓名</Label>
            <Input
              id="new-display"
              value={form.full_name}
              onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="new-password">初始密码（至少 8 位）</Label>
            <Input
              id="new-password"
              type="password"
              value={form.password}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_superuser}
              onChange={(event) => setForm({ ...form, is_superuser: event.target.checked })}
            />
            设为管理员
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={busy}>取消</Button>
          <Button
            onClick={() => void createUser()}
            disabled={busy || !form.username || form.password.length < 8}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            创建
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={pwdTarget !== null}
        onOpenChange={(open) => { if (!open) setPwdTarget(null) }}
        title="重置密码"
        description={`为「${pwdTarget?.username ?? ''}」设置新密码`}
      >
        <Input
          type="password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          placeholder="至少 8 位"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setPwdTarget(null)} disabled={busy}>取消</Button>
          <Button onClick={() => void resetPassword()} disabled={busy || newPassword.length < 8}>确认</Button>
        </div>
      </Dialog>
    </div>
  )
}
