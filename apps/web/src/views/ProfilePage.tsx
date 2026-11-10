import type { CSSProperties, FormEvent } from 'react'
import { useState } from 'react'
import {
  Building2,
  CalendarDays,
  Image as ImageIcon,
  KeyRound,
  Mail,
  MonitorSmartphone,
  Phone,
  Save,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { authApi } from '@/api/modules/auth'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { PasswordStrengthMeter } from '@/components/PasswordStrengthMeter'
import { useToast } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/auth'
import { cn, formatDate, formatDateTime } from '@/lib/utils'

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const { toast } = useToast()

  const [form, setForm] = useState({
    email: user?.email ?? '',
    full_name: user?.full_name ?? '',
    phone: user?.phone ?? '',
    department: user?.department ?? '',
    avatar: user?.avatar ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [avatarBroken, setAvatarBroken] = useState(false)

  const [pwd, setPwd] = useState({ old_password: '', new_password: '', confirm: '' })
  const [changing, setChanging] = useState(false)

  const initial = (user?.full_name || user?.username || 'U').slice(0, 1).toUpperCase()

  const metaTiles = [
    {
      label: '账号状态',
      value: user?.is_active ? '正常' : '已停用',
      sub: user?.is_superuser ? '系统最高权限' : '标准成员',
      icon: ShieldCheck,
      tone: 'bg-emerald-50 text-emerald-600',
    },
    {
      label: '最近登录',
      value: formatDateTime(user?.last_login_at),
      sub: user?.last_login_ip ? `IP ${user.last_login_ip}` : '暂无 IP 记录',
      icon: MonitorSmartphone,
      tone: 'bg-sky-50 text-sky-600',
    },
    {
      label: '注册时间',
      value: formatDate(user?.created_at),
      sub: '账户创建日期',
      icon: CalendarDays,
      tone: 'bg-amber-50 text-amber-600',
    },
  ]

  async function handleSaveProfile(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const updated = await authApi.updateProfile({
        full_name: form.full_name || undefined,
      })
      setUser(updated)
      toast('success', '资料已更新')
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault()
    if (pwd.new_password !== pwd.confirm) {
      toast('warning', '两次输入的新密码不一致')
      return
    }
    setChanging(true)
    try {
      await authApi.changePassword({
        old_password: pwd.old_password,
        new_password: pwd.new_password,
      })
      toast('success', '密码修改成功', '请妥善保管新密码')
      setPwd({ old_password: '', new_password: '', confirm: '' })
    } catch (err) {
      toast('error', '修改失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setChanging(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="账户" title="个人中心" description="管理你的账户资料、安全信息与登录密码" />

      {/* ===== 签名横幅：账户卡片 ===== */}
      <div className="animate-fade-up relative overflow-hidden rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50 via-white to-teal-50 shadow-soft">
        <div className="doc-grid absolute inset-0" aria-hidden="true" />
        <div className="aurora aurora-a -right-16 -top-24 h-64 w-64" aria-hidden="true" />
        <div className="aurora aurora-b -bottom-24 left-1/4 h-56 w-56" aria-hidden="true" />
        <div className="relative flex flex-col gap-6 p-6 sm:p-8 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-4 sm:gap-5">
            <div className="relative shrink-0">
              {form.avatar && !avatarBroken ? (
                <img
                  key={form.avatar}
                  src={form.avatar}
                  alt="头像预览"
                  onError={() => setAvatarBroken(true)}
                  className="h-16 w-16 rounded-full object-cover shadow-glow ring-2 ring-white sm:h-20 sm:w-20"
                />
              ) : (
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 font-display text-2xl font-semibold text-white shadow-glow ring-2 ring-white sm:h-20 sm:w-20">
                  {initial}
                </div>
              )}
              <span
                className={cn(
                  'pulse-dot absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full ring-4 ring-white',
                  user?.is_active ? 'bg-success' : 'bg-muted-foreground',
                )}
              />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-display text-2xl font-semibold tracking-tight">
                  {user?.full_name || user?.username}
                </h2>
                {(user?.roles?.length ? user.roles : []).map((role) => (
                  <Badge key={role.code} variant={role.code === 'super_admin' ? 'success' : 'secondary'} dot>
                    {role.name}
                  </Badge>
                ))}
              </div>
              <p className="mt-1 font-mono text-sm text-muted-foreground">@{user?.username}</p>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Mail className="h-3.5 w-3.5 text-primary" />
                  {user?.email || '未绑定邮箱'}
                </span>
                {user?.department ? (
                  <span className="flex items-center gap-1.5">
                    <Building2 className="h-3.5 w-3.5 text-primary" />
                    {user.department}
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="grid shrink-0 gap-3 sm:grid-cols-3 lg:max-w-xl">
            {metaTiles.map((tile) => (
              <div
                key={tile.label}
                className="flex items-center gap-2.5 rounded-xl border border-emerald-100 bg-white/80 px-3.5 py-2.5 shadow-soft backdrop-blur"
              >
                <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', tile.tone)}>
                  <tile.icon className="h-4 w-4" strokeWidth={1.8} />
                </span>
                <div className="min-w-0">
                  <p className="text-[11px] text-muted-foreground">{tile.label}</p>
                  <p className="truncate text-xs font-medium sm:text-sm">{tile.value}</p>
                  <p className="truncate text-[10px] text-muted-foreground">{tile.sub}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card interactive className="animate-fade-up" style={{ animationDelay: '80ms' } as CSSProperties}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                <UserRound className="h-4 w-4" strokeWidth={1.9} />
              </span>
              基本信息
            </CardTitle>
            <CardDescription>这些信息将展示在你的账户资料中</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div className="space-y-1.5">
                <Label>用户名</Label>
                <div className="relative">
                  <UserRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input value={user?.username ?? ''} disabled className="pl-9" />
                </div>
                <p className="text-xs text-muted-foreground">用户名用于登录，创建后不可修改</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="full_name">姓名</Label>
                  <Input
                    id="full_name"
                    value={form.full_name}
                    onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                    placeholder="请输入姓名"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="department">部门</Label>
                  <div className="relative">
                    <Building2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="department"
                      className="pl-9"
                      value={form.department}
                      onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
                      placeholder="请输入部门"
                    />
                  </div>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="email">邮箱</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    className="pl-9"
                    value={form.email}
                    onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                    placeholder="name@example.com"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="phone">手机号</Label>
                <div className="relative">
                  <Phone className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="phone"
                    className="pl-9"
                    value={form.phone}
                    onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                    placeholder="请输入手机号"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="avatar">头像 URL</Label>
                <div className="flex items-center gap-3">
                  {form.avatar && !avatarBroken ? (
                    <img
                      key={form.avatar}
                      src={form.avatar}
                      alt="头像预览"
                      onError={() => setAvatarBroken(true)}
                      className="h-11 w-11 shrink-0 rounded-full object-cover ring-2 ring-emerald-200"
                    />
                  ) : (
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 font-semibold text-primary-strong ring-2 ring-emerald-200">
                      {initial}
                    </div>
                  )}
                  <div className="relative flex-1">
                    <ImageIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="avatar"
                      className="pl-9"
                      value={form.avatar}
                      onChange={(e) => {
                        setForm((f) => ({ ...f, avatar: e.target.value }))
                        setAvatarBroken(false)
                      }}
                      placeholder="https://..."
                    />
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
                <p className="text-xs text-muted-foreground">保存后立即生效</p>
                <Button type="submit" disabled={saving}>
                  <Save className="h-4 w-4" />
                  {saving ? '保存中...' : '保存资料'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card interactive className="animate-fade-up" style={{ animationDelay: '140ms' } as CSSProperties}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                <KeyRound className="h-4 w-4" strokeWidth={1.9} />
              </span>
              修改密码
            </CardTitle>
            <CardDescription>
              新密码需满足系统密码策略，且不能与最近 {5} 次使用的密码相同
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="old_password">当前密码</Label>
                <div className="relative">
                  <KeyRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="old_password"
                    type="password"
                    className="pl-9"
                    value={pwd.old_password}
                    onChange={(e) => setPwd((p) => ({ ...p, old_password: e.target.value }))}
                    autoComplete="current-password"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="new_password">新密码</Label>
                <div className="relative">
                  <ShieldCheck className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="new_password"
                    type="password"
                    className="pl-9"
                    value={pwd.new_password}
                    onChange={(e) => setPwd((p) => ({ ...p, new_password: e.target.value }))}
                    autoComplete="new-password"
                  />
                </div>
                <PasswordStrengthMeter password={pwd.new_password} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="confirm">确认新密码</Label>
                <div className="relative">
                  <ShieldCheck className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="confirm"
                    type="password"
                    className="pl-9"
                    value={pwd.confirm}
                    onChange={(e) => setPwd((p) => ({ ...p, confirm: e.target.value }))}
                    autoComplete="new-password"
                  />
                </div>
              </div>
              <Button type="submit" variant="secondary" disabled={changing}>
                <KeyRound className="h-4 w-4" />
                {changing ? '提交中...' : '修改密码'}
              </Button>
            </form>
            <div className="mt-6 rounded-xl border border-border bg-muted/60 p-4">
              <div className="mb-3 flex items-center gap-2 text-xs font-medium text-foreground">
                <ShieldCheck className="h-4 w-4 text-primary" />
                密码安全
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">上次修改密码</span>
                  <span className="text-right font-medium">{formatDateTime(user?.password_changed_at)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">历史密码校验</span>
                  <span className="font-medium">最近 5 次</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">账户状态</span>
                  <span className={cn('font-medium', user?.is_active ? 'text-success' : 'text-destructive')}>
                    {user?.is_active ? '正常' : '已停用'}
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
