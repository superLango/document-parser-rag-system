import type { FormEvent } from 'react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { KeyRound, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { apiKeysApi } from '@/api/modules/apiKeys'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { formatDateTime } from '@/lib/utils'

export default function ApiKeysPage() {
  const { toast } = useToast()
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['api-keys'],
    queryFn: apiKeysApi.list,
  })
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState('')
  const [secret, setSecret] = useState<string | null>(null)

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    try {
      const scopesList = scopes
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const created = await apiKeysApi.create({ name, scopes: scopesList })
      setSecret(created.secret ?? null)
      setName('')
      setScopes('')
      void refetch()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleRevoke(id: string, keyName: string) {
    try {
      await apiKeysApi.revoke(id)
      toast('success', 'API Key 已撤销', `已撤销 ${keyName}`)
      void refetch()
    } catch (err) {
      toast('error', '撤销失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="开发者"
        title="API 密钥"
        description="为脚本与集成创建访问凭证；密钥仅创建时展示一次，支持作用域限制"
        actions={
          <Button onClick={() => { setCreating(true); setSecret(null) }}>
            <Plus className="h-4 w-4" />
            新建密钥
          </Button>
        }
      />

      <Card>
        <CardContent className="p-6">
          {isLoading ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : (data ?? []).length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-primary">
                <KeyRound className="h-7 w-7" strokeWidth={1.5} />
              </span>
              <p className="text-sm font-medium">暂无 API 密钥</p>
              <p className="text-xs text-muted-foreground">创建密钥后可调用平台 API</p>
            </div>
          ) : (
            <div className="space-y-3">
              {(data ?? []).map((key) => (
                <div key={key.id} className="flex flex-col gap-3 rounded-xl border border-border bg-muted/30 p-4 sm:flex-row sm:items-center">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary-strong">
                    <KeyRound className="h-5 w-5" strokeWidth={1.7} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {key.name}
                      {key.revoked_at ? (
                        <Badge variant="destructive" className="ml-2">已撤销</Badge>
                      ) : null}
                    </p>
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                      {key.key_prefix}•••••••• · 创建于 {formatDateTime(key.created_at)}
                      {key.last_used_at ? ` · 最近使用 ${formatDateTime(key.last_used_at)}` : ''}
                    </p>
                    {key.scopes.length ? (
                      <p className="mt-1 flex flex-wrap gap-1">
                        {key.scopes.map((s) => (
                          <Badge key={s} variant="outline">{s}</Badge>
                        ))}
                      </p>
                    ) : null}
                  </div>
                  {!key.revoked_at ? (
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => handleRevoke(key.id, key.name)}>
                      <Trash2 className="h-4 w-4" />
                      撤销
                    </Button>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={creating}
        onOpenChange={(open) => { setCreating(open); if (!open) setSecret(null) }}
        title="新建 API 密钥"
        description="创建后仅展示一次，请立即保存"
        footer={
          secret ? (
            <Button variant="secondary" onClick={() => { setCreating(false); setSecret(null) }}>
              我已保存
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setCreating(false)}>取消</Button>
              <Button type="submit" form="key-form">创建密钥</Button>
            </>
          )
        }
      >
        {secret ? (
          <div className="space-y-3">
            <div className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 p-3 text-xs text-warning">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              此密钥不会再次展示，请立即复制保存
            </div>
            <div className="rounded-xl border border-border bg-muted/60 p-3">
              <p className="break-all font-mono text-sm">{secret}</p>
            </div>
          </div>
        ) : (
          <form id="key-form" onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="key-name">名称</Label>
              <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：CI 集成" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="key-scopes">作用域（逗号分隔，可空）</Label>
              <Input
                id="key-scopes"
                value={scopes}
                onChange={(e) => setScopes(e.target.value)}
                placeholder="如：user.view,audit.view"
              />
            </div>
          </form>
        )}
      </Dialog>
    </div>
  )
}
