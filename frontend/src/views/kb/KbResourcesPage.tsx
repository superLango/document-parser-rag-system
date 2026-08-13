import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Cpu, KeyRound, Link2, Loader2, RefreshCcw, Save } from 'lucide-react'
import { kbApi } from '@/api/modules/kb'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/auth'
import { useKbDetail } from './KbDetailLayout'

export default function KbResourcesPage() {
  const { kb, refetch } = useKbDetail()
  const user = useAuthStore((s) => s.user)
  const canManage = user?.is_superuser || kb.my_role === 'owner' || kb.my_role === 'admin' || kb.my_role === 'editor'
  const { toast } = useToast()
  const [name, setName] = useState(kb.name)
  const [description, setDescription] = useState(kb.description ?? '')
  const [saving, setSaving] = useState(false)
  const [regenerateOpen, setRegenerateOpen] = useState(false)
  const [fullToken, setFullToken] = useState<string | null>(null)

  const { data: external, isLoading: extLoading, refetch: refetchExternal } = useQuery({
    queryKey: ['kb-external', kb.id],
    queryFn: () => kbApi.getExternal(kb.id),
  })

  const [llm, setLlm] = useState({ enabled: false, api_base: '', model: '', api_key: '', timeout: 300 })
  const [llmSaving, setLlmSaving] = useState(false)
  const [llmTesting, setLlmTesting] = useState(false)
  const [llmTestResult, setLlmTestResult] = useState<{ ok: boolean; error?: string } | null>(null)
  const { data: llmConfig, isLoading: llmLoading } = useQuery({
    queryKey: ['kb-llm', kb.id],
    queryFn: () => kbApi.getLLMResource(kb.id),
  })

  useEffect(() => {
    if (llmConfig) {
      setLlm({
        enabled: llmConfig.enabled,
        api_base: llmConfig.api_base,
        model: llmConfig.model,
        api_key: '',
        timeout: llmConfig.timeout,
      })
    }
  }, [llmConfig])

  async function handleSaveLLM() {
    if (!llm.api_base.trim() || !llm.model.trim()) {
      toast('warning', '请填写服务地址与模型名称')
      return
    }
    setLlmSaving(true)
    setLlmTestResult(null)
    try {
      await kbApi.saveLLMResource(kb.id, { ...llm, api_key: llm.api_key || undefined })
      setLlm((prev) => ({ ...prev, api_key: '' }))
      toast('success', 'LLM 服务配置已保存')
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setLlmSaving(false)
    }
  }

  async function handleTestLLM() {
    setLlmTesting(true)
    setLlmTestResult(null)
    try {
      const res = await kbApi.testLLMResource(kb.id, { ...llm, api_key: llm.api_key || undefined })
      setLlmTestResult(res)
      toast(res.ok ? 'success' : 'error', res.ok ? '连接成功' : '连接失败', res.error)
    } catch (err) {
      setLlmTestResult({ ok: false, error: err instanceof ApiError ? err.message : '测试失败' })
    } finally {
      setLlmTesting(false)
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      await kbApi.update(kb.id, { name, description: description || undefined })
      toast('success', '知识库信息已更新')
      void refetch()
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  async function toggleExternal(next: boolean) {
    try {
      await kbApi.updateExternal(kb.id, { enabled: next })
      toast('success', next ? '外部访问已开启' : '外部访问已关闭')
      void refetchExternal()
    } catch (err) {
      toast('error', '更新失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function handleRegenerate() {
    setRegenerateOpen(false)
    try {
      const result = await kbApi.updateExternal(kb.id, { enabled: true, regenerate: true })
      setFullToken(result.token ?? null)
      toast('success', '已生成新的外部访问令牌')
      void refetchExternal()
    } catch (err) {
      toast('error', '生成失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  async function copyToken(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast('success', '已复制', `${label}已复制到剪贴板`)
    } catch {
      toast('error', '复制失败', '请手动复制')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="资源" title="资源与配置" description="知识库基础信息与外部联动配置" />

      <Card>
        <CardHeader>
          <CardTitle>基础信息</CardTitle>
          <CardDescription>修改知识库名称与描述</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="kb-edit-name">名称</Label>
              <Input id="kb-edit-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="kb-edit-desc">描述</Label>
              <Input id="kb-edit-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <Button type="submit" disabled={saving || !name.trim()}>
              <Save className="h-4 w-4" />
              {saving ? '保存中...' : '保存'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Link2 className="h-4 w-4 text-primary" />
              外部访问令牌
            </CardTitle>
            <CardDescription>
              供外部系统调用本知识库的访问令牌（预留）；公开上传/嵌入接口将在文档解析阶段启用
            </CardDescription>
          </div>
          <Badge variant={external?.enabled ? 'success' : 'outline'}>
            {external?.enabled ? '已开启' : '已关闭'}
          </Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          {extLoading || !external ? (
            <Skeleton className="h-24 w-full rounded-xl" />
          ) : (
            <>
              <label className="flex items-center justify-between rounded-xl border border-border bg-muted/30 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">启用外部访问</p>
                  <p className="text-xs text-muted-foreground">允许外部系统通过令牌调用本知识库（接口随文档解析阶段开放）</p>
                </div>
                <input
                  type="checkbox"
                  checked={external.enabled}
                  onChange={(e) => toggleExternal(e.target.checked)}
                  className="h-5 w-9 cursor-pointer appearance-none rounded-full border border-emerald-300 bg-emerald-100 transition-colors checked:bg-primary after:absolute after:left-0.5 after:top-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow after:transition-transform checked:after:translate-x-4"
                />
              </label>

              <div className="rounded-xl border border-border bg-muted/30 p-4">
                <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <KeyRound className="h-3.5 w-3.5" />
                  访问令牌（仅显示前缀）
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 rounded-lg border border-border bg-card px-3 py-2 font-mono text-sm">
                    {external.token_prefix}
                  </code>
                  <Button variant="outline" size="sm" onClick={() => copyToken(external.token_prefix, '令牌前缀')}>
                    <Copy className="h-3.5 w-3.5" />
                    复制前缀
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setRegenerateOpen(true)}>
                    <RefreshCcw className="h-3.5 w-3.5" />
                    重新生成
                  </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  完整令牌仅在重新生成时展示一次，请妥善保存
                </p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {fullToken ? (
        <Card className="border-warning/40 bg-warning/5">
          <CardContent className="space-y-2 p-4">
            <p className="text-sm font-medium text-warning">新令牌已生成（仅此一次展示）</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded-lg border border-warning/30 bg-card px-3 py-2 font-mono text-sm">
                {fullToken}
              </code>
              <Button variant="secondary" size="sm" onClick={() => copyToken(fullToken, '完整令牌')}>
                <Copy className="h-3.5 w-3.5" />
                复制
              </Button>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setFullToken(null)}>我知道了</Button>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-primary" />
            LLM 服务
          </CardTitle>
          <CardDescription>结构化抽取使用的 LLM 服务（vLLM/Ollama 等 OpenAI 兼容接口）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {llmLoading || !llmConfig ? (
            <Skeleton className="h-24 w-full rounded-xl" />
          ) : (
            <>
              <label className="flex items-center justify-between rounded-xl border border-border bg-muted/30 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">启用 LLM 服务</p>
                  <p className="text-xs text-muted-foreground">关闭后抽取任务无法启动（B14 前置校验会拒绝）</p>
                </div>
                <input
                  type="checkbox"
                  disabled={!canManage}
                  checked={llm.enabled}
                  onChange={(e) => setLlm((prev) => ({ ...prev, enabled: e.target.checked }))}
                  className="h-5 w-9 cursor-pointer appearance-none rounded-full border border-emerald-300 bg-emerald-100 transition-colors checked:bg-primary after:absolute after:left-0.5 after:top-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow after:transition-transform checked:after:translate-x-4"
                />
              </label>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="llm-base">服务地址 api_base</Label>
                  <Input
                    id="llm-base"
                    disabled={!canManage}
                    value={llm.api_base}
                    placeholder="http://127.0.0.1:8001/v1"
                    onChange={(e) => setLlm((prev) => ({ ...prev, api_base: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="llm-model">模型名称</Label>
                  <Input
                    id="llm-model"
                    disabled={!canManage}
                    value={llm.model}
                    placeholder="如 Qwen2.5-72B-Instruct"
                    onChange={(e) => setLlm((prev) => ({ ...prev, model: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="llm-key">API Key（留空保持不变）</Label>
                  <Input
                    id="llm-key"
                    disabled={!canManage}
                    type="password"
                    value={llm.api_key}
                    placeholder={llmConfig.api_key_masked || '未配置'}
                    onChange={(e) => setLlm((prev) => ({ ...prev, api_key: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="llm-timeout">超时（秒）</Label>
                  <Input
                    id="llm-timeout"
                    disabled={!canManage}
                    type="number"
                    min={1}
                    max={3600}
                    value={llm.timeout}
                    onChange={(e) => setLlm((prev) => ({ ...prev, timeout: Number(e.target.value) || 300 }))}
                  />
                </div>
              </div>

              {canManage && (
                <div className="flex items-center gap-2">
                  <Button onClick={handleSaveLLM} disabled={llmSaving} className="gap-1.5">
                    {llmSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    保存 LLM 服务
                  </Button>
                  <Button variant="outline" onClick={handleTestLLM} disabled={llmTesting} className="gap-1.5">
                    {llmTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                    测试连接
                  </Button>
                </div>
              )}

              {llmTestResult && (
                <p className={`rounded-lg px-3 py-2 text-xs ${llmTestResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-destructive'}`}>
                  {llmTestResult.ok ? '连接成功' : `连接失败：${llmTestResult.error || '未知错误'}`}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={regenerateOpen}
        onOpenChange={setRegenerateOpen}
        title="重新生成外部访问令牌"
        description="旧令牌将立即失效，生成后的完整令牌仅展示一次。确认继续？"
        footer={
          <>
            <Button variant="outline" onClick={() => setRegenerateOpen(false)}>取消</Button>
            <Button onClick={() => void handleRegenerate()}>确认重新生成</Button>
          </>
        }
      />
    </div>
  )
}
