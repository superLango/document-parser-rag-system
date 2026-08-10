import type { Dispatch, FormEvent, SetStateAction } from 'react'
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Lock, Pencil, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { rolesApi } from '@/api/modules/roles'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
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
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/stores/rbac'
import type { PermissionItem, Role } from '@/api/types'

interface RoleForm {
  code: string
  name: string
  description: string
}

const emptyForm: RoleForm = { code: '', name: '', description: '' }

export default function RolesPage() {
  const user = useAuthStore((s) => s.user)
  const canManage = hasPermission(user, 'role.manage')
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const { data: roles, isLoading } = useQuery({
    queryKey: ['roles'],
    queryFn: rolesApi.list,
  })
  const { data: permissions } = useQuery({
    queryKey: ['role-permissions'],
    queryFn: rolesApi.listPermissions,
    enabled: canManage,
  })

  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Role | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null)
  const [matrixTarget, setMatrixTarget] = useState<Role | null>(null)
  const [form, setForm] = useState<RoleForm>(emptyForm)
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  const groupedPermissions = useMemo(() => {
    const groups = new Map<string, PermissionItem[]>()
    for (const p of permissions ?? []) {
      const key = p.resource_type || 'other'
      groups.set(key, [...(groups.get(key) ?? []), p])
    }
    return [...groups.entries()]
  }, [permissions])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['roles'] })
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await rolesApi.create({
        code: form.code,
        name: form.name,
        description: form.description || undefined,
      })
      toast('success', '角色已创建')
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
      await rolesApi.update(editing.id, {
        name: form.name,
        description: form.description || undefined,
      })
      toast('success', '角色已更新')
      setEditing(null)
      invalidate()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await rolesApi.remove(deleteTarget.id)
      toast('success', '角色已删除', `已删除 ${deleteTarget.name}`)
      setDeleteTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  function openMatrix(role: Role) {
    setMatrixTarget(role)
    setSelectedCodes(role.permissions ?? [])
    if (!role.permissions) {
      void rolesApi.getPermissions(role.id).then((codes) => setSelectedCodes(codes)).catch(() => undefined)
    }
  }

  async function handleSaveMatrix() {
    if (!matrixTarget) return
    setSubmitting(true)
    try {
      await rolesApi.setPermissions(matrixTarget.id, selectedCodes)
      toast('success', '权限矩阵已保存', `${matrixTarget.name} 当前 ${selectedCodes.length} 个权限点`)
      setMatrixTarget(null)
      invalidate()
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="系统管理"
        title="角色管理"
        description="维护系统角色与权限矩阵，内置角色受保护"
        actions={
          canManage ? (
            <Button onClick={() => { setCreating(true); setForm(emptyForm) }}>
              <Plus className="h-4 w-4" />
              新建角色
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>角色</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>权限数</TableHead>
                <TableHead>描述</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}><Skeleton className="h-16 w-full" /></TableCell>
                </TableRow>
              ) : (roles ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-sm text-muted-foreground">
                    暂无角色
                  </TableCell>
                </TableRow>
              ) : (
                (roles ?? []).map((role) => (
                  <TableRow key={role.id}>
                    <TableCell>
                      <p className="font-medium">{role.name}</p>
                      <p className="font-mono text-xs text-muted-foreground">{role.code}</p>
                    </TableCell>
                    <TableCell>
                      {role.is_system ? (
                        <Badge variant="secondary"><Lock className="h-3 w-3" /> 内置</Badge>
                      ) : (
                        <Badge variant="outline">自定义</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="success">{role.permission_count ?? 0} 项</Badge>
                    </TableCell>
                    <TableCell className="max-w-md text-sm text-muted-foreground">
                      {role.description || '—'}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          title={role.is_system ? '内置角色权限矩阵固定' : '权限矩阵'}
                          disabled={role.is_system}
                          onClick={() => openMatrix(role)}
                        >
                          <ShieldCheck className="h-4 w-4" />
                        </Button>
                        {canManage ? (
                          <>
                            <Button
                              variant="ghost"
                              size="icon"
                              title="编辑"
                              disabled={role.is_system}
                              onClick={() => {
                                setEditing(role)
                                setForm({
                                  code: role.code,
                                  name: role.name,
                                  description: role.description ?? '',
                                })
                              }}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              title="删除"
                              className="text-destructive"
                              disabled={role.is_system}
                              onClick={() => setDeleteTarget(role)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 新建角色 */}
      <Dialog
        open={creating}
        onOpenChange={setCreating}
        title="新建角色"
        description="自定义角色创建后可维护权限矩阵"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreating(false)}>取消</Button>
            <Button type="submit" form="role-form" disabled={submitting}>
              {submitting ? '创建中...' : '创建角色'}
            </Button>
          </>
        }
      >
        <RoleFormFields form={form} setForm={setForm} onSubmit={handleCreate} />
      </Dialog>

      {/* 编辑角色 */}
      <Dialog
        open={editing !== null}
        onOpenChange={(open) => { if (!open) setEditing(null) }}
        title={`编辑角色：${editing?.name ?? ''}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
            <Button type="submit" form="role-form" disabled={submitting}>
              {submitting ? '保存中...' : '保存'}
            </Button>
          </>
        }
      >
        <RoleFormFields form={form} setForm={setForm} onSubmit={handleUpdate} hideCode />
      </Dialog>

      {/* 权限矩阵 */}
      <Dialog
        open={matrixTarget !== null}
        onOpenChange={(open) => { if (!open) setMatrixTarget(null) }}
        title={`权限矩阵：${matrixTarget?.name ?? ''}`}
        description="勾选该角色允许访问的权限点"
        footer={
          <>
            <Button variant="outline" onClick={() => setMatrixTarget(null)}>取消</Button>
            <Button type="submit" form="matrix-form" disabled={submitting}>
              {submitting ? '保存中...' : '保存矩阵'}
            </Button>
          </>
        }
      >
        <form id="matrix-form" onSubmit={(e) => { e.preventDefault(); void handleSaveMatrix() }} className="space-y-4">
          {groupedPermissions.map(([group, items]) => (
            <div key={group}>
              <p className="mb-2 text-xs font-medium uppercase tracking-widest text-muted-foreground">{group}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {items.map((perm) => (
                  <label key={perm.code} className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedCodes.includes(perm.code)}
                      onChange={(e) => {
                        setSelectedCodes((prev) =>
                          e.target.checked
                            ? [...prev, perm.code]
                            : prev.filter((c) => c !== perm.code),
                        )
                      }}
                      className="h-4 w-4 rounded border-input accent-emerald-600"
                    />
                    <span className="font-medium">{perm.name}</span>
                    <span className="ml-auto font-mono text-[11px] text-muted-foreground">{perm.code}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </form>
      </Dialog>

      {/* 删除确认 */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="删除角色"
        description={`确认删除自定义角色「${deleteTarget?.name ?? ''}」？已分配该角色的用户将不再拥有其权限。`}
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

interface RoleFormFieldsProps {
  form: RoleForm
  setForm: Dispatch<SetStateAction<RoleForm>>
  onSubmit: (e: FormEvent) => void
  hideCode?: boolean
}

function RoleFormFields({ form, setForm, onSubmit, hideCode }: RoleFormFieldsProps) {
  return (
    <form id="role-form" onSubmit={onSubmit} className="space-y-4">
      {!hideCode ? (
        <div className="space-y-1.5">
          <Label htmlFor="r-code">角色编码</Label>
          <Input
            id="r-code"
            value={form.code}
            onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
            placeholder="如 data_operator（小写字母/数字/下划线）"
          />
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor="r-name">角色名称</Label>
        <Input
          id="r-name"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="请输入角色名称"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="r-desc">描述</Label>
        <Input
          id="r-desc"
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          placeholder="角色职责说明（可选）"
        />
      </div>
    </form>
  )
}
