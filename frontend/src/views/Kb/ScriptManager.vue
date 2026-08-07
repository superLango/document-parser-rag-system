<script setup lang="ts">
/**
 * 自定义处理脚本管理（类似 magic-api 脚本即函数）
 *
 * 布局（左中右 + 底部调试）：
 * - 左：脚本目录（抽取后处理 / 校验），每目录下脚本列表 + 新建
 * - 中：脚本编辑区（代码编辑器 + 脚本属性）
 * - 右：可传入参数 + 返回参数（随时机不同而不同）
 * - 底部：接口参数调用与调试请求发送块（运行脚本 + 展示结果）
 *
 * 脚本契约：
 *   def run(args): ...  返回 dict
 *   - post / validation：返回 {"records": [...], "rejected": [...]}
 *   - 可用 kb_tools 调用内置能力（后处理 / 校验 / 术语集访问）
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Folder,
  FileCode2,
  Play,
  Save,
  Trash2,
  Plus,
  Loader2,
  Code2,
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronRight,
  ChevronDown,
  Bug,
  Wrench,
  BookOpen,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { confirm } from '@/composables/useConfirm'

const route = useRoute()
const kbId = computed(() => route.params.kb_id as string)
const { isEditor } = useKbPermission()

// ============================================================
// 目录定义
// ============================================================
const FOLDERS: { key: string; label: string; icon: any }[] = [
  { key: 'post', label: '抽取后处理', icon: Folder },
  { key: 'validation', label: '校验', icon: Folder },
]

const ioRegistry = ref<Record<string, any>>({})
const scriptsByFolder = ref<Record<string, any[]>>({ post: [], validation: [] })
const expandedFolders = ref<Set<string>>(new Set(['post']))
const loading = ref(false)
// 右侧面板折叠状态（input/output/tools/termbases 四类，默认全收起）
const openPanels = ref<Set<string>>(new Set())
const termBases = ref<{ id: string; name: string }[]>([])

function togglePanel(key: string) {
  if (openPanels.value.has(key)) openPanels.value.delete(key)
  else openPanels.value.add(key)
}
// 二级折叠：工具用法 / 术语集示例（点击展开）
const openToolUsage = ref<Set<string>>(new Set())
const openTermUsage = ref<Set<string>>(new Set())
function toggleToolUsage(name: string) {
  if (openToolUsage.value.has(name)) openToolUsage.value.delete(name)
  else openToolUsage.value.add(name)
}
function toggleTermUsage(id: string) {
  if (openTermUsage.value.has(id)) openTermUsage.value.delete(id)
  else openTermUsage.value.add(id)
}

// 当前选中的目录 + 脚本
const currentFolder = ref('post')
const currentScriptId = ref<string | null>(null)

// 编辑器表单
const editor = ref({
  id: '' as string | null,
  name: '',
  description: '',
  enabled: true,
  code: '',
})
const dirty = ref(false)
const saving = ref(false)

// 调试
const debugArgsText = ref('')
const debugRunning = ref(false)
const debugResult = ref<{ ok: boolean; result?: any; error?: string } | null>(null)

const folderMeta = computed(() => ioRegistry.value[currentFolder.value] || {})
const inputParams = computed<any[]>(() => folderMeta.value.input || [])
const outputParams = computed<any[]>(() => folderMeta.value.output || [])
const toolCatalog = computed<any[]>(() => folderMeta.value.tools || [])

const lineCount = computed(() => editor.value.code.split('\n').length)

// 各目录默认调试入参
function defaultArgsFor(): string {
  return JSON.stringify({ records: [], category: '', doc_id: '' }, null, 2)
}

// 各目录默认脚本模板
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

// ============================================================
// 数据加载
// ============================================================
async function loadAll() {
  loading.value = true
  try {
    const [io, list, tb] = await Promise.all([
      kbApi.getScriptIO(kbId.value),
      kbApi.listScripts(kbId.value),
      kbApi.listTermBases(kbId.value),
    ])
    ioRegistry.value = (io.folders || {}) as any
    termBases.value = ((tb.items as any[]) || []).map((t) => ({ id: t.id, name: t.name }))
    const items = (list.items as any[]) || []
    const grouped: Record<string, any[]> = { post: [], validation: [] }
    for (const it of items) {
      const f = it.folder || 'post'
      if (!grouped[f]) grouped[f] = []
      grouped[f].push(it)
    }
    scriptsByFolder.value = grouped
  } catch {
    scriptsByFolder.value = { post: [], validation: [] }
  } finally {
    loading.value = false
  }
}

function toggleFolder(folder: string) {
  if (expandedFolders.value.has(folder)) expandedFolders.value.delete(folder)
  else expandedFolders.value.add(folder)
}

function selectScript(script: any) {
  currentFolder.value = script.folder || 'post'
  currentScriptId.value = script.id
  editor.value = {
    id: script.id,
    name: script.name || '',
    description: script.description || '',
    enabled: script.enabled !== false,
    code: script.code || '',
  }
  debugArgsText.value = defaultArgsFor()
  debugResult.value = null
  dirty.value = false
}

function newScript() {
  currentFolder.value = currentFolder.value || 'post'
  currentScriptId.value = null
  editor.value = {
    id: null,
    name: '',
    description: '',
    enabled: true,
    code: defaultCodeFor(),
  }
  debugArgsText.value = defaultArgsFor()
  debugResult.value = null
  dirty.value = true
}

function onCodeChange(v: string) {
  editor.value.code = v
  dirty.value = true
}

function onFieldChange() {
  dirty.value = true
}

async function saveScript() {
  if (!editor.value.name.trim()) {
    toast.warning('请填写脚本名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      folder: currentFolder.value,
      name: editor.value.name.trim(),
      description: editor.value.description,
      enabled: editor.value.enabled,
      code: editor.value.code,
    }
    if (editor.value.id) {
      await kbApi.updateScript(kbId.value, editor.value.id, payload)
    } else {
      const res = await kbApi.createScript(kbId.value, payload)
      currentScriptId.value = res.id
    }
    toast.success('脚本已保存', editor.value.name)
    dirty.value = false
    await loadAll()
  } catch {
    // 拦截器提示
  } finally {
    saving.value = false
  }
}

async function deleteScript() {
  if (!editor.value.id) return
  if (!(await confirm(`确定删除脚本「${editor.value.name || '未命名'}」？`))) return
  try {
    await kbApi.deleteScript(kbId.value, editor.value.id)
    toast.success('脚本已删除')
    currentScriptId.value = null
    editor.value = { id: null, name: '', description: '', enabled: true, code: '' }
    await loadAll()
  } catch {
    // 拦截器提示
  }
}

// ============================================================
// 调试执行
// ============================================================
async function runDebug() {
  let args: any = {}
  try {
    args = debugArgsText.value.trim() ? JSON.parse(debugArgsText.value) : {}
  } catch {
    toast.warning('调试请求参数不是合法的 JSON')
    return
  }
  debugRunning.value = true
  debugResult.value = null
  try {
    const res = await kbApi.runScript(kbId.value, {
      script_id: currentScriptId.value || undefined,
      code: currentScriptId.value ? undefined : editor.value.code,
      args,
    })
    debugResult.value = res
  } catch {
    // 拦截器提示
  } finally {
    debugRunning.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="flex h-auto min-h-[520px] flex-col gap-3">
    <!-- 顶部说明 -->
    <div class="flex items-center justify-between">
      <div>
        <p class="text-sm text-muted-foreground">编写可复用的 Python 处理脚本，按调用时机组织目录，支持在线调试。</p>
        <p class="mt-0.5 text-xs text-muted-foreground/70">
          脚本需定义 <code class="rounded bg-muted px-1 font-mono text-[11px]">def run(args): ...</code>，返回 dict。
        </p>
      </div>
      <Button v-if="isEditor" size="sm" :disabled="saving" @click="saveScript">
        <Loader2 v-if="saving" class="size-4 animate-spin" :stroke-width="1.5" />
        <Save v-else class="size-4" :stroke-width="1.5" />
        保存脚本
      </Button>
    </div>

    <div class="flex flex-1 gap-3">
      <!-- ===== 左：脚本目录 ===== -->
      <div class="w-60 shrink-0 rounded-lg border border-border bg-card">
        <div class="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">脚本目录</div>
        <div class="max-h-[420px] overflow-y-auto p-2">
          <div v-for="f in FOLDERS" :key="f.key" class="mb-1">
            <div
              class="flex cursor-pointer items-center gap-1.5 rounded px-2 py-1.5 hover:bg-muted/60"
              :class="currentFolder === f.key ? 'bg-muted/80' : ''"
              @click="toggleFolder(f.key); currentFolder = f.key"
            >
              <ChevronDown v-if="expandedFolders.has(f.key)" class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
              <ChevronRight v-else class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
              <component :is="f.icon" class="size-4" :stroke-width="1.5" />
              <span class="flex-1 text-sm">{{ f.label }}</span>
              <Badge variant="secondary" class="text-[10px]">{{ (scriptsByFolder[f.key] || []).length }}</Badge>
            </div>
            <div v-if="expandedFolders.has(f.key)" class="ml-4 space-y-0.5">
              <div
                v-for="s in scriptsByFolder[f.key] || []"
                :key="s.id"
                class="flex cursor-pointer items-center gap-1.5 rounded px-2 py-1 text-xs hover:bg-muted/60"
                :class="currentScriptId === s.id ? 'bg-primary/10 text-primary' : 'text-foreground/80'"
                @click="selectScript(s)"
              >
                <FileCode2 class="size-3.5 shrink-0" :stroke-width="1.5" />
                <span class="flex-1 truncate">{{ s.name }}</span>
                <span v-if="s.enabled === false" class="text-[10px] text-muted-foreground">停</span>
              </div>
              <div v-if="isEditor" class="pt-0.5">
                <Button variant="ghost" size="sm" class="h-6 w-full justify-start text-primary" @click="currentFolder = f.key; newScript()">
                  <Plus class="size-3.5" :stroke-width="1.5" />
                  新建脚本
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== 中：脚本编辑区 ===== -->
      <div class="flex min-w-0 flex-1 flex-col rounded-lg border border-border bg-card">
        <div class="flex items-center gap-2 border-b border-border px-3 py-2">
          <Code2 class="size-4 text-muted-foreground" :stroke-width="1.5" />
          <Input
            v-model="editor.name"
            :disabled="!isEditor"
            placeholder="脚本名称"
            class="h-7 max-w-52 font-medium"
            @update:model-value="onFieldChange"
          />
          <Switch v-if="isEditor" v-model="editor.enabled" @update:model-value="onFieldChange" />
          <span class="text-xs text-muted-foreground">{{ editor.enabled ? '启用' : '关闭' }}</span>
          <div class="ml-auto flex items-center gap-2">
            <span v-if="dirty" class="text-[10px] text-amber-500">未保存</span>
            <Button v-if="isEditor && editor.id" variant="ghost" size="icon" class="size-7" @click="deleteScript">
              <Trash2 class="size-3.5" :stroke-width="1.5" />
            </Button>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2 px-3 py-2 sm:grid-cols-4">
          <div>
            <Label class="text-[10px] text-muted-foreground">目录</Label>
            <div class="mt-0.5 text-xs">{{ folderMeta.name || FOLDERS.find((f) => f.key === currentFolder)?.label }}</div>
          </div>
          <div class="col-span-3">
            <Label class="text-[10px] text-muted-foreground">说明</Label>
            <Input
              v-if="isEditor"
              v-model="editor.description"
              placeholder="脚本用途说明"
              class="mt-0.5 h-7"
              @update:model-value="onFieldChange"
            />
            <div v-else class="mt-0.5 truncate text-xs">{{ editor.description || '—' }}</div>
          </div>
        </div>
        <!-- 代码编辑器（带行号） -->
        <div class="relative min-h-[280px] flex-1 overflow-hidden border-t border-border">
          <div class="flex h-full">
            <div class="select-none border-r border-border bg-muted/40 px-2 py-3 text-right font-mono text-[12px] leading-5 text-muted-foreground/70">
              <div v-for="n in lineCount" :key="n" class="w-6">{{ n }}</div>
            </div>
            <textarea
              :value="editor.code"
              :readonly="!isEditor"
              spellcheck="false"
              class="h-full flex-1 resize-none bg-transparent p-3 font-mono text-[13px] leading-5 text-foreground outline-none"
              @input="onCodeChange(($event.target as HTMLTextAreaElement).value)"
            />
          </div>
          <div class="pointer-events-none absolute bottom-2 right-3 text-[10px] text-muted-foreground/60">
            Python · {{ lineCount }} 行
          </div>
        </div>
      </div>

      <!-- ===== 右：可传入 / 返回参数 / 工具 / 术语集（可折叠） ===== -->
      <div class="w-72 shrink-0 space-y-2 overflow-y-auto">
        <!-- 可传入参数 -->
        <div class="rounded-lg border border-border bg-card">
          <div class="flex cursor-pointer items-center gap-1.5 px-3 py-2" @click="togglePanel('input')">
            <ChevronDown v-if="openPanels.has('input')" class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <ChevronRight v-else class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <ArrowDownToLine class="size-3.5 text-emerald-500" :stroke-width="1.5" />
            <span class="text-xs font-medium">可传入参数</span>
            <span class="ml-auto text-[10px] text-muted-foreground">{{ inputParams.length }}</span>
          </div>
          <div v-if="openPanels.has('input')" class="space-y-2 border-t border-border p-3">
            <div v-for="p in inputParams" :key="p.name" class="rounded bg-muted/40 p-2">
              <div class="flex items-center gap-1.5">
                <code class="font-mono text-[11px] text-emerald-600">{{ p.name }}</code>
                <span class="text-[10px] text-muted-foreground">{{ p.type }}</span>
              </div>
              <p class="mt-0.5 text-[10px] leading-tight text-muted-foreground">{{ p.desc }}</p>
            </div>
            <p v-if="!inputParams.length" class="text-[10px] text-muted-foreground">当前目录无需传入参数</p>
            <button v-if="isEditor" class="text-[10px] text-primary hover:underline" @click="debugArgsText = defaultArgsFor()">
              重置调试默认值
            </button>
          </div>
        </div>
        <!-- 返回参数 -->
        <div class="rounded-lg border border-border bg-card">
          <div class="flex cursor-pointer items-center gap-1.5 px-3 py-2" @click="togglePanel('output')">
            <ChevronDown v-if="openPanels.has('output')" class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <ChevronRight v-else class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <ArrowUpFromLine class="size-3.5 text-blue-500" :stroke-width="1.5" />
            <span class="text-xs font-medium">返回参数</span>
            <span class="ml-auto text-[10px] text-muted-foreground">{{ outputParams.length }}</span>
          </div>
          <div v-if="openPanels.has('output')" class="space-y-2 border-t border-border p-3">
            <div v-for="p in outputParams" :key="p.name" class="rounded bg-muted/40 p-2">
              <div class="flex items-center gap-1.5">
                <code class="font-mono text-[11px] text-blue-600">{{ p.name }}</code>
                <span class="text-[10px] text-muted-foreground">{{ p.type }}</span>
              </div>
              <p class="mt-0.5 text-[10px] leading-tight text-muted-foreground">{{ p.desc }}</p>
            </div>
            <p v-if="!outputParams.length" class="text-[10px] text-muted-foreground">当前目录无需返回参数</p>
          </div>
        </div>
        <!-- kb_tool 可用工具 -->
        <div class="rounded-lg border border-border bg-card">
          <div class="flex cursor-pointer items-center gap-1.5 px-3 py-2" @click="togglePanel('tools')">
            <ChevronDown v-if="openPanels.has('tools')" class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <ChevronRight v-else class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <Wrench class="size-3.5 text-violet-500" :stroke-width="1.5" />
            <span class="text-xs font-medium">kb_tool 可用工具</span>
            <span class="ml-auto text-[10px] text-muted-foreground">{{ toolCatalog.length }}</span>
          </div>
          <div v-if="openPanels.has('tools')" class="space-y-2 border-t border-border p-3">
            <p class="text-[10px] leading-tight text-muted-foreground">脚本内通过 <code class="rounded bg-muted px-1 font-mono text-[10px]">await kb_tools.xxx(...)</code> 调用内置能力</p>
            <div v-for="t in toolCatalog" :key="t.name" class="rounded border border-border/60 p-2">
              <button class="flex w-full items-center gap-1.5 text-left" @click="toggleToolUsage(t.name)">
                <ChevronDown v-if="openToolUsage.has(t.name)" class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
                <ChevronRight v-else class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
                <code class="font-mono text-[11px] font-semibold text-violet-600">{{ t.name }}</code>
              </button>
              <div v-if="openToolUsage.has(t.name)" class="mt-1.5 space-y-1.5 border-t border-border/40 pt-1.5">
                <p class="text-[10px] leading-tight text-muted-foreground">{{ t.desc }}</p>
                <div v-if="t.params?.length">
                  <p class="text-[10px] font-medium text-muted-foreground">入参：</p>
                  <div v-for="p in t.params" :key="p.name" class="mt-0.5 pl-1">
                    <code class="font-mono text-[10px] text-foreground">{{ p.name }}</code>
                    <span class="text-[10px] text-muted-foreground"> : {{ p.type }}</span>
                    <p class="text-[10px] leading-tight text-muted-foreground">{{ p.desc }}</p>
                  </div>
                </div>
                <p v-if="t.returns" class="text-[10px] leading-tight text-muted-foreground"><span class="font-medium text-foreground">出参：</span>{{ t.returns }}</p>
                <div v-if="t.usage" class="rounded bg-muted/50">
                  <p class="px-1.5 py-1 text-[10px] font-medium text-muted-foreground">用法：</p>
                  <pre class="whitespace-pre-wrap border-t border-border/40 px-1.5 py-1.5 font-mono text-[10px] leading-snug text-foreground">{{ t.usage }}</pre>
                </div>
              </div>
            </div>
            <p v-if="!toolCatalog.length" class="text-[10px] text-muted-foreground">当前目录无可调用工具</p>
          </div>
        </div>
        <!-- 可用术语集 -->
        <div class="rounded-lg border border-border bg-card">
          <div class="flex cursor-pointer items-center gap-1.5 px-3 py-2" @click="togglePanel('termbases')">
            <ChevronDown v-if="openPanels.has('termbases')" class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <ChevronRight v-else class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
            <BookOpen class="size-3.5 text-amber-500" :stroke-width="1.5" />
            <span class="text-xs font-medium">可用术语集</span>
            <span class="ml-auto text-[10px] text-muted-foreground">{{ termBases.length }}</span>
          </div>
          <div v-if="openPanels.has('termbases')" class="space-y-2 border-t border-border p-3">
            <p class="text-[10px] leading-tight text-muted-foreground">术语集通过 <code class="rounded bg-muted px-1 font-mono text-[10px]">kb_tools.get_term_records</code> 读取，返回键为修改后字段名的记录列表</p>
            <div v-for="tb in termBases" :key="tb.id" class="rounded bg-muted/40 p-2">
              <button class="flex w-full items-center gap-1.5 text-left" @click="toggleTermUsage(tb.id)">
                <ChevronDown v-if="openTermUsage.has(tb.id)" class="size-3 text-muted-foreground" :stroke-width="1.5" />
                <ChevronRight v-else class="size-3 text-muted-foreground" :stroke-width="1.5" />
                <code class="font-mono text-[11px] text-amber-600">{{ tb.name }}</code>
              </button>
              <pre v-if="openTermUsage.has(tb.id)" class="mt-1 whitespace-pre-wrap font-mono text-[10px] leading-snug text-muted-foreground">rows = await kb_tools.get_term_records("{{ tb.name }}", "字段名")
# rows = [{"字段名": "值", ...}, ...]</pre>
            </div>
            <p v-if="!termBases.length" class="text-[10px] text-muted-foreground">当前知识库暂无术语集，请先在「专业术语集」中创建</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 底部：调试请求块 ===== -->
    <div class="rounded-lg border border-border bg-card">
      <div class="flex items-center gap-2 border-b border-border px-3 py-2">
        <Bug class="size-4 text-amber-500" :stroke-width="1.5" />
        <span class="text-xs font-medium">接口参数调用与调试</span>
        <span class="text-[10px] text-muted-foreground">模拟 {{ folderMeta.name || '当前目录' }} 的运行时入参</span>
        <div class="ml-auto">
          <Button size="sm" :disabled="debugRunning" @click="runDebug">
            <Loader2 v-if="debugRunning" class="size-4 animate-spin" :stroke-width="1.5" />
            <Play v-else class="size-4" :stroke-width="1.5" />
            运行调试
          </Button>
        </div>
      </div>
      <div class="grid gap-3 p-3 lg:grid-cols-2">
        <div>
          <Label class="text-[10px] text-muted-foreground">请求参数 (args JSON)</Label>
          <Textarea
            v-model="debugArgsText"
            :readonly="!isEditor && !currentScriptId"
            spellcheck="false"
            class="mt-1 min-h-[140px] bg-muted/30 font-mono text-[12px]"
          />
        </div>
        <div>
          <Label class="text-[10px] text-muted-foreground">返回结果</Label>
          <div class="mt-1 min-h-[140px] overflow-auto rounded border border-border bg-muted/30 p-3 font-mono text-[12px]">
            <pre v-if="debugResult" class="whitespace-pre-wrap" :class="debugResult.ok ? 'text-foreground' : 'text-red-500'">
{{ JSON.stringify(debugResult.ok ? debugResult.result : { ok: false, error: debugResult?.error }, null, 2) }}</pre>
            <span v-else class="text-muted-foreground/60">运行后在此展示结果</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>