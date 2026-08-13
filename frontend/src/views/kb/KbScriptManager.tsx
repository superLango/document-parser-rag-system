import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, BookOpen, Bug, ChevronDown, ChevronRight, Code2, FileCode2, Folder, Loader2, Play, Plus, Save, Trash2, Wrench } from 'lucide-react'
import { scriptApi, type KbScript, type ScriptIOFolder, type ScriptIOFolderTool } from '@/api/modules/extractionConfig'
import { glossaryApi } from '@/api/modules/glossary'
import type { TermBase } from '@/api/types'
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

function defaultCodeFor(): string {
  return `def run(args):
    # 抽取后处理 / 校验
    records = args.get("records", [])

    # TODO: 在此编写你的处理逻辑
    # category = args.get("category", "")
    # 如需剔除记录，额外返回 rejected；只修改不剔除时可不返回
    # 可用工具（await kb_tools.xxx）：
    #   embed / semantic_search / match_record / get_term_records
    #   rows = await kb_tools.get_term_records("术语集名称", "字段名")
    #   hit = await kb_tools.match_record("查询词", rows, ["字段名"])

    return {"records": records}
`
}

function defaultArgsFor(): string {
  return JSON.stringify({ records: [], category: '', doc_id: '' }, null, 2)
}

interface Props {
  kbId: string
  canManage: boolean
}

export default function KbScriptManager({ kbId, canManage }: Props) {
  const { toast } = useToast()
  const [ioRegistry, setIoRegistry] = useState<Record<string, ScriptIOFolder>>({})
  const [scriptsByFolder, setScriptsByFolder] = useState<Record<string, KbScript[]>>({ post: [], validation: [] })
  const [termBases, setTermBases] = useState<{ id: string; name: string }[]>([])
  const [currentFolder, setCurrentFolder] = useState('post')
  const [currentScriptId, setCurrentScriptId] = useState<string | null>(null)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(['post']))
  const [openPanels, setOpenPanels] = useState<Set<string>>(new Set())
  const [openToolUsage, setOpenToolUsage] = useState<Set<string>>(new Set())
  const [openTermUsage, setOpenTermUsage] = useState<Set<string>>(new Set())
  const [editor, setEditor] = useState({ id: '' as string | null, name: '', description: '', enabled: true, code: defaultCodeFor() })
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KbScript | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [debugArgsText, setDebugArgsText] = useState(defaultArgsFor())
  const [debugRunning, setDebugRunning] = useState(false)
  const [debugResult, setDebugResult] = useState<{ ok: boolean; result?: unknown; error?: string } | null>(null)
  const codeScrollRef = useRef<HTMLDivElement | null>(null)
  const lineRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    try {
      const [ioRes, listRes, tbRes] = await Promise.all([
        scriptApi.io(kbId),
        scriptApi.list(kbId),
        glossaryApi.list(kbId, { page_size: 50 }),
      ])
      setIoRegistry(ioRes.folders)
      setTermBases((tbRes.items ?? []).map((t: TermBase) => ({ id: t.id, name: t.name })))
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

  const io = useMemo(() => ioRegistry[currentFolder], [ioRegistry, currentFolder])
  const inputParams = io?.input ?? []
  const outputParams = io?.output ?? []
  const toolCatalog = io?.tools ?? []
  const lineCount = useMemo(() => editor.code.split('\n').length, [editor.code])

  function togglePanel(key: string) {
    setOpenPanels((st) => {
      const n = new Set(st)
      if (n.has(key)) n.delete(key); else n.add(key)
      return n
    })
  }

  function toggleToolUsage(name: string) {
    setOpenToolUsage((st) => {
      const n = new Set(st)
      if (n.has(name)) n.delete(name); else n.add(name)
      return n
    })
  }

  function toggleTermUsage(id: string) {
    setOpenTermUsage((st) => {
      const n = new Set(st)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }

  function toggleFolder(folder: string) {
    setExpandedFolders((st) => {
      const n = new Set(st)
      if (n.has(folder)) n.delete(folder); else n.add(folder)
      return n
    })
  }

  function selectScript(s: KbScript) {
    setCurrentFolder(s.folder || 'post')
    setCurrentScriptId(s.id)
    setEditor({ id: s.id, name: s.name || '', description: s.description || '', enabled: s.enabled !== false, code: s.code || '' })
    setDebugArgsText(defaultArgsFor())
    setDebugResult(null)
    setDirty(false)
  }

  function newScript() {
    setCurrentScriptId(null)
    setEditor({ id: null, name: '', description: '', enabled: true, code: defaultCodeFor() })
    setDebugArgsText(defaultArgsFor())
    setDebugResult(null)
    setDirty(true)
  }

  function onCodeChange(value: string) {
    setEditor((e) => ({ ...e, code: value }))
    setDirty(true)
  }

  function onFieldChange(patch: Partial<{ name: string; description: string; enabled: boolean }>) {
    setEditor((e) => ({ ...e, ...patch }))
    setDirty(true)
  }

  async function saveScript() {
    if (!editor.name.trim()) { toast('warning', '请填写脚本名称'); return }
    setSaving(true)
    try {
      const payload = { folder: currentFolder, name: editor.name.trim(), description: editor.description, enabled: editor.enabled, code: editor.code }
      if (editor.id) {
        await scriptApi.update(kbId, editor.id, payload)
      } else {
        const r = await scriptApi.create(kbId, payload)
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
      if (currentScriptId === deleteTarget.id) {
        setCurrentScriptId(null)
        setEditor({ id: null, name: '', description: '', enabled: true, code: defaultCodeFor() })
        setDirty(false)
      }
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
      toast('warning', '调试请求参数不是合法的 JSON')
      return
    }
    setDebugRunning(true)
    setDebugResult(null)
    try {
      const res = await scriptApi.run(kbId, currentScriptId ? { script_id: currentScriptId, args } : { code: editor.code, args })
      setDebugResult(res)
    } catch (err) {
      setDebugResult({ ok: false, error: err instanceof ApiError ? err.message : '运行失败' })
    } finally {
      setDebugRunning(false)
    }
  }

  function syncScroll() {
    const el = codeScrollRef.current
    if (el && lineRef.current) lineRef.current.scrollTop = el.scrollTop
  }

  return (
    <div className="flex min-h-[520px] flex-col gap-3">
      {/* 顶部说明 */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">编写可复用的 Python 处理脚本，按调用时机组织目录，支持在线调试。</p>
          <p className="mt-0.5 text-xs text-muted-foreground/70">
            脚本需定义 <code className="rounded bg-muted px-1 font-mono text-[11px]">def run(args): ...</code>，返回 dict。
          </p>
        </div>
        {canManage && (
          <Button size="sm" onClick={saveScript} disabled={saving} className="gap-1.5" data-testid="btn-save-script">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存脚本
          </Button>
        )}
      </div>

      <div className="flex flex-1 gap-3">
        {/* ===== 左：脚本目录 ===== */}
        <Card className="h-fit w-60 shrink-0">
          <CardContent className="p-0">
            <div className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">脚本目录</div>
            <div className="max-h-[420px] overflow-y-auto p-2">
              {FOLDERS.map((f) => (
                <div key={f.key} className="mb-1">
                  <button
                    type="button"
                    onClick={() => { toggleFolder(f.key); setCurrentFolder(f.key) }}
                    className={`flex w-full cursor-pointer items-center gap-1.5 rounded px-2 py-1.5 text-left hover:bg-muted/60 ${currentFolder === f.key ? 'bg-muted/80' : ''}`}
                    data-testid={`script-folder-${f.key}`}
                  >
                    {expandedFolders.has(f.key) ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                    <Folder className="h-4 w-4" />
                    <span className="flex-1 text-sm">{f.label}</span>
                    <Badge variant="secondary" className="text-[10px]">{(scriptsByFolder[f.key] ?? []).length}</Badge>
                  </button>
                  {expandedFolders.has(f.key) && (
                    <div className="ml-4 space-y-0.5">
                      {(scriptsByFolder[f.key] ?? []).map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => selectScript(s)}
                          data-testid={`script-item-${s.name}`}
                          className={`flex w-full cursor-pointer items-center gap-1.5 rounded px-2 py-1 text-left text-xs hover:bg-muted/60 ${currentScriptId === s.id ? 'bg-primary/10 text-primary' : 'text-foreground/80'}`}
                        >
                          <FileCode2 className="h-3.5 w-3.5 shrink-0" />
                          <span className="flex-1 truncate">{s.name}</span>
                          {s.enabled === false && <span className="text-[10px] text-muted-foreground">停</span>}
                        </button>
                      ))}
                      {canManage && (
                        <div className="pt-0.5">
                          <Button variant="ghost" size="sm" className="h-6 w-full justify-start text-primary" onClick={() => { setCurrentFolder(f.key); newScript() }} data-testid="btn-new-script">
                            <Plus className="h-3.5 w-3.5" /> 新建脚本
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* ===== 中：脚本编辑区 ===== */}
        <Card className="flex min-w-0 flex-1 flex-col">
          <CardContent className="flex flex-1 flex-col p-0">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <Code2 className="h-4 w-4 text-muted-foreground" />
              <Input value={editor.name} onChange={(e) => onFieldChange({ name: e.target.value })} placeholder="脚本名称" className="h-7 max-w-52 font-medium" disabled={!canManage} data-testid="script-name-input" />
              {canManage && <Switch checked={editor.enabled} onCheckedChange={(v) => onFieldChange({ enabled: v })} />}
              <span className="text-xs text-muted-foreground">{editor.enabled ? '启用' : '关闭'}</span>
              <div className="ml-auto flex items-center gap-2">
                {dirty && <span className="text-[10px] text-amber-500">未保存</span>}
                {canManage && editor.id && (
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDeleteTarget(scriptsByFolder[currentFolder]?.find((s) => s.id === editor.id) ?? null)} data-testid="btn-delete-script">
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 px-3 py-2 sm:grid-cols-4">
              <div>
                <p className="text-[10px] text-muted-foreground">目录</p>
                <div className="mt-0.5 text-xs">{FOLDERS.find((f) => f.key === currentFolder)?.label}</div>
              </div>
              <div className="col-span-3">
                <p className="text-[10px] text-muted-foreground">说明</p>
                {canManage ? (
                  <Input value={editor.description} onChange={(e) => onFieldChange({ description: e.target.value })} placeholder="脚本用途说明" className="mt-0.5 h-7" />
                ) : (
                  <div className="mt-0.5 truncate text-xs">{editor.description || '—'}</div>
                )}
              </div>
            </div>
            {/* 代码编辑器（带行号） */}
            <div className="relative min-h-[280px] flex-1 overflow-hidden border-t border-border">
              <div className="flex h-full">
                <div ref={lineRef} className="select-none overflow-hidden border-r border-border bg-muted/40 px-2 py-3 text-right font-mono text-[12px] leading-5 text-muted-foreground/70">
                  {Array.from({ length: lineCount }, (_, i) => (
                    <div key={i + 1} className="w-6">{i + 1}</div>
                  ))}
                </div>
                <div ref={codeScrollRef} onScroll={syncScroll} className="h-full flex-1 overflow-auto">
                  <textarea
                    value={editor.code}
                    onChange={(e) => onCodeChange(e.target.value)}
                    spellCheck={false}
                    readOnly={!canManage}
                    className="h-full w-full resize-none bg-transparent p-3 font-mono text-[13px] leading-5 text-foreground outline-none disabled:cursor-not-allowed"
                    data-testid="script-code-input"
                  />
                </div>
              </div>
              <div className="pointer-events-none absolute bottom-2 right-3 text-[10px] text-muted-foreground/60">Python · {lineCount} 行</div>
            </div>
          </CardContent>
        </Card>

        {/* ===== 右：可传入 / 返回参数 / 工具 / 术语集 ===== */}
        <div className="w-72 shrink-0 space-y-2 overflow-y-auto">
          <Card>
            <CardContent className="p-0">
              <button type="button" onClick={() => togglePanel('input')} className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2 text-left" data-testid="io-input">
                {openPanels.has('input') ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                <ArrowDownToLine className="h-3.5 w-3.5 text-emerald-500" />
                <span className="text-xs font-medium">可传入参数</span>
                <span className="ml-auto text-[10px] text-muted-foreground">{inputParams.length}</span>
              </button>
              {openPanels.has('input') && (
                <div className="space-y-2 border-t border-border p-3">
                  {inputParams.map((p) => (
                    <div key={p.name} className="rounded bg-muted/40 p-2">
                      <div className="flex items-center gap-1.5">
                        <code className="font-mono text-[11px] text-emerald-600">{p.name}</code>
                        <span className="text-[10px] text-muted-foreground">{p.type}</span>
                      </div>
                      <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">{p.description}</p>
                    </div>
                  ))}
                  {inputParams.length === 0 && <p className="text-[10px] text-muted-foreground">当前目录无需传入参数</p>}
                  {canManage && (
                    <button type="button" className="text-[10px] text-primary hover:underline" onClick={() => setDebugArgsText(defaultArgsFor())}>重置调试默认值</button>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <button type="button" onClick={() => togglePanel('output')} className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2 text-left" data-testid="io-output">
                {openPanels.has('output') ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                <ArrowUpFromLine className="h-3.5 w-3.5 text-blue-500" />
                <span className="text-xs font-medium">返回参数</span>
                <span className="ml-auto text-[10px] text-muted-foreground">{outputParams.length}</span>
              </button>
              {openPanels.has('output') && (
                <div className="space-y-2 border-t border-border p-3">
                  {outputParams.map((p) => (
                    <div key={p.name} className="rounded bg-muted/40 p-2">
                      <div className="flex items-center gap-1.5">
                        <code className="font-mono text-[11px] text-blue-600">{p.name}</code>
                        <span className="text-[10px] text-muted-foreground">{p.type}</span>
                      </div>
                      <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">{p.description}</p>
                    </div>
                  ))}
                  {outputParams.length === 0 && <p className="text-[10px] text-muted-foreground">当前目录无需返回参数</p>}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <button type="button" onClick={() => togglePanel('tools')} className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2 text-left" data-testid="io-tools">
                {openPanels.has('tools') ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                <Wrench className="h-3.5 w-3.5 text-violet-500" />
                <span className="text-xs font-medium">kb_tool 可用工具</span>
                <span className="ml-auto text-[10px] text-muted-foreground">{toolCatalog.length}</span>
              </button>
              {openPanels.has('tools') && (
                <div className="space-y-2 border-t border-border p-3">
                  <p className="text-[10px] leading-tight text-muted-foreground">脚本内通过 <code className="rounded bg-muted px-1 font-mono text-[10px]">await kb_tools.xxx(...)</code> 调用内置能力</p>
                  {toolCatalog.map((t: ScriptIOFolderTool) => (
                    <div key={t.name} className="rounded border border-border/60 p-2">
                      <button type="button" className="flex w-full items-center gap-1.5 text-left" onClick={() => toggleToolUsage(t.name)}>
                        {openToolUsage.has(t.name) ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                        <code className="font-mono text-[11px] font-semibold text-violet-600">{t.name}</code>
                      </button>
                      {openToolUsage.has(t.name) && (
                        <div className="mt-1.5 space-y-1.5 border-t border-border/40 pt-1.5">
                          <p className="text-[10px] leading-tight text-muted-foreground">{t.desc}</p>
                          {t.params?.length ? (
                            <div>
                              <p className="text-[10px] font-medium text-muted-foreground">入参：</p>
                              {t.params.map((pr) => (
                                <div key={pr.name} className="mt-0.5 pl-1">
                                  <code className="font-mono text-[10px] text-foreground">{pr.name}</code>
                                  <span className="text-[10px] text-muted-foreground"> : {pr.type}</span>
                                  <p className="text-[10px] leading-tight text-muted-foreground">{pr.desc}</p>
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {t.returns && <p className="text-[10px] leading-tight text-muted-foreground"><span className="font-medium text-foreground">出参：</span>{t.returns}</p>}
                          {t.usage && (
                            <div className="rounded bg-muted/50">
                              <p className="px-1.5 py-1 text-[10px] font-medium text-muted-foreground">用法：</p>
                              <pre className="whitespace-pre-wrap border-t border-border/40 px-1.5 py-1.5 font-mono text-[10px] leading-snug text-foreground">{t.usage}</pre>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                  {toolCatalog.length === 0 && <p className="text-[10px] text-muted-foreground">当前目录无可调用工具</p>}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <button type="button" onClick={() => togglePanel('termbases')} className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2 text-left" data-testid="io-termbases">
                {openPanels.has('termbases') ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                <BookOpen className="h-3.5 w-3.5 text-amber-500" />
                <span className="text-xs font-medium">可用术语集</span>
                <span className="ml-auto text-[10px] text-muted-foreground">{termBases.length}</span>
              </button>
              {openPanels.has('termbases') && (
                <div className="space-y-2 border-t border-border p-3">
                  <p className="text-[10px] leading-tight text-muted-foreground">术语集通过 <code className="rounded bg-muted px-1 font-mono text-[10px]">kb_tools.get_term_records</code> 读取，返回键为修改后字段名的记录列表</p>
                  {termBases.map((tb) => (
                    <div key={tb.id} className="rounded bg-muted/40 p-2">
                      <button type="button" className="flex w-full items-center gap-1.5 text-left" onClick={() => toggleTermUsage(tb.id)}>
                        {openTermUsage.has(tb.id) ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
                        <code className="font-mono text-[11px] text-amber-600">{tb.name}</code>
                      </button>
                      {openTermUsage.has(tb.id) && (
                        <pre className="mt-1 whitespace-pre-wrap font-mono text-[10px] leading-snug text-muted-foreground">{`rows = await kb_tools.get_term_records("${tb.name}", "字段名")\n# rows = [{"字段名": "值", ...}, ...]`}</pre>
                      )}
                    </div>
                  ))}
                  {termBases.length === 0 && <p className="text-[10px] text-muted-foreground">当前知识库暂无术语集，请先在「专业术语集」中创建</p>}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ===== 底部：调试请求块 ===== */}
      <Card>
        <CardContent className="p-0">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Bug className="h-4 w-4 text-amber-500" />
            <span className="text-xs font-medium">接口参数调用与调试</span>
            <span className="text-[10px] text-muted-foreground">模拟 {FOLDERS.find((f) => f.key === currentFolder)?.label} 的运行时入参</span>
            <div className="ml-auto">
              <Button size="sm" onClick={runDebug} disabled={debugRunning} className="gap-1" data-testid="btn-run-script">
                {debugRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} 运行调试
              </Button>
            </div>
          </div>
          <div className="grid gap-3 p-3 lg:grid-cols-2">
            <div>
              <p className="text-[10px] text-muted-foreground">请求参数 (args JSON)</p>
              <textarea value={debugArgsText} onChange={(e) => setDebugArgsText(e.target.value)} spellCheck={false} readOnly={!canManage && !currentScriptId} className="mt-1 min-h-[140px] w-full rounded border border-input bg-muted/30 p-3 font-mono text-[12px] disabled:cursor-not-allowed" data-testid="debug-args-input" />
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground">返回结果</p>
              <div className="mt-1 min-h-[140px] overflow-auto rounded border border-border bg-muted/30 p-3 font-mono text-[12px]">
                {debugResult ? (
                  <pre className={`whitespace-pre-wrap ${debugResult.ok ? 'text-foreground' : 'text-red-500'}`} data-testid="debug-result">
                    {JSON.stringify(debugResult.ok ? debugResult.result : { ok: false, error: debugResult.error }, null, 2)}
                  </pre>
                ) : (
                  <span className="text-muted-foreground/60">运行后在此展示结果</span>
                )}
              </div>
            </div>
          </div>
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
