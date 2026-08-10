import type { FormEvent } from 'react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Eye,
  EyeOff,
  FileSearch,
  KeyRound,
  Loader2,
  ShieldCheck,
  Sparkles,
  User as UserIcon,
} from 'lucide-react'
import { useAuthStore } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/api/client'
import { cn } from '@/lib/utils'

export default function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const login = useAuthStore((s) => s.login)
  const { toast } = useToast()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleLogin(e: FormEvent) {
    e.preventDefault()
    if (!username || !password) {
      toast('warning', '请填写完整', '用户名和密码不能为空')
      return
    }
    setLoading(true)
    try {
      await login(username, password)
      toast('success', '登录成功', `欢迎回来，${username}`)
      const redirect = searchParams.get('redirect') || '/'
      navigate(redirect, { replace: true })
    } catch (err) {
      toast('error', '登录失败', err instanceof ApiError ? err.message : '用户名或密码错误')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative grid min-h-dvh overflow-hidden lg:grid-cols-2">
      {/* ===== 品牌区：绿意光晕 + 文档网格 ===== */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-emerald-50 via-white to-teal-50 p-12 lg:flex">
        <div className="doc-grid absolute inset-0" aria-hidden="true" />
        <div className="aurora aurora-a -left-24 -top-24 h-96 w-96" aria-hidden="true" />
        <div className="aurora aurora-b -bottom-32 right-0 h-[28rem] w-[28rem]" aria-hidden="true" />
        <div className="aurora aurora-c left-1/3 top-1/2 h-72 w-72" aria-hidden="true" />

        <div className="animate-fade-up relative flex items-center gap-3">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
            <FileSearch className="h-6 w-6" strokeWidth={1.6} />
            <span className="pulse-dot absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-emerald-400" />
          </div>
          <div>
            <p className="font-display text-xl font-semibold">HansonDOC RAG</p>
            <p className="text-sm text-muted-foreground">文档智能解析与检索增强生成</p>
          </div>
        </div>

        <div className="relative max-w-lg">
          <div className="animate-fade-up" style={{ animationDelay: '80ms' }}>
            <p className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-white/70 px-3 py-1 text-xs font-medium text-primary-strong shadow-soft backdrop-blur">
              <Sparkles className="h-3.5 w-3.5" />
              内网部署 · 数据不出网
            </p>
            <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight">
              知识库驱动的
              <span className="bg-gradient-to-r from-emerald-600 to-teal-500 bg-clip-text text-transparent">
                {' '}文档智能平台
              </span>
            </h1>
            <p className="mt-4 text-sm leading-6 text-muted-foreground">
              面向垂直领域文档的结构化抽取与 RAG 问答系统，以知识库为隔离边界，安全、可控、可审计。
            </p>
          </div>
          <div
            className="animate-fade-up mt-8 grid gap-3 sm:grid-cols-2"
            style={{ animationDelay: '180ms' }}
          >
            {[
              { icon: ShieldCheck, title: '权限体系', desc: 'RBAC 角色 + 审计留痕' },
              { icon: KeyRound, title: '账户安全', desc: '双令牌 + 失败锁定' },
            ].map((item) => (
              <div
                key={item.title}
                className="card-hover flex items-start gap-3 rounded-xl border border-emerald-100 bg-white/70 p-4 shadow-soft backdrop-blur"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                  <item.icon className="h-4.5 w-4.5" strokeWidth={1.8} />
                </span>
                <div>
                  <p className="text-sm font-medium">{item.title}</p>
                  <p className="text-xs text-muted-foreground">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="animate-fade-in relative text-xs text-muted-foreground" style={{ animationDelay: '300ms' }}>
          © 2026 HansonDOC RAG · 文档智能解析平台
        </p>
      </div>

      {/* ===== 登录表单 ===== */}
      <div className="relative flex items-center justify-center overflow-hidden bg-background p-6">
        <div className="aurora aurora-b -right-32 -top-32 h-80 w-80 lg:hidden" aria-hidden="true" />
        <div className="relative w-full max-w-sm">
          <div className="animate-fade-up mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-glow">
              <FileSearch className="h-5 w-5" />
            </div>
            <div>
              <p className="font-display font-semibold">HansonDOC RAG</p>
              <p className="text-xs text-muted-foreground">文档智能解析平台</p>
            </div>
          </div>

          <div className="animate-fade-up" style={{ animationDelay: '60ms' }}>
            <h2 className="font-display text-2xl font-semibold tracking-tight">欢迎回来</h2>
            <p className="mt-1 text-sm text-muted-foreground">登录以进入你的工作台</p>
          </div>

          <form onSubmit={handleLogin} className="mt-8 space-y-4">
            <div className="animate-fade-up space-y-1.5" style={{ animationDelay: '120ms' }}>
              <Label htmlFor="username">用户名</Label>
              <div className="relative">
                <UserIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="username"
                  className="pl-9"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  autoComplete="username"
                  disabled={loading}
                />
              </div>
            </div>
            <div className="animate-fade-up space-y-1.5" style={{ animationDelay: '180ms' }}>
              <Label htmlFor="password">密码</Label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  className="pl-9 pr-10"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition-colors hover:text-primary-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="animate-fade-up" style={{ animationDelay: '240ms' }}>
              <Button type="submit" className={cn('w-full', loading && 'opacity-80')} size="lg" disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {loading ? '登录中...' : '登 录'}
              </Button>
            </div>
          </form>

          <p
            className="animate-fade-in mt-8 text-center text-xs text-muted-foreground"
            style={{ animationDelay: '320ms' }}
          >
            HansonDOC · 文档智能解析与 RAG 系统
          </p>
        </div>
      </div>
    </div>
  )
}
