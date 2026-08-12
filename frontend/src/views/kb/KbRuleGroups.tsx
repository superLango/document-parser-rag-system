import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, ChevronUp, FolderTree, LayoutTemplate, ListChecks, Loader2, Plus, ShieldCheck, Trash2, Wand2 } from 'lucide-react'
import { ruleGroupApi, scriptApi, type KbScript, type RuleGroup, type RuleGroupCategory, type RuleGroupItem } from '@/api/modules/extractionConfig'
import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { SchemaTemplate } from '@/api/modules/extractionConfig'

interface Props {
  kbId: string
  canManage: boolean
  templates: SchemaTemplate[]
}

type GroupWithDetail = RuleGroup & { categories?: RuleGroupCategory[]; loaded?: boolean }

let dragItem: RuleGroupItem | null = null

function summarizeStages(cat: RuleGroupCategory): string {
  const rules = cat.rules || []
  const parts: string[] = []
  const post = rules.filter((r) => r.stage === 'post').length
  const val = rules.filter((r) => r.stage === 'validation').length
  if (post) parts.push(`后处理 ${post}`)
  if (val) parts.push(`校验 ${val}`)
  return parts.join(' · ')
}

export default function KbRuleGroups({ kbId, canManage, templates }: Props) {
  const { toast } = useToast()
  const [groups, setGroups] = useState<GroupWithDetail[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set())
  const [scriptsByFolder, setScriptsByFolder] = useState<Record<string, KbScript[]>>({ post: [], validation: [] })

  const [groupOpen, setGroupOpen] = useState(false)
  const [groupForm, setGroupForm] = useState({ name: '', schema_template_id: '', description: '' })
  const [groupSaving, setGroupSaving] = useState(false)

  const [addOpen, setAddOpen] = useState(false)
  const [addCtx, setAddCtx] = useState<{ groupId: string; categoryId: string; categoryName: string } | null>(null)
  const [addForm, setAddForm] = useState<{ stage: 'post' | 'validation'; script_id: string }>({ stage: 'post', script_id: '' })
  const [addSaving, setAddSaving] = useState(false)

  const [confirmState, setConfirmState] = useState<{ title: string; description: string; onConfirm: () => Promise<void> } | null>(null)
  const [confirming, setConfirming] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [gRes, sRes] = await Promise.all([ruleGroupApi.list(kbId), scriptApi.list(kbId)])
      const grouped: Record<string, KbScript[]> = { post: [], validation: [] }
      for (const s of sRes.items) {
        const f = s.folder || 'post'
        if (!grouped[f]) grouped[f] = []
        grouped[f].push(s)
      }
      setScriptsByFolder(grouped)
      setGroups(gRes.items.map((g) => ({ ...g })))
    } catch (err) {
      toast('error', '加载失败', err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [kbId, toast])

  useEffect(() => { void load() }, [load])

  const addRuleScripts = useMemo(() =>
    (scriptsByFolder[addForm.stage] || []).filter((s) => s.enabled !== false),
  [scriptsByFolder, addForm.stage])

  function toggleGroup(id: string) {
    setExpandedGroups((st) => {
      const n = new Set(st)
      if (n.has(id)) { n.delete(id); return n }
      n.add(id)
      const g = groups.find((x) => x.id === id)
      if (g && !g.loaded) void loadGroupDetail(g)
      return n
    })
  }

  async function loadGroupDetail(g: GroupWithDetail) {
    try {
      const d = await ruleGroupApi.get(kbId, g.id)
      setGroups((prev) => prev.map((x) => (x.id === g.id ? { ...x, categories: d.categories, loaded: true } : x)))
    } catch {
      toast('error', '加载失败', '规则组详情加载失败')
    }
  }

  function toggleCategory(groupId: string, catId: string) {
    const k = `${groupId}:${catId}`
    setExpandedCats((st) => {
      const n = new Set(st)
      if (n.has(k)) n.delete(k); else n.add(k)
      return n
    })
  }

  function openCreateGroup() {
    setGroupForm({ name: '', schema_template_id: templates[0]?.id || '', description: '' })
    setGroupOpen(true)
  }

  async function submitGroup() {
    if (!groupForm.schema_template_id) { toast('warning', '请选择 Schema 模板'); return }
    setGroupSaving(true)
    try {
      await ruleGroupApi.create(kbId, { name: groupForm.name.trim() || undefined, schema_template_id: groupForm.schema_template_id, description: groupForm.description.trim() || undefined })
      toast('success', '规则组已创建')
      setGroupOpen(false)
      await load()
    } catch (err) {
      toast('error', '创建失败', err instanceof ApiError ? err.message : '创建失败')
    } finally {
      setGroupSaving(false)
    }
  }

  function openAddRule(g: GroupWithDetail, cat: RuleGroupCategory) {
    setAddCtx({ groupId: g.id, categoryId: cat.id, categoryName: cat.name })
    setAddForm({ stage: 'post', script_id: '' })
    setAddOpen(true)
  }

  async function submitAddRule() {
    if (!addForm.script_id) { toast('warning', '请选择脚本'); return }
    if (!addCtx) return
    setAddSaving(true)
    try {
      const g = groups.find((x) => x.id === addCtx.groupId)
      const cat = g?.categories?.find((c) => c.id === addCtx.categoryId)
      if (!g || !cat) return
      const script = (scriptsByFolder[addForm.stage] || []).find((s) => s.id === addForm.script_id)
      const nextRules = [...(cat.rules || []), {
        id: `tmp-${Date.now()}`,
        category_id: cat.id,
        category_name: cat.name,
        script_id: addForm.script_id,
        script_name: script?.name || '',
        script_description: script?.description || '',
        stage: addForm.stage,
        sort_order: (cat.rules || []).length,
      }]
      updateCatRules(g, cat, nextRules)
      await persist(g.id, cat.id, cat.name, nextRules)
      toast('success', '规则已添加')
      setAddOpen(false)
    } catch (err) {
      toast('error', '添加失败', err instanceof ApiError ? err.message : '添加失败')
    } finally {
      setAddSaving(false)
    }
  }

  function updateCatRules(g: GroupWithDetail, cat: RuleGroupCategory, rules: RuleGroupItem[]) {
    setGroups((prev) => prev.map((x) => {
      if (x.id !== g.id) return x
      return { ...x, categories: (x.categories || []).map((c) => (c.id === cat.id ? { ...c, rules } : c)) }
    }))
  }

  async function persist(groupId: string, categoryId: string, categoryName: string, rules: RuleGroupItem[]) {
    try {
      await ruleGroupApi.saveItems(kbId, groupId, {
        category_id: categoryId,
        items: rules.map((r, i) => ({ script_id: r.script_id, stage: r.stage, category_name: categoryName, sort_order: i })),
      })
      // 刷新列表同时保留展开组的详情，避免展开态退化回骨架
      const [gRes, dRes] = await Promise.all([ruleGroupApi.list(kbId), ruleGroupApi.get(kbId, groupId)])
      setGroups(gRes.items.map((g) => (g.id === groupId ? { ...g, categories: dRes.categories, loaded: true } : { ...g })))
    } catch (err) {
      toast('error', '保存失败', err instanceof ApiError ? err.message : '保存失败')
    }
  }

  function removeItem(g: GroupWithDetail, cat: RuleGroupCategory, rule: RuleGroupItem) {
    setConfirmState({
      title: '移除规则',
      description: `确定移除此规则「${rule.script_name}」？`,
      onConfirm: async () => {
        const next = (cat.rules || []).filter((r) => r !== rule).map((r, i) => ({ ...r, sort_order: i }))
        updateCatRules(g, cat, next)
        await persist(g.id, cat.id, cat.name, next)
      },
    })
  }

  function moveRule(g: GroupWithDetail, cat: RuleGroupCategory, rule: RuleGroupItem, dir: -1 | 1) {
    const rules = [...(cat.rules || [])]
    const idx = rules.indexOf(rule)
    const to = idx + dir
    if (to < 0 || to >= rules.length) return
    rules.splice(idx, 1)
    rules.splice(to, 0, rule)
    rules.forEach((r, i) => { r.sort_order = i })
    updateCatRules(g, cat, rules)
    void persist(g.id, cat.id, cat.name, rules)
  }

  function onRuleDrop(g: GroupWithDetail, cat: RuleGroupCategory, target: RuleGroupItem) {
    if (dragItem && dragItem !== target) {
      const rules = [...(cat.rules || [])]
      const fromIdx = rules.indexOf(dragItem)
      const toIdx = rules.indexOf(target)
      rules.splice(fromIdx, 1)
      rules.splice(toIdx, 0, dragItem)
      rules.forEach((r, i) => { r.sort_order = i })
      updateCatRules(g, cat, rules)
      void persist(g.id, cat.id, cat.name, rules)
    }
    dragItem = null
  }

  function requestDeleteGroup(g: GroupWithDetail) {
    setConfirmState({
      title: '删除规则组',
      description: `确定删除规则组「${g.name}」？其下所有规则将一并删除。`,
      onConfirm: async () => {
        await ruleGroupApi.remove(kbId, g.id)
        toast('success', '规则组已删除')
        await load()
      },
    })
  }

  async function runConfirm() {
    if (!confirmState) return
    setConfirming(true)
    try {
      await confirmState.onConfirm()
    } catch (err) {
      toast('error', '操作失败', err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setConfirming(false)
      setConfirmState(null)
    }
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">后处理与校验规则</p>
            {canManage && (
              <Button variant="outline" size="sm" onClick={openCreateGroup} className="gap-1" data-testid="btn-new-rule-group">
                <Plus className="h-4 w-4" /> 新建规则组
              </Button>
            )}
          </div>
          {loading ? (
            <Skeleton className="h-24 w-full" />
          ) : groups.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <ListChecks className="h-8 w-8 text-muted-foreground/50" />
              <p className="text-sm font-medium">暂无规则组</p>
              <p className="text-xs text-muted-foreground">新建规则组并绑定 Schema 模板，然后按类别配置后处理与校验脚本规则</p>
            </div>
          ) : (
            groups.map((g) => (
              <div key={g.id} className="overflow-hidden rounded-xl border border-border bg-card shadow-sm transition-all duration-200 hover:shadow-md">
                <div className="h-1 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent" />
                <div className="flex items-center justify-between gap-3 p-3.5">
                  <div className="flex min-w-0 flex-1 cursor-pointer items-start gap-3" onClick={() => toggleGroup(g.id)} data-testid={`rule-group-${g.id}`}>
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <FolderTree className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        {expandedGroups.has(g.id) ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                        <p className="truncate font-semibold text-foreground">{g.name}</p>
                        <Badge variant="secondary" className="shrink-0 text-[10px]">{g.category_count} 类别</Badge>
                        <Badge variant="outline" className="shrink-0 text-[10px]">{g.item_count} 规则</Badge>
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1"><LayoutTemplate className="h-3 w-3" /> {g.schema_template_name}</span>
                        {g.description ? ` · ${g.description}` : ''}
                      </p>
                    </div>
                  </div>
                  {canManage && (
                    <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive" onClick={() => requestDeleteGroup(g)} data-testid={`btn-del-rule-group-${g.id}`}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>

                {expandedGroups.has(g.id) && (
                  <div className="space-y-2 border-t border-border/70 bg-muted/20 p-3">
                    {!g.loaded ? (
                      <Skeleton className="h-16 w-full" />
                    ) : (g.categories || []).length === 0 ? (
                      <div className="flex flex-col items-center gap-1.5 py-6 text-muted-foreground">
                        <FolderTree className="h-6 w-6" />
                        <p className="text-xs">该模板下暂无类别</p>
                      </div>
                    ) : (
                      (g.categories || []).map((cat) => (
                        <div key={cat.id} className="overflow-hidden rounded-lg border border-border transition-shadow hover:shadow-sm">
                          <div className="flex cursor-pointer items-center gap-3 p-3 transition-colors hover:bg-primary/5" onClick={() => toggleCategory(g.id, cat.id)} data-testid={`rule-cat-${cat.id}`}>
                            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground">
                              {expandedCats.has(`${g.id}:${cat.id}`) ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </div>
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                              <FolderTree className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="font-medium text-foreground">{cat.name}</p>
                                <Badge variant="secondary" className="text-[10px]">{(cat.rules || []).length} 规则</Badge>
                              </div>
                              {(cat.rules || []).length > 0 && (
                                <p className="mt-0.5 truncate text-xs text-muted-foreground">{summarizeStages(cat)}</p>
                              )}
                            </div>
                            {canManage && (
                              <Button variant="ghost" size="sm" title="添加规则" onClick={(e) => { e.stopPropagation(); openAddRule(g, cat) }}>
                                <Plus className="h-4 w-4" />
                              </Button>
                            )}
                          </div>

                          {expandedCats.has(`${g.id}:${cat.id}`) && (
                            <div className="space-y-2 border-t border-border bg-muted/20 p-3">
                              {(cat.rules || []).length === 0 ? (
                                <div className="py-4 text-center text-xs text-muted-foreground">暂无规则，点击右侧「＋」或下方「添加规则」</div>
                              ) : (
                                (cat.rules || []).map((rule, ri) => (
                                  <div key={rule.id} draggable onDragStart={() => { dragItem = rule }} onDragOver={(e) => e.preventDefault()} onDrop={() => onRuleDrop(g, cat, rule)}
                                    className="group flex items-center gap-3 rounded-md bg-card p-2.5 transition-colors hover:bg-primary/5">
                                    <span className="cursor-grab text-lg leading-none text-muted-foreground/40">⋮⋮</span>
                                    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${rule.stage === 'post' ? 'bg-primary/10 text-primary' : 'bg-warning/15 text-warning'}`} title={rule.stage === 'post' ? '后处理' : '校验'}>
                                      {rule.stage === 'post' ? <Wand2 className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                                    </div>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-2">
                                        <p className="truncate text-sm font-medium text-foreground">{rule.script_name || '未命名脚本'}</p>
                                        <Badge variant={rule.stage === 'post' ? 'default' : 'outline'} className="shrink-0 text-[10px]">{rule.stage === 'post' ? '后处理' : '校验'}</Badge>
                                      </div>
                                      {rule.script_description && <p className="mt-0.5 truncate text-xs text-muted-foreground">{rule.script_description}</p>}
                                    </div>
                                    {canManage && (
                                      <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground" title="上移" disabled={ri === 0} onClick={() => moveRule(g, cat, rule, -1)}><ChevronUp className="h-3.5 w-3.5" /></Button>
                                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground" title="下移" disabled={ri === (cat.rules || []).length - 1} onClick={() => moveRule(g, cat, rule, 1)}><ChevronDown className="h-3.5 w-3.5" /></Button>
                                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" title="移除" onClick={() => void removeItem(g, cat, rule)}><Trash2 className="h-3.5 w-3.5" /></Button>
                                      </div>
                                    )}
                                  </div>
                                ))
                              )}
                              {canManage && (
                                <Button variant="outline" size="sm" className="w-full border-dashed hover:bg-primary/5" onClick={() => openAddRule(g, cat)}>
                                  <Plus className="h-4 w-4" /> 添加规则
                                </Button>
                              )}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* 新建规则组 */}
      <Dialog open={groupOpen} onOpenChange={(o) => { if (!o) setGroupOpen(false) }} title="新建规则组" description="按 Schema 模板分组，为各类别统一配置后处理与校验脚本规则" className="max-w-xl">
        <div className="space-y-4">
          <label className="block text-xs font-medium text-muted-foreground">规则组名称（可不填，默认取 Schema 模板名）
            <Input value={groupForm.name} onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })} placeholder="如：材料检测规则组" className="mt-1 h-10" data-testid="rule-name-input" />
          </label>
          <label className="block text-xs font-medium text-muted-foreground">Schema 模板 *
            <Select value={groupForm.schema_template_id} onChange={(e) => setGroupForm({ ...groupForm, schema_template_id: e.target.value })} className="mt-1 h-10" data-testid="rule-template-select">
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          </label>
          <label className="block text-xs font-medium text-muted-foreground">描述
            <Input value={groupForm.description} onChange={(e) => setGroupForm({ ...groupForm, description: e.target.value })} placeholder="规则组用途说明" className="mt-1 h-10" />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="ghost" onClick={() => setGroupOpen(false)}>取消</Button>
          <Button onClick={submitGroup} disabled={groupSaving || !groupForm.schema_template_id} className="gap-1.5" data-testid="btn-rule-save">
            {groupSaving && <Loader2 className="h-4 w-4 animate-spin" />} 创建
          </Button>
        </div>
      </Dialog>

      {/* 添加规则 */}
      <Dialog open={addOpen} onOpenChange={(o) => { if (!o) setAddOpen(false) }} title="添加规则" description="先选择阶段，脚本列表仅展示该阶段目录下已启用的脚本" className="max-w-xl">
        <div className="space-y-4">
          <label className="block text-xs font-medium text-muted-foreground">阶段 *
            <Select value={addForm.stage} onChange={(e) => setAddForm({ stage: e.target.value as 'post' | 'validation', script_id: '' })} className="mt-1 h-10" data-testid="add-rule-stage">
              <option value="post">后处理</option>
              <option value="validation">校验</option>
            </Select>
          </label>
          <label className="block text-xs font-medium text-muted-foreground">选择脚本 *（{addForm.stage === 'post' ? '抽取后处理' : '校验'}目录）
            <Select value={addForm.script_id} onChange={(e) => setAddForm({ ...addForm, script_id: e.target.value })} className="mt-1 h-10" data-testid="add-rule-script">
              <option value="">选择脚本</option>
              {addRuleScripts.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
            {addRuleScripts.length === 0 && <p className="mt-1 text-xs text-warning">该阶段暂无启用脚本，请先在「脚本管理」中创建</p>}
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="ghost" onClick={() => setAddOpen(false)}>取消</Button>
          <Button onClick={submitAddRule} disabled={addSaving || !addForm.script_id} className="gap-1.5" data-testid="btn-add-rule">
            {addSaving && <Loader2 className="h-4 w-4 animate-spin" />} 添加
          </Button>
        </div>
      </Dialog>

      {/* 确认弹框（删除规则组/移除规则） */}
      <Dialog open={confirmState !== null} onOpenChange={(o) => { if (!o) setConfirmState(null) }} title={confirmState?.title ?? '确认'}>
        <p className="text-sm text-muted-foreground">{confirmState?.description}</p>
        <div className="mt-5 flex justify-end gap-2 border-t border-border/60 pt-4">
          <Button variant="outline" onClick={() => setConfirmState(null)}>取消</Button>
          <Button variant="destructive" onClick={runConfirm} disabled={confirming} className="gap-1.5" data-testid="btn-confirm-delete">
            {confirming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} 删除
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
