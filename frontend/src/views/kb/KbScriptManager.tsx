import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bug, ChevronDown, ChevronRight, Code2, Folder, Loader2, Play, Plus, Save, Trash2 } from 'lucide-react'
import { scriptApi, type KbScript, type ScriptIOFolder } from '@/api/modules/extractionConfig'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'

const FOLDERS = [
  { key: 'post', label: '抽取后处理' },
  { key: 'validation', label: '校验' },
]

const DEFAULT_CODE = `def run(args):
    # 抽取后处理 / 校验
    records = args.get("records", [])
    # category = args.get("category", "")
    # 如需剔除记录，额外返回 rejected
    # rows = await kb_tools.get_term_records("术语集名称", "字段名")
    return {"records": records}
`

const DEFAULT_ARGS = JSON.stringify({ records: [], category: '', doc_id: '' }, null, 2)

interface Props {
  kbId: string
  canManage: boolean
}

export default function KbScriptManager({ kbId, canManage }: Props) {
  const { toast } = useToast()
  const [ioRegistry, setIoRegistry] = useState<Record<string, ScriptIOFolder>>({})
  const [scriptsByFolder, setScriptsByFolder] = useState<Record<string, KbScript[]>>({ post: [], validation: [] })
  const [currentFolder, setCurrentFolder] = useState('post')
  const [currentScriptId, setCurrentScriptId] = useState<string | null>(null)
  const [editor, setEditor] = useState({ id: '' as string | null, name: '', description: '', enabled: true, code: DEFAULT_CODE })
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KbScript | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [debugArgsText, setDebugArgsText] = useState(DEFAULT_ARGS)
  const [debugRunning, setDebugRunning] = useState(false)
  const [debugResult, setDebugResult] = useState<{ ok: boolean; result?: unknown; error?: string } | null>(null)
  const [openPanels, setOpenPanels] = useState<Record<string, boolean>>({})

  const load = useCallback(async () => {
    try {
      const [ioRes, listRes] = await Promise.all([scriptApi.io(kbId), scriptApi.list(kbId)])
      setIoRegistry(ioRes.folders)
      const grouped: Record<string, KbScript[]> = { post: [], validation: [] }
      for (const item of listRes.items) {
        const f = item.folder || 'post'
        if (!grouped[f]) grouped[f] = []
        grouped[f].push(item)
      }
      setScriptsByFolder(grouped)
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    }
  }, [kbId, toast])

  useEffect(() => { void load() }, [load])

  const scripts = useMemo(() => scriptsByFolder[currentFolder] ?? [], [scriptsByFolder, currentFolder])
  const io = useMemo(() => ioRegistry[currentFolder], [ioRegistry, currentFolder])

  function togglePanel(key: string) {
    setOpenPanels((m) => ({ ...m, [key]: !m[key] }))
  }

  function selectFolder(folder: string) {
    setCurrentFolder(folder)
    setCurrentScriptId(null)
    setEditor({ id: null, name: '', description: '', enabled: true, code: DEFAULT_CODE })
    setDirty(false)
    setDebugResult(null)
  }

  function selectScript(s: KbScript) {
    setCurrentScriptId(s.id)
    setEditor({ id: s.id, name: s.name, description: s.description, enabled: s.enabled, code: s.code })
    setDirty(false)
    setDebugResult(null)
  }

  function newScript() {
    setCurrentScriptId(null)
    setEditor({ id: null, name: '', description: '', enabled: true, code: DEFAULT_CODE })
    setDirty(false)
  }

  async function saveScript() {
    if (!editor.name.trim()) { toast('warning', '请填写脚本名称'); return }
    setSaving(true)
    try {
      if (editor.id) {
        await scriptApi.update(kbId, editor.id, {
          name: editor.name, description: editor.description, enabled: editor.enabled, code: editor.code,
        })
      } else {
        const r = await scriptApi.create(kbId, { folder: currentFolder, name: editor.name, description: editor.description, enabled: editor.enabled, code: editor.code })
        setEditor((e) => ({ ...e, id: r.id }))
        setCurrentScriptId(r.id)
      }
      toast('success', '脚本已保存')
      setDirty(false)
      await load()
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await scriptApi.remove(kbId, deleteTarget.id)
      toast('success', '脚本已删除')
      if (currentScriptId === deleteTarget.id) { setCurrentScriptId(null); setEditor({ id: null, name: '', description: '', enabled: true, code: DEFAULT_CODE }) }
      setDeleteTarget(null)
      await load()
    } catch (err) {
      toast('error', '删除失败', err instanceof ApiError ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  async function runDebug() {
    let args: Record<string, unknown> = {}
    try {
      args = debugArgsText.trim() ? JSON.parse(debugArgsText) : {}
    } catch {
      toast('error', '参数 JSON 格式错误')
      return
    }
    setDebugRunning(true)
    try {
      const res = await scriptApi.run(kbId, currentScriptId ? { script_id: currentScriptId, args } : { code: editor.code, args })
      setDebugResult(res)
    } catch (err) {
      setDebugResult({ ok: false, error: err instanceof ApiError ? err.message : '运行失败' })
    } finally {
      setDebugRunning(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[220px_1fr_280px]">
        {/* 左：目录 + 脚本列表 */}
        <Card className="h-fit">
          <CardContent className="space-y-2 p-3">
            {FOLDERS.map((f) => (
              <div key={f.key} className="rounded-lg border border-border/70">
                <button
                  type="button"
                  onClick={() => selectFolder(f.key)}
                  className={`flex w-full items-center gap-2 px-2 py-2 text-left text-sm font-medium transition-all ${currentFolder === f.key ? 'text-primary-strong' : 'text-muted-foreground hover:text-foreground'}`}
                  data-testid={`script-folder-${f.key}`}
                >
                  <Folder className="h-4 w-4" /> {f.label}
                  <Badge variant="outline" className="ml-auto text-[10px]">{(scriptsByFolder[f.key] ?? []).length}</Badge>
                </button>
                {currentFolder === f.key && (
                  <div className="space-y-1 border-t border-border/60 p-1">
                    {canManage && (
                      <Button variant="ghost" size="sm" className="w-full justify-start gap-1 text-xs" onClick={newScript} data-testid="btn-new-script">
                        <Plus className="h-3.5 w-3.5" /> 新建脚本
                      </Button>
                    )}
                    {scripts.length === 0 ? (
                      <p className="px-2 py-2 text-xs text-muted-foreground">暂无脚本</p>
                    ) : (
                      scripts.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => selectScript(s)}
                          data-testid={`script-item-${s.name}`}
                          className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-all ${currentScriptId === s.id ? 'bg-secondary font-medium' : 'hover:bg-muted'}`}
                        >
                          <Code2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate">{s.name}</span>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>

        {/* 中：脚本编辑 */}
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Input value={editor.name} onChange={(e) => { setEditor({ ...editor, name: e.target.value }); setDirty(true) }} placeholder="脚本名称" className="h-9 flex-1 font-mono text-xs" data-testid="script-name-input" />
              <label className="flex items-center gap-1.5 text-xs"><Switch checked={editor.enabled} onCheckedChange={(v) => { setEditor({ ...editor, enabled: v }); setDirty(true) }} /> 启用</label>
              {canManage && (
                <>
                  <Button size="sm" onClick={saveScript} disabled={saving} className="gap-1" data-testid="btn-save-script">
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} 保存{dirty ? ' *' : ''}
                  </Button>
                  {currentScriptId && (
                    <Button variant="outline" size="sm" onClick={() => setDeleteTarget(scripts.find((s) => s.id === currentScriptId) ?? null)} className="gap-1 text-destructive hover:text-destructive" data-testid="btn-delete-script">
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </>
              )}
            </div>
            <label className="block text-xs font-medium text-muted-foreground">描述
              <Input value={editor.description} onChange={(e) => { setEditor({ ...editor, description: e.target.value }); setDirty(true) }} className="mt-1 h-9" />
            </label>
            <label className="block text-xs font-medium text-muted-foreground">脚本代码（def run(args): ... 返回 dict）
              <textarea value={editor.code} onChange={(e) => { setEditor({ ...editor, code: e.target.value }); setDirty(true) }} rows={18} spellCheck={false}
                className="mt-1 w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs leading-5 shadow-soft focus-visible:border-primary/50" data-testid="script-code-input" />
            </label>
          </CardContent>
        </Card>

        {/* 右：IO 注册 */}
        <Card className="h-fit">
          <CardContent className="space-y-3 p-3">
            {[
              { key: 'input', label: '输入参数' },
              { key: 'output', label: '返回参数' },
              { key: 'tools', label: '可用工具' },
            ].map((p) => (
              <div key={p.key} className="rounded-lg border border-border/70">
                <button type="button" onClick={() => togglePanel(p.key)} className="flex w-full items-center gap-2 px-2 py-2 text-left text-xs font-medium text-muted-foreground" data-testid={`io-${p.key}`}>
                  {openPanels[p.key] ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                  {p.label}
                </button>
                {openPanels[p.key] && (
                  <div className="space-y-1 border-t border-border/60 p-2">
                    {p.key === 'tools' ? (io?.tools ?? []).map((t) => <p key={t} className="break-all font-mono text-[11px] text-muted-foreground">{t}</p>) : (io?.[p.key as 'input' | 'output'] ?? []).map((item) => (
                      <div key={item.name} className="flex items-start justify-between gap-2">
                        <span className="font-mono text-[11px]">{item.name}</span>
                        <Badge variant="outline" className="text-[10px]">{item.type}</Badge>
                      </div>
                    ))}
                    {p.key !== 'tools' && (io?.[p.key as 'input' | 'output'] ?? []).length === 0 && <p className="text-[11px] text-muted-foreground">无</p>}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* 底部调试 */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex items-center gap-2">
            <Bug className="h-4 w-4 text-muted-foreground" />
            <p className="text-sm font-medium">调试运行</p>
            <Button size="sm" onClick={runDebug} disabled={debugRunning} className="ml-auto gap-1" data-testid="btn-run-script">
              {debugRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} 运行
            </Button>
          </div>
          <label className="block text-xs font-medium text-muted-foreground">请求参数（args JSON）
            <textarea value={debugArgsText} onChange={(e) => setDebugArgsText(e.target.value)} rows={5} spellCheck={false} className="mt-1 w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-soft focus-visible:border-primary/50" data-testid="debug-args-input" />
          </label>
          {debugResult && (
            <div className="rounded-lg bg-muted/40 p-3">
              <p className="mb-1 text-xs font-medium">{debugResult.ok ? '运行成功' : '运行失败'}</p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs" data-testid="debug-result">{debugResult.ok ? JSON.stringify(debugResult.result, null, 2) : debugResult.error}</pre>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 删除确认 */}
      <Dialog open={deleteTarget !== null} onOpenChange={(o) => { if (!o) setDeleteTarget(null) }} title="删除脚本" description={`确定删除脚本「${deleteTarget?.name}」？`}>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
          <Button variant="destructive" onClick={confirmDelete} disabled={deleting} className="gap-1.5" data-testid="btn-script-delete-confirm">
            {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} 删除
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
