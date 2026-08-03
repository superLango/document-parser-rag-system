<script setup lang="ts">
/**
 * 知识库配置中心
 *
 * 标签页：
 *   1. 基础配置（OCR/向量/抽取/问答 config JSON 读写）
 *   2. 领域类别（类别 CRUD + enum 约束）
 *   3. Hook 管理（脚本读写/重载/删除）
 *   4. 模板应用（列表/应用模板）
 *   5. 校验诊断（配置校验 + 资源诊断）
 *
 * 权限：viewer 可查看；admin+ 可修改
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Settings,
  ListPlus,
  Code2,
  Sparkles,
  ShieldCheck,
  Loader2,
  RefreshCw,
  Plus,
  Trash2,
  Save,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Upload,
  Download,
  DatabaseBackup,
  FileArchive,
  Network,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { systemApi } from '@/api/modules/system'
import { useKbPermission } from '@/composables/useKbPermission'
import type {
  KbConfig,
  KbHookContent,
  KbConfigValidation,
  KbResourceVerify,
  DomainTemplateSummary,
  ApplyTemplateResult,
  KbBackup,
  KbBackupRestoreStats,
} from '@/api/types'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { PageHeader } from '@/components/ui/page-header'

const route = useRoute()
const kbId = computed(() => route.params.kb_id as string)
const { isAdmin } = useKbPermission()

const activeTab = ref<'config' | 'categories' | 'hook' | 'templates' | 'diagnostics' | 'backup'>('config')
const tabs = [
  { key: 'config' as const, label: '基础配置', icon: Settings },
  { key: 'categories' as const, label: '领域类别', icon: ListPlus },
  { key: 'hook' as const, label: 'Hook 管理', icon: Code2 },
  { key: 'templates' as const, label: '模板应用', icon: Sparkles },
  { key: 'diagnostics' as const, label: '校验诊断', icon: ShieldCheck },
  { key: 'backup' as const, label: '备份恢复', icon: DatabaseBackup },
]

// ===== 基础配置 =====
const configLoading = ref(true)
const configSaving = ref(false)
const kbConfig = ref<KbConfig | null>(null)
const configSections = ['ocr', 'vector', 'extraction', 'qa', 'dict'] as const
const editingConfig = ref<Record<string, Record<string, unknown>>>({})

// 版面分析模型检查状态
const layoutCheckLoading = ref(false)
const layoutCheckResult = ref<{
  status: 'healthy' | 'unavailable' | 'unhealthy'
  error?: string
  model_dir?: string
} | null>(null)

// NebulaGraph 图谱服务检查状态
const nebulaCheckLoading = ref(false)
const nebulaCheckResult = ref<{
  status: 'healthy' | 'unavailable' | 'degraded' | 'timeout'
  host?: string
  port?: number
  host_count?: number
  space_count?: number
  spaces?: string[]
  message?: string
  error?: string
} | null>(null)

/** 检查版面分析模型可用性 */
async function checkLayoutModel() {
  layoutCheckLoading.value = true
  try {
    const res = await systemApi.checkOcrLayout()
    layoutCheckResult.value = res as typeof layoutCheckResult.value
    if (res.status === 'healthy') {
      toast.success('模型可用', `版面分析模型 ${res.model_dir || 'PP-DocLayoutV3'} 已就绪`)
    } else {
      toast.error('模型不可用', res.error || '版面分析模型初始化失败')
    }
  } catch (err) {
    layoutCheckResult.value = { status: 'unavailable', error: '检查请求失败' }
  } finally {
    layoutCheckLoading.value = false
  }
}

/** 检查 NebulaGraph 图谱服务可用性 */
async function checkNebulaGraph() {
  nebulaCheckLoading.value = true
  try {
    const res = await systemApi.checkNebulaGraph()
    nebulaCheckResult.value = res as typeof nebulaCheckResult.value
    if (res.status === 'healthy') {
      toast.success('图谱服务可用', `NebulaGraph ${res.host}:${res.port}，共 ${res.space_count ?? 0} 个 space`)
    } else if (res.status === 'timeout') {
      toast.error('图谱服务超时', 'NebulaGraph 健康检查超时，请检查服务状态')
    } else {
      toast.warning('图谱服务不可用', res.message || res.error || '图谱功能将优雅降级，文档解析不受影响')
    }
  } catch (err) {
    nebulaCheckResult.value = { status: 'unavailable', error: '检查请求失败' }
  } finally {
    nebulaCheckLoading.value = false
  }
}

/** 版面分析开关变更 */
function onLayoutToggle(checked: boolean) {
  if (!checked) {
    // 关闭时不需要检查
    return
  }
  // 启用时立即检查模型可用性
  checkLayoutModel()
}

async function fetchConfig() {
  configLoading.value = true
  try {
    kbConfig.value = await kbApi.getConfig(kbId.value)
    // 深拷贝用于编辑
    editingConfig.value = JSON.parse(JSON.stringify(kbConfig.value.config || {}))
    for (const s of configSections) {
      if (!editingConfig.value[s]) editingConfig.value[s] = {}
    }
  } catch {
    kbConfig.value = null
  } finally {
    configLoading.value = false
  }
}

async function saveConfig() {
  configSaving.value = true
  try {
    await kbApi.updateConfig(kbId.value, editingConfig.value)
    toast.success('配置已保存', '知识库配置更新成功')
    await fetchConfig()
  } catch {
    // 错误已由拦截器提示
  } finally {
    configSaving.value = false
  }
}

// ===== 领域类别 =====
const categories = ref<Record<string, unknown>[]>([])

async function fetchCategories() {
  try {
    const res = await kbApi.listCategories(kbId.value)
    categories.value = res.items
  } catch {
    categories.value = []
  }
}

async function toggleCategory(cat: Record<string, unknown>) {
  if (!isAdmin.value) return
  try {
    await kbApi.updateCategory(kbId.value, cat.id as string, {
      is_active: !cat.is_active,
    })
    await fetchCategories()
    toast.success('已更新', `类别「${cat.name}」已${cat.is_active ? '停用' : '启用'}`)
  } catch {
    // 错误已由拦截器提示
  }
}

async function deleteCategory(cat: Record<string, unknown>) {
  if (!isAdmin.value) return
  if (!confirm(`确定删除类别「${cat.name}」？关联的 enum 约束将一并删除。`)) return
  try {
    await kbApi.deleteCategory(kbId.value, cat.id as string)
    await fetchCategories()
    toast.success('已删除', cat.name as string)
  } catch {
    // 错误已由拦截器提示
  }
}

// 新增类别表单
const showAddCategory = ref(false)
const newCategory = ref({ name: '', extraction_class: '', description: '', is_active: true })

async function addCategory() {
  if (!newCategory.value.name.trim()) {
    toast.warning('请填写类别名')
    return
  }
  try {
    await kbApi.createCategory(kbId.value, {
      name: newCategory.value.name.trim(),
      extraction_class: newCategory.value.extraction_class.trim() || newCategory.value.name.trim(),
      description: newCategory.value.description.trim() || undefined,
      is_active: newCategory.value.is_active,
    })
    toast.success('类别已创建', newCategory.value.name)
    newCategory.value = { name: '', extraction_class: '', description: '', is_active: true }
    showAddCategory.value = false
    await fetchCategories()
  } catch {
    // 错误已由拦截器提示
  }
}

// ===== Hook 管理 =====
const hookContent = ref<KbHookContent | null>(null)
const hookEditing = ref('')
const hookSaving = ref(false)

async function fetchHook() {
  try {
    hookContent.value = await kbApi.getHookContent(kbId.value)
    hookEditing.value = hookContent.value.content
  } catch {
    hookContent.value = null
  }
}

async function saveHook() {
  hookSaving.value = true
  try {
    await kbApi.updateHookContent(kbId.value, hookEditing.value)
    toast.success('Hook 已保存', '下次调用自动重载')
    await fetchHook()
  } catch {
    // 错误已由拦截器提示
  } finally {
    hookSaving.value = false
  }
}

async function reloadHook() {
  try {
    await kbApi.reloadHook(kbId.value)
    toast.success('Hook 已重载', '缓存已清除')
  } catch {
    // 错误已由拦截器提示
  }
}

async function deleteHook() {
  if (!confirm('确定删除 Hook 脚本？将回退到默认逻辑。')) return
  try {
    await kbApi.deleteHook(kbId.value)
    toast.success('Hook 已删除', '回退默认逻辑')
    await fetchHook()
  } catch {
    // 错误已由拦截器提示
  }
}

// ===== 模板应用 =====
const templates = ref<DomainTemplateSummary[]>([])
const applyingTemplate = ref<string | null>(null)

async function fetchTemplates() {
  try {
    const res = await kbApi.listTemplates()
    templates.value = res.items
  } catch {
    templates.value = []
  }
}

async function applyTemplate(code: string) {
  if (!confirm(`确定应用模板「${code}」？将覆盖当前所有领域配置（类别/正则/字段模板/字典配置）。`)) return
  applyingTemplate.value = code
  try {
    const res: ApplyTemplateResult = await kbApi.applyTemplate(kbId.value, code)
    toast.success('模板已应用', `写入 ${res.categories_written} 类别、${res.regex_rules_written} 正则`)
    await fetchConfig()
    await fetchCategories()
  } catch {
    // 错误已由拦截器提示
  } finally {
    applyingTemplate.value = null
  }
}

// ===== 校验诊断 =====
const validation = ref<KbConfigValidation | null>(null)
const resourceVerify = ref<KbResourceVerify | null>(null)
const validating = ref(false)
const verifying = ref(false)

async function runValidation() {
  validating.value = true
  try {
    validation.value = await kbApi.validateConfig(kbId.value)
  } catch {
    validation.value = null
  } finally {
    validating.value = false
  }
}

async function runVerify() {
  verifying.value = true
  try {
    resourceVerify.value = await kbApi.verifyResources(kbId.value)
  } catch {
    resourceVerify.value = null
  } finally {
    verifying.value = false
  }
}

function onTabChange(key: typeof activeTab.value) {
  activeTab.value = key
  if (key === 'categories' && categories.value.length === 0) fetchCategories()
  if (key === 'hook' && !hookContent.value) fetchHook()
  if (key === 'templates' && templates.value.length === 0) fetchTemplates()
  if (key === 'diagnostics') {
    if (!validation.value) runValidation()
    if (!resourceVerify.value) runVerify()
  }
  if (key === 'backup' && backups.value.length === 0) fetchBackups()
}

// ===== 备份恢复 =====
const backups = ref<KbBackup[]>([])
const backupsLoading = ref(false)
const backupCreating = ref(false)
const restoreFile = ref<File | null>(null)
const restoring = ref(false)

async function fetchBackups() {
  backupsLoading.value = true
  try {
    const res = await kbApi.listBackups(kbId.value, { page: 1, page_size: 50 })
    backups.value = res.items
  } catch {
    backups.value = []
  } finally {
    backupsLoading.value = false
  }
}

async function createBackup() {
  backupCreating.value = true
  try {
    await kbApi.createBackup(kbId.value)
    toast.success('备份成功', '知识库数据已打包')
    await fetchBackups()
  } catch {
    // 错误已由拦截器提示
  } finally {
    backupCreating.value = false
  }
}

async function deleteBackup(backup: KbBackup) {
  if (!confirm(`确定删除备份「${backup.file_name}」？此操作不可撤销。`)) return
  try {
    await kbApi.deleteBackup(kbId.value, backup.id)
    toast.success('已删除', backup.file_name)
    await fetchBackups()
  } catch {
    // 错误已由拦截器提示
  }
}

async function downloadBackup(backup: KbBackup) {
  try {
    const token = localStorage.getItem('token')
    const res = await fetch(kbApi.downloadBackupUrl(kbId.value, backup.id), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error('下载失败')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = backup.file_name
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    toast.error('下载失败', '请稍后重试')
  }
}

function onRestoreFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    restoreFile.value = input.files[0]
  }
}

async function restoreBackup() {
  if (!restoreFile.value) {
    toast.warning('请先选择备份文件')
    return
  }
  if (!confirm('恢复将覆盖当前 KB 的配置与领域配置，文档/Schema/术语按去重跳过。确定继续？')) return
  restoring.value = true
  try {
    const stats = await kbApi.restoreBackup(kbId.value, restoreFile.value)
    toast.success('恢复完成', `文档+${stats.documents} Schema+${stats.schemas} 术语+${stats.terms}`)
    restoreFile.value = null
    // 刷新配置
    await fetchConfig()
  } catch {
    // 错误已由拦截器提示
  } finally {
    restoring.value = false
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

onMounted(() => {
  fetchConfig()
  checkNebulaGraph()
})
</script>

<template>
  <div>
    <PageHeader title="配置中心" description="OCR / 向量 / 抽取 / 问答 / 领域配置 / Hook / 模板" />

    <!-- 标签页 -->
    <div class="mb-4 flex items-center gap-1 border-b border-border">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors"
        :class="activeTab === tab.key
          ? 'border-primary text-primary font-medium'
          : 'border-transparent text-muted-foreground hover:text-foreground'"
        @click="onTabChange(tab.key)"
      >
        <component :is="tab.icon" class="size-4" :stroke-width="1.5" />
        {{ tab.label }}
      </button>
    </div>

    <!-- 基础配置 -->
    <div v-if="activeTab === 'config'">
      <!-- NebulaGraph 图谱服务状态卡片 -->
      <Card class="mb-4 border-l-4"
        :class="nebulaCheckResult?.status === 'healthy'
          ? 'border-l-success'
          : (nebulaCheckResult?.status === 'timeout' ? 'border-l-destructive' : 'border-l-warning')"
      >
        <CardContent class="p-4">
          <div class="flex items-center justify-between">
            <div class="space-y-1">
              <div class="flex items-center gap-2">
                <Network class="size-4 text-muted-foreground" :stroke-width="1.5" />
                <span class="text-sm font-medium">NebulaGraph 图谱服务</span>
                <Badge
                  v-if="nebulaCheckResult?.status === 'healthy'"
                  variant="default"
                  class="bg-success/15 text-success text-[10px]"
                >
                  可用
                </Badge>
                <Badge
                  v-else-if="nebulaCheckResult?.status === 'timeout'"
                  variant="destructive"
                  class="text-[10px]"
                >
                  超时
                </Badge>
                <Badge
                  v-else
                  variant="warning"
                  class="text-[10px]"
                >
                  不可用 · 降级
                </Badge>
              </div>
              <p class="text-xs text-muted-foreground">
                {{ nebulaCheckResult?.host || 'localhost' }}:{{ nebulaCheckResult?.port || 9669 }}
                <template v-if="nebulaCheckResult?.status === 'healthy'">
                  · {{ nebulaCheckResult.space_count ?? 0 }} 个 space · {{ nebulaCheckResult.host_count ?? 0 }} 个节点
                </template>
                <template v-else-if="nebulaCheckResult?.message">
                  · {{ nebulaCheckResult.message }}
                </template>
                <template v-else-if="nebulaCheckResult?.error">
                  · {{ nebulaCheckResult.error }}
                </template>
              </p>
              <p class="text-[11px] text-muted-foreground/80">
                图谱服务不可用时，文档解析/删除等主流程将优雅降级（跳过图谱读写），不影响向量检索与 OCR
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              class="h-8 px-2 text-xs"
              :disabled="nebulaCheckLoading"
              @click="checkNebulaGraph"
            >
              <Loader2 v-if="nebulaCheckLoading" class="size-3 animate-spin" :stroke-width="1.5" />
              <RefreshCw v-else class="size-3" :stroke-width="1.5" />
              检查
            </Button>
          </div>
        </CardContent>
      </Card>

      <div v-if="configLoading" class="space-y-3">
        <Skeleton v-for="i in 3" :key="i" class="h-40 w-full" />
      </div>
      <div v-else class="space-y-4">
        <Card v-for="section in configSections" :key="section">
          <CardContent class="p-4">
            <div class="mb-3 flex items-center justify-between">
              <h3 class="text-sm font-medium capitalize text-foreground">{{ section }} 配置</h3>
              <Badge variant="secondary" class="text-[10px]">
                {{ Object.keys(editingConfig[section] || {}).length }} 项
              </Badge>
            </div>

            <!-- OCR 特殊配置：版面分析开关 -->
            <div v-if="section === 'ocr'" class="mb-3 rounded-md border border-border bg-muted/30 p-3">
              <div class="flex items-center justify-between">
                <div class="space-y-0.5">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-medium">版面分析（PP-DocLayoutV3）</span>
                    <Badge
                      v-if="layoutCheckResult?.status === 'healthy'"
                      variant="default"
                      class="bg-success/15 text-success text-[10px]"
                    >
                      模型可用
                    </Badge>
                    <Badge
                      v-else-if="layoutCheckResult?.status === 'unavailable' || layoutCheckResult?.status === 'unhealthy'"
                      variant="destructive"
                      class="text-[10px]"
                    >
                      模型不可用
                    </Badge>
                  </div>
                  <p class="text-xs text-muted-foreground">
                    启用后将使用 PP-DocLayoutV3 进行文档版面区域检测（标题/正文/表格/图片等），禁用时直接整页 OCR
                  </p>
                  <p v-if="layoutCheckResult?.error" class="text-xs text-destructive">
                    {{ layoutCheckResult.error }}
                  </p>
                </div>
                <div class="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    class="h-8 px-2 text-xs"
                    :disabled="layoutCheckLoading || !isAdmin"
                    @click="checkLayoutModel"
                  >
                    <Loader2 v-if="layoutCheckLoading" class="size-3 animate-spin" :stroke-width="1.5" />
                    <RefreshCw v-else class="size-3" :stroke-width="1.5" />
                    检查模型
                  </Button>
                  <Switch
                    :checked="(editingConfig.ocr?.layout_analysis_enabled as boolean) ?? true"
                    :disabled="!isAdmin"
                    @update:checked="(v: boolean) => {
                      editingConfig.ocr = editingConfig.ocr || {}
                      editingConfig.ocr.layout_analysis_enabled = v
                      onLayoutToggle(v)
                    }"
                  />
                </div>
              </div>
            </div>

            <Textarea
              :model-value="JSON.stringify(editingConfig[section] || {}, null, 2)"
              @update:model-value="(v: string) => { try { editingConfig[section] = JSON.parse(v) } catch {} }"
              class="font-mono text-xs"
              rows="6"
              :disabled="!isAdmin"
              placeholder="{}"
            />
          </CardContent>
        </Card>
        <div v-if="isAdmin" class="flex justify-end">
          <Button :disabled="configSaving" @click="saveConfig">
            <Loader2 v-if="configSaving" class="size-4 animate-spin" :stroke-width="1.5" />
            <Save v-else class="size-4" :stroke-width="1.5" />
            保存配置
          </Button>
        </div>
      </div>
    </div>

    <!-- 领域类别 -->
    <div v-else-if="activeTab === 'categories'">
      <div class="mb-4 flex items-center justify-between">
        <p class="text-sm text-muted-foreground">共 {{ categories.length }} 个类别</p>
        <Button v-if="isAdmin" size="sm" @click="showAddCategory = !showAddCategory">
          <Plus class="size-4" :stroke-width="1.5" />
          新增类别
        </Button>
      </div>

      <!-- 新增表单 -->
      <Card v-if="showAddCategory && isAdmin" class="mb-4 border-primary/40">
        <CardContent class="space-y-3 p-4">
          <div class="grid grid-cols-2 gap-3">
            <Input v-model="newCategory.name" placeholder="类别名（如：化学成分）" />
            <Input v-model="newCategory.extraction_class" placeholder="extraction_class（留空同类别名）" />
          </div>
          <Input v-model="newCategory.description" placeholder="描述（可选）" />
          <div class="flex justify-end gap-2">
            <Button variant="outline" size="sm" @click="showAddCategory = false">取消</Button>
            <Button size="sm" @click="addCategory">创建</Button>
          </div>
        </CardContent>
      </Card>

      <div class="space-y-2">
        <Card v-for="cat in categories" :key="cat.id as string">
          <CardContent class="flex items-center gap-3 p-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <p class="font-medium text-foreground">{{ cat.name }}</p>
                <Badge v-if="cat.is_active === false" variant="secondary" class="text-[10px]">停用</Badge>
              </div>
              <p class="mt-0.5 truncate text-xs text-muted-foreground">
                class={{ cat.extraction_class }} · {{ cat.description || '无描述' }}
              </p>
              <div v-if="cat.enums" class="mt-1 flex flex-wrap gap-1">
                <Badge
                  v-for="(vals, field) in (cat.enums as Record<string, string[]>)"
                  :key="field"
                  variant="outline"
                  class="text-[10px]"
                >
                  {{ field }}: {{ vals.length }}
                </Badge>
              </div>
            </div>
            <div v-if="isAdmin" class="flex shrink-0 gap-1">
              <Button variant="ghost" size="sm" @click="toggleCategory(cat)">
                {{ cat.is_active === false ? '启用' : '停用' }}
              </Button>
              <Button variant="ghost" size="sm" @click="deleteCategory(cat)">
                <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- Hook 管理 -->
    <div v-else-if="activeTab === 'hook'">
      <div class="mb-4 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Badge :variant="hookContent?.has_hook ? 'default' : 'secondary'">
            {{ hookContent?.has_hook ? '已配置' : '未配置（使用默认）' }}
          </Badge>
          <span v-if="hookContent?.overridden_interfaces.length" class="text-xs text-muted-foreground">
            覆盖接口: {{ hookContent.overridden_interfaces.join(', ') }}
          </span>
        </div>
        <div v-if="isAdmin" class="flex gap-2">
          <Button variant="outline" size="sm" :disabled="!hookContent?.has_hook" @click="reloadHook">
            <RefreshCw class="size-4" :stroke-width="1.5" />
            重载
          </Button>
          <Button variant="outline" size="sm" :disabled="!hookContent?.has_hook" @click="deleteHook">
            <Trash2 class="size-4" :stroke-width="1.5" />
            删除
          </Button>
          <Button size="sm" :disabled="hookSaving" @click="saveHook">
            <Loader2 v-if="hookSaving" class="size-4 animate-spin" :stroke-width="1.5" />
            <Save v-else class="size-4" :stroke-width="1.5" />
            保存
          </Button>
        </div>
      </div>
      <Textarea
        v-model="hookEditing"
        class="font-mono text-xs"
        rows="20"
        :disabled="!isAdmin"
        placeholder="# 在此编写 Hook 脚本，覆盖默认逻辑&#10;async def post_process(records, category, **ctx):&#10;    return records"
      />
    </div>

    <!-- 模板应用 -->
    <div v-else-if="activeTab === 'templates'">
      <p class="mb-4 text-sm text-muted-foreground">
        应用模板将覆盖当前所有领域配置（类别/正则/字段模板/字典配置），但不影响已上传的文档与数据。
      </p>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card v-for="tpl in templates" :key="tpl.code" class="border-2">
          <CardContent class="p-4">
            <div class="mb-2 flex items-center justify-between">
              <h4 class="font-medium text-foreground">{{ tpl.name }}</h4>
              <Badge variant="secondary" class="font-mono text-[10px]">{{ tpl.code }}</Badge>
            </div>
            <p class="mb-3 line-clamp-2 text-xs text-muted-foreground">{{ tpl.description }}</p>
            <div class="mb-3 flex flex-wrap gap-1">
              <Badge variant="outline" class="text-[10px]">{{ tpl.category_count }} 类别</Badge>
              <Badge variant="outline" class="text-[10px]">{{ tpl.regex_rule_count }} 正则</Badge>
              <Badge v-if="tpl.has_hook" variant="outline" class="text-[10px]">Hook</Badge>
            </div>
            <Button
              v-if="isAdmin"
              size="sm"
              class="w-full"
              :disabled="applyingTemplate === tpl.code"
              @click="applyTemplate(tpl.code)"
            >
              <Loader2 v-if="applyingTemplate === tpl.code" class="size-4 animate-spin" :stroke-width="1.5" />
              <Upload v-else class="size-4" :stroke-width="1.5" />
              应用此模板
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- 校验诊断 -->
    <div v-else-if="activeTab === 'diagnostics'" class="space-y-4">
      <!-- 配置校验 -->
      <Card>
        <CardContent class="p-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="flex items-center gap-2 text-sm font-medium">
              <ShieldCheck class="size-4" :stroke-width="1.5" />
              配置校验
            </h3>
            <Button variant="outline" size="sm" :disabled="validating" @click="runValidation">
              <Loader2 v-if="validating" class="size-3.5 animate-spin" :stroke-width="1.5" />
              <RefreshCw v-else class="size-3.5" :stroke-width="1.5" />
              重新校验
            </Button>
          </div>
          <div v-if="validation">
            <div class="mb-2 flex items-center gap-2">
              <component
                :is="validation.valid ? CheckCircle2 : XCircle"
                class="size-5"
                :class="validation.valid ? 'text-success' : 'text-danger'"
                :stroke-width="1.5"
              />
              <span class="font-medium" :class="validation.valid ? 'text-success' : 'text-danger'">
                {{ validation.valid ? '配置有效' : '配置存在问题' }}
              </span>
            </div>
            <div v-if="validation.errors.length" class="mt-2 space-y-1">
              <p v-for="e in validation.errors" :key="e" class="flex items-center gap-1.5 text-xs text-danger">
                <XCircle class="size-3 shrink-0" :stroke-width="1.5" />{{ e }}
              </p>
            </div>
            <div v-if="validation.warnings.length" class="mt-2 space-y-1">
              <p v-for="w in validation.warnings" :key="w" class="flex items-center gap-1.5 text-xs text-warning">
                <AlertTriangle class="size-3 shrink-0" :stroke-width="1.5" />{{ w }}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- 资源诊断 -->
      <Card>
        <CardContent class="p-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="flex items-center gap-2 text-sm font-medium">
              <Settings class="size-4" :stroke-width="1.5" />
              物理资源诊断
            </h3>
            <Button variant="outline" size="sm" :disabled="verifying" @click="runVerify">
              <Loader2 v-if="verifying" class="size-3.5 animate-spin" :stroke-width="1.5" />
              <RefreshCw v-else class="size-3.5" :stroke-width="1.5" />
              重新诊断
            </Button>
          </div>
          <div v-if="resourceVerify" class="space-y-2">
            <div
              v-for="(step, name) in resourceVerify.steps"
              :key="name"
              class="flex items-center justify-between rounded-md border border-border px-3 py-2"
            >
              <span class="text-sm font-medium text-foreground">{{ name }}</span>
              <div class="flex items-center gap-2">
                <component
                  :is="step.ok ? CheckCircle2 : XCircle"
                  class="size-4"
                  :class="step.ok ? 'text-success' : 'text-danger'"
                  :stroke-width="1.5"
                />
                <span class="text-xs" :class="step.ok ? 'text-success' : 'text-danger'">
                  {{ step.detail || step.error || (step.ok ? '正常' : '异常') }}
                </span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 备份恢复 -->
    <div v-else-if="activeTab === 'backup'" class="space-y-4">
      <!-- 操作区 -->
      <Card>
        <CardContent class="p-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 class="flex items-center gap-2 text-sm font-medium">
                <DatabaseBackup class="size-4" :stroke-width="1.5" />
                数据备份
              </h3>
              <p class="mt-1 text-xs text-muted-foreground">
                打包 KB 配置 / 文档元数据 / 抽取结果 / 术语 / Schema / 领域配置为 ZIP
              </p>
            </div>
            <Button v-if="isAdmin" :disabled="backupCreating" @click="createBackup">
              <Loader2 v-if="backupCreating" class="size-4 animate-spin" :stroke-width="1.5" />
              <FileArchive v-else class="size-4" :stroke-width="1.5" />
              立即备份
            </Button>
          </div>
        </CardContent>
      </Card>

      <!-- 恢复区 -->
      <Card v-if="isAdmin">
        <CardContent class="p-4">
          <h3 class="mb-2 flex items-center gap-2 text-sm font-medium">
            <Upload class="size-4" :stroke-width="1.5" />
            数据恢复
          </h3>
          <p class="mb-3 text-xs text-muted-foreground">
            上传备份 ZIP 恢复数据。文档/Schema/术语按去重跳过，配置与领域配置将被覆盖。
          </p>
          <div class="flex items-center gap-3">
            <input
              type="file"
              accept=".zip"
              class="text-sm"
              @change="onRestoreFileChange"
            />
            <Button :disabled="!restoreFile || restoring" @click="restoreBackup">
              <Loader2 v-if="restoring" class="size-4 animate-spin" :stroke-width="1.5" />
              <DatabaseBackup v-else class="size-4" :stroke-width="1.5" />
              恢复
            </Button>
          </div>
        </CardContent>
      </Card>

      <!-- 备份列表 -->
      <Card>
        <CardContent class="p-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-sm font-medium">备份记录</h3>
            <Button variant="ghost" size="sm" :disabled="backupsLoading" @click="fetchBackups">
              <RefreshCw class="size-3.5" :stroke-width="1.5" />
              刷新
            </Button>
          </div>
          <div v-if="backupsLoading" class="flex justify-center py-8">
            <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
          </div>
          <div v-else-if="backups.length === 0" class="py-8 text-center text-sm text-muted-foreground">
            暂无备份记录
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="b in backups"
              :key="b.id"
              class="flex items-center justify-between rounded-md border border-border px-3 py-2.5"
            >
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <FileArchive class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.5" />
                  <span class="truncate text-sm font-medium text-foreground">{{ b.file_name }}</span>
                  <Badge
                    :variant="b.status === 'completed' ? 'default' : 'destructive'"
                    class="text-[10px]"
                  >
                    {{ b.status === 'completed' ? '成功' : '失败' }}
                  </Badge>
                </div>
                <div class="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{{ formatFileSize(b.file_size) }}</span>
                  <span>{{ formatTime(b.created_at) }}</span>
                  <span v-if="b.item_counts">
                    文档{{ b.item_counts.documents || 0 }} / Schema{{ b.item_counts.schemas || 0 }} / 术语{{ b.item_counts.terms || 0 }}
                  </span>
                </div>
              </div>
              <div v-if="isAdmin" class="flex shrink-0 items-center gap-1">
                <Button variant="ghost" size="sm" @click="downloadBackup(b)">
                  <Download class="size-3.5" :stroke-width="1.5" />
                </Button>
                <Button variant="ghost" size="sm" @click="deleteBackup(b)">
                  <Trash2 class="size-3.5 text-danger" :stroke-width="1.5" />
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
