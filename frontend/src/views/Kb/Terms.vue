<script setup lang="ts">
/**
 * 知识库术语库管理 - 统一术语集主页
 *
 * 功能：
 * - 术语集列表展示/创建/编辑/删除/同步
 * - 新建术语集支持三种数据源：手动录入/接口拉取/数据库直连
 * 数据隔离：/kbs/{kb_id}/term-bases，后端 RLS 强制
 * 权限：viewer 可查看；editor+ 可管理
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BookMarked,
  Plus,
  RefreshCw,
  Loader2,
  Trash2,
  Pencil,
  FileJson,
  Play,
  Globe,
  Database as DbIcon,
  Hand,
  ArrowLeft,
  ChevronRight,
  CheckCircle2,
  XCircle,
  X,
  Eye,
  RefreshCcw,
  Sparkles,
} from 'lucide-vue-next'
import { cn } from '@/lib/utils'
import { kbApi, type TermBase } from '@/api/modules/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import { toast } from '@/components/ui/toast'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { EmptyState } from '@/components/ui/empty-state'
import { Separator } from '@/components/ui/separator'
import { Checkbox } from '@/components/ui/checkbox'
import { confirm } from '@/composables/useConfirm'

const route = useRoute()
const router = useRouter()
const { isEditor } = useKbPermission()
const kbId = computed(() => route.params.kb_id as string)

const loading = ref(true)
const termBases = ref<TermBase[]>([])

// 数据源类型标签和图标 - Premium Dark-Tech 配色
const sourceTypeMeta: Record<string, { label: string; icon: any; color: string; bgGradient: string; glow: string }> = {
  manual: {
    label: '手动录入',
    icon: Hand,
    color: 'bg-sky-500/15 text-sky-400 border-sky-500/30',
    bgGradient: 'from-sky-500/10 to-sky-600/5',
    glow: 'shadow-sky-500/20',
  },
  api: {
    label: '接口拉取',
    icon: Globe,
    color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    bgGradient: 'from-emerald-500/10 to-emerald-600/5',
    glow: 'shadow-emerald-500/20',
  },
  db: {
    label: '数据库',
    icon: DbIcon,
    color: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
    bgGradient: 'from-violet-500/10 to-violet-600/5',
    glow: 'shadow-violet-500/20',
  },
}

// ========== 新建术语集弹窗 ==========
const createDialogOpen = ref(false)
const createStep = ref<'form' | 'preview'>('form')
const createSubmitting = ref(false)

const form = ref({
  name: '',
  description: '',
  sourceType: 'manual' as 'manual' | 'api' | 'db',
  // API 配置
  apiUrl: '',
  apiMethod: 'GET' as 'GET' | 'POST',
  apiHeaders: {} as Record<string, string>,
  apiParams: [] as Array<{ key: string; value: string; inLocation: 'query' | 'header' | 'path'; enabled: boolean }>,
  apiJsonPath: '',
  apiBody: '',
  // 测试结果
  apiTesting: false,
  apiTestResult: null as null | {
    ok: boolean
    status_code?: number
    extracted_rows?: any[]
    columns?: Array<{ name: string; type: string; label: string }>
    total_rows?: number
    error?: string
    raw?: any
  },
  // DB 配置
  dbHost: '',
  dbPort: 3306,
  dbUser: '',
  dbPassword: '',
  dbDatabase: '',
  dbCharset: 'utf8mb4',
  dbConnected: false,
  dbConnecting: false,
  dbConnectError: '',
  dbTables: [] as string[],
  dbLoadingTables: false,
  dbMode: 'table' as 'table' | 'sql',
  dbTable: '',
  dbSql: '',
  dbPreviewing: false,
  dbPreviewResult: null as null | {
    rows: any[]
    columns: Array<{ name: string; type: string; label: string }>
    total_preview: number
  },
  // 预览后数据
  previewRows: [] as any[],
  previewColumns: [] as Array<{ name: string; type: string; label: string }>,
})

function openCreate() {
  createStep.value = 'form'
  createSubmitting.value = false
  form.value = {
    name: '',
    description: '',
    sourceType: 'manual',
    apiUrl: '',
    apiMethod: 'GET',
    apiHeaders: {},
    apiParams: [],
    apiJsonPath: '',
    apiBody: '',
    apiTesting: false,
    apiTestResult: null,
    dbHost: '',
    dbPort: 3306,
    dbUser: '',
    dbPassword: '',
    dbDatabase: '',
    dbCharset: 'utf8mb4',
    dbConnected: false,
    dbConnecting: false,
    dbConnectError: '',
    dbTables: [],
    dbLoadingTables: false,
    dbMode: 'table',
    dbTable: '',
    dbSql: '',
    dbPreviewing: false,
    dbPreviewResult: null,
    previewRows: [],
    previewColumns: [],
  }
  createDialogOpen.value = true
}

function resetCreateDialog() {
  createDialogOpen.value = false
}

// 添加API参数
function addApiParam(loc: 'query' | 'header' | 'path') {
  form.value.apiParams.push({ key: '', value: '', inLocation: loc, enabled: true })
}

function removeApiParam(idx: number) {
  form.value.apiParams.splice(idx, 1)
}

// 测试API连接
async function testApi() {
  if (!form.value.apiUrl.trim()) {
    toast.warning('请填写接口地址')
    return
  }
  form.value.apiTesting = true
  form.value.apiTestResult = null
  try {
    const params = form.value.apiParams
      .filter(p => p.enabled && p.key.trim())
      .map(p => ({ key: p.key.trim(), value: p.value, in_location: p.inLocation, enabled: true }))
    const res = await kbApi.testTermBaseApi(kbId.value, {
      url: form.value.apiUrl.trim(),
      method: form.value.apiMethod,
      params,
      headers: form.value.apiHeaders,
      body: form.value.apiBody || undefined,
      json_path: form.value.apiJsonPath || undefined,
      timeout: 30,
    })
    form.value.apiTestResult = {
      ok: true,
      status_code: res.status_code,
      extracted_rows: res.extracted_rows,
      columns: res.columns,
      total_rows: res.total_rows,
      raw: res.raw_response,
    }
    if (res.columns && res.columns.length > 0) {
      form.value.previewColumns = res.columns
      form.value.previewRows = res.extracted_rows || []
      toast.success('接口测试成功', `共提取到 ${res.total_rows} 条数据`)
    } else {
      toast.warning('接口调用成功，但未能提取到数组数据，请检查数据路径配置')
    }
  } catch (e: any) {
    form.value.apiTestResult = { ok: false, error: e?.message || '测试失败' }
  } finally {
    form.value.apiTesting = false
  }
}

// 测试数据库连接
async function testDb() {
  if (!form.value.dbHost || !form.value.dbUser || !form.value.dbDatabase) {
    toast.warning('请填写完整的数据库连接信息')
    return
  }
  form.value.dbConnecting = true
  form.value.dbConnectError = ''
  form.value.dbConnected = false
  try {
    await kbApi.testTermBaseDb(kbId.value, {
      db_type: 'mysql',
      host: form.value.dbHost,
      port: form.value.dbPort,
      user: form.value.dbUser,
      password: form.value.dbPassword,
      database: form.value.dbDatabase,
      charset: form.value.dbCharset,
    })
    form.value.dbConnected = true
    toast.success('数据库连接成功')
    // 自动获取表列表
    await fetchDbTables()
  } catch (e: any) {
    form.value.dbConnectError = e?.message || '连接失败'
  } finally {
    form.value.dbConnecting = false
  }
}

// 获取数据库表列表
async function fetchDbTables() {
  form.value.dbLoadingTables = true
  try {
    const res = await kbApi.listDbTables(kbId.value, {
      db_type: 'mysql',
      host: form.value.dbHost,
      port: form.value.dbPort,
      user: form.value.dbUser,
      password: form.value.dbPassword,
      database: form.value.dbDatabase,
      charset: form.value.dbCharset,
    })
    form.value.dbTables = res.tables
  } catch (e: any) {
    toast.error(e?.message || '获取表列表失败')
  } finally {
    form.value.dbLoadingTables = false
  }
}

// 预览SQL/表数据
async function previewDb() {
  if (form.value.dbMode === 'table' && !form.value.dbTable) {
    toast.warning('请选择数据表')
    return
  }
  if (form.value.dbMode === 'sql' && !form.value.dbSql.trim()) {
    toast.warning('请输入SQL查询语句')
    return
  }
  form.value.dbPreviewing = true
  form.value.dbPreviewResult = null
  try {
    const res = await kbApi.previewSql(kbId.value, {
      db_type: 'mysql',
      host: form.value.dbHost,
      port: form.value.dbPort,
      user: form.value.dbUser,
      password: form.value.dbPassword,
      database: form.value.dbDatabase,
      charset: form.value.dbCharset,
      mode: form.value.dbMode,
      table: form.value.dbTable || undefined,
      sql_query: form.value.dbSql.trim() || undefined,
    })
    form.value.dbPreviewResult = res
    form.value.previewColumns = res.columns
    form.value.previewRows = res.rows
    toast.success('预览成功', `前 ${res.rows.length} 条数据`)
  } catch (e: any) {
    toast.error(e?.message || '预览失败')
  } finally {
    form.value.dbPreviewing = false
  }
}

// 创建术语集
async function submitCreate() {
  if (!form.value.name.trim()) {
    toast.warning('请填写术语集名称')
    return
  }

  // manual类型直接创建
  if (form.value.sourceType === 'manual') {
    createSubmitting.value = true
    try {
      const res = await kbApi.createTermBase(kbId.value, {
        name: form.value.name.trim(),
        description: form.value.description.trim() || undefined,
        source_type: 'manual',
      })
      toast.success('术语集已创建', form.value.name)
      resetCreateDialog()
      await fetchTermBases()
      // 手动类型直接进入编辑页
      router.push({ name: 'KbTermSetEditor', params: { kb_id: kbId.value, base_id: res.id } })
    } catch {
      // 拦截器处理
    } finally {
      createSubmitting.value = false
    }
    return
  }

  // api/db类型：需要先测试/预览成功，有previewColumns和previewRows才能创建
  if (form.value.previewColumns.length === 0) {
    toast.warning('请先完成数据源测试/预览，获取列结构和数据')
    return
  }

  // 对于api类型，需要拉取全量数据；这里先使用预览的前5条+创建后同步
  // 实际：api类型创建时仅保存配置，不立即导入全量（避免超时）；db类型table模式导入全量
  createSubmitting.value = true
  try {
    const sourceConfig: Record<string, any> = {}
    if (form.value.sourceType === 'api') {
      sourceConfig.url = form.value.apiUrl.trim()
      sourceConfig.method = form.value.apiMethod
      sourceConfig.headers = form.value.apiHeaders
      sourceConfig.params = form.value.apiParams.filter(p => p.key.trim())
      sourceConfig.body = form.value.apiBody
      sourceConfig.json_path = form.value.apiJsonPath
      sourceConfig.timeout = 30
    } else {
      sourceConfig.db_type = 'mysql'
      sourceConfig.host = form.value.dbHost
      sourceConfig.port = form.value.dbPort
      sourceConfig.user = form.value.dbUser
      sourceConfig.password = form.value.dbPassword
      sourceConfig.database = form.value.dbDatabase
      sourceConfig.charset = form.value.dbCharset
      sourceConfig.mode = form.value.dbMode
      sourceConfig.table = form.value.dbTable
      sourceConfig.sql_query = form.value.dbSql
    }

    // db类型table模式：在创建时不传递import_data，创建后调用sync导入全量
    // api类型和db sql模式：先创建，然后调用sync导入全量
    const res = await kbApi.createTermBase(kbId.value, {
      name: form.value.name.trim(),
      description: form.value.description.trim() || undefined,
      source_type: form.value.sourceType,
      source_config: sourceConfig,
      columns: form.value.previewColumns,
      import_data: undefined, // 统一创建后调用sync导入全量
    })
    toast.success('术语集已创建，正在同步数据...')
    resetCreateDialog()
    await fetchTermBases()

    // 创建后自动同步全量数据
    const newBaseId = res.id
    try {
      const syncRes = await kbApi.syncTermBase(kbId.value, newBaseId)
      toast.success('数据同步完成', `导入 ${syncRes.imported || 0} 条数据`)
    } catch {
      toast.info('术语集已创建，请在详情页手动同步数据')
    }
    await fetchTermBases()

    router.push({ name: 'KbTermSetEditor', params: { kb_id: kbId.value, base_id: newBaseId } })
  } catch {
    // 拦截器处理
  } finally {
    createSubmitting.value = false
  }
}

// ========== 术语集列表 ==========
async function fetchTermBases() {
  loading.value = true
  try {
    const res = await kbApi.listTermBases(kbId.value)
    termBases.value = res.items || []
  } catch {
    termBases.value = []
  } finally {
    loading.value = false
  }
}

function openEditor(base: TermBase) {
  router.push({ name: 'KbTermSetEditor', params: { kb_id: kbId.value, base_id: base.id } })
}

async function deleteBase(base: TermBase) {
  if (!await confirm(`确定删除术语集「${base.name}」？该术语集下的 ${base.term_count} 条数据也将被删除，此操作不可恢复。`)) return
  try {
    await kbApi.deleteTermBase(kbId.value, base.id)
    toast.success('已删除', base.name)
    await fetchTermBases()
  } catch {
    // 错误已由拦截器提示
  }
}

async function syncBase(base: TermBase) {
  if (!await confirm(`将从数据源重新同步「${base.name}」，现有数据将被覆盖，是否继续？`)) return
  try {
    const res = await kbApi.syncTermBase(kbId.value, base.id)
    toast.success('同步完成', `导入 ${res.imported} 条数据`)
    await fetchTermBases()
  } catch {
    // 错误已由拦截器提示
  }
}

onMounted(fetchTermBases)
</script>

<template>
  <div class="space-y-6">
    <!-- 头部 - Premium Dark-Tech 风格 -->
    <div class="flex items-center justify-between">
      <div>
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/20">
            <BookMarked class="size-6 text-primary" />
          </div>
          <div>
            <h1 class="text-2xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/80 bg-clip-text">术语库</h1>
            <p class="mt-1 text-sm text-muted-foreground">
              管理专业术语集合，支持手动录入、接口拉取、数据库直连三种方式构建术语集
            </p>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          @click="fetchTermBases"
          :disabled="loading"
          class="border-border/60 bg-card/50 backdrop-blur-sm hover:bg-accent/50 hover:border-border transition-all duration-200"
        >
          <RefreshCw class="mr-2 size-4" :class="{ 'animate-spin': loading }" />
          刷新
        </Button>
        <Button
          v-if="isEditor"
          size="sm"
          @click="openCreate"
          class="shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:-translate-y-0.5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
        >
          <Plus class="mr-2 size-4" />
          新建术语集
        </Button>
      </div>
    </div>

    <!-- 术语集列表骨架屏 -->
    <div v-if="loading" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Skeleton v-for="i in 6" :key="i" class="h-48 rounded-xl skeleton-shimmer" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="termBases.length === 0" class="py-16">
      <EmptyState
        :icon="BookMarked"
        title="暂无术语集"
        description="术语集用于管理专业术语、同义词和标准化名称，可用于结构化抽取时的术语识别与归一化"
        class="gap-4"
      >
        <Button size="sm" @click="openCreate" class="mt-2">
          <Plus class="mr-2 size-4" />
          新建术语集
        </Button>
      </EmptyState>
    </div>

    <!-- 术语集卡片列表 - Premium Dark-Tech 增强版 -->
    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="base in termBases"
        :key="base.id"
        class="group relative overflow-hidden cursor-pointer border-border/60 bg-card/80 backdrop-blur-sm
               transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]
               hover:border-primary/30 hover:shadow-xl hover:shadow-primary/10 hover:-translate-y-1"
        @click="openEditor(base)"
      >
        <!-- 渐变背景装饰 - Hover时显示 -->
        <div
          :class="[
            'absolute inset-0 bg-gradient-to-br opacity-0 group-hover:opacity-100 transition-opacity duration-500 -z-10',
            sourceTypeMeta[base.source_type]?.bgGradient || 'from-primary/5 to-primary/0'
          ]"
        />

        <!-- 顶部发光条 -->
        <div
          :class="[
            'absolute top-0 left-0 right-0 h-1 bg-gradient-to-r opacity-0 group-hover:opacity-100 transition-opacity duration-500',
            base.source_type === 'manual' ? 'from-sky-500/0 via-sky-500/50 to-sky-500/0' :
            base.source_type === 'api' ? 'from-emerald-500/0 via-emerald-500/50 to-emerald-500/0' :
            'from-violet-500/0 via-violet-500/50 to-violet-500/0'
          ]"
        />

        <CardHeader class="pb-3">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-3 min-w-0">
              <!-- 图标容器 - 带渐变和光晕 -->
              <div
                :class="[
                  'flex size-11 items-center justify-center rounded-xl shrink-0 border transition-all duration-300',
                  sourceTypeMeta[base.source_type]?.color || 'bg-muted/50 border-border',
                  'group-hover:scale-110 group-hover:shadow-lg',
                  sourceTypeMeta[base.source_type]?.glow || ''
                ]"
              >
                <component :is="sourceTypeMeta[base.source_type]?.icon || BookMarked" class="size-5" />
              </div>
              <div class="min-w-0">
                <CardTitle class="text-base truncate font-semibold group-hover:text-primary transition-colors duration-200">
                  {{ base.name }}
                </CardTitle>
                <!-- 数据源类型徽章 - 增强版 -->
                <Badge
                  :class="cn(
                    'mt-1.5 text-xs font-medium border transition-all duration-200',
                    sourceTypeMeta[base.source_type]?.color || 'bg-secondary text-secondary-foreground border-transparent',
                    'group-hover:shadow-sm'
                  )"
                >
                  {{ sourceTypeMeta[base.source_type]?.label || base.source_type }}
                </Badge>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent class="pb-4">
          <p v-if="base.description" class="mb-3 text-sm text-muted-foreground line-clamp-2 leading-relaxed">
            {{ base.description }}
          </p>

          <!-- 统计信息 -->
          <div class="flex items-center gap-4 text-xs text-muted-foreground">
            <div class="flex items-center gap-1.5">
              <div class="size-1.5 rounded-full bg-primary/60" />
              <span class="font-medium">{{ base.term_count }} 条术语</span>
            </div>
            <div v-if="base.last_synced_at" class="flex items-center gap-1.5">
              <div class="size-1.5 rounded-full bg-muted-foreground/40" />
              <span>上次同步：{{ new Date(base.last_synced_at).toLocaleDateString() }}</span>
            </div>
          </div>

          <!-- 操作按钮区域 - Hover时优雅显示 -->
          <div
            class="mt-4 flex items-center gap-1 pt-3 border-t border-border/0 group-hover:border-border/50 transition-all duration-300"
          >
            <Button
              variant="ghost"
              size="sm"
              class="h-8 px-3 text-xs font-medium opacity-0 group-hover:opacity-100 translate-y-1 group-hover:translate-y-0
                     transition-all duration-200 hover:bg-primary/10 hover:text-primary rounded-lg"
              @click.stop="openEditor(base)"
            >
              <Eye class="mr-1.5 size-3.5" />查看
            </Button>
            <Button
              v-if="isEditor && base.source_type !== 'manual'"
              variant="ghost"
              size="sm"
              class="h-8 px-3 text-xs font-medium opacity-0 group-hover:opacity-100 translate-y-1 group-hover:translate-y-0
                     transition-all duration-200 delay-50 hover:bg-emerald-500/10 hover:text-emerald-400 rounded-lg"
              @click.stop="syncBase(base)"
            >
              <RefreshCcw class="mr-1.5 size-3.5" />同步
            </Button>
            <Button
              v-if="isEditor"
              variant="ghost"
              size="sm"
              class="h-8 px-3 text-xs font-medium opacity-0 group-hover:opacity-100 translate-y-1 group-hover:translate-y-0
                     transition-all duration-200 delay-100 hover:bg-destructive/10 hover:text-destructive rounded-lg ml-auto"
              @click.stop="deleteBase(base)"
            >
              <Trash2 class="mr-1.5 size-3.5" />删除
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- ========== 新建术语集弹窗 - Premium Dark-Tech 优化 ========== -->
    <Dialog
      :open="createDialogOpen"
      title="新建术语集"
      class="max-w-3xl"
      @update:open="v => !v && resetCreateDialog()"
    >
      <div class="space-y-6 py-2 max-h-[75vh] overflow-y-auto pr-2">
        <!-- 基本信息 -->
        <div class="space-y-5">
          <div class="space-y-2.5">
            <Label class="text-sm font-medium flex items-center gap-2">
              <span>术语集名称</span>
              <span class="text-destructive">*</span>
            </Label>
            <Input
              v-model="form.name"
              placeholder="例如：检测项目库、材料牌号库"
              class="h-11 bg-card/50 border-border/60 focus:border-primary/50 focus:ring-primary/20
                     transition-all duration-200 rounded-lg"
            />
          </div>
          <div class="space-y-2.5">
            <Label class="text-sm font-medium">描述</Label>
            <Textarea
              v-model="form.description"
              placeholder="描述这个术语集的用途和内容范围"
              :rows="2"
              class="bg-card/50 border-border/60 focus:border-primary/50 focus:ring-primary/20
                     transition-all duration-200 rounded-lg resize-none"
            />
          </div>

          <!-- 数据源类型选择 - 视觉优化 -->
          <div class="space-y-3">
            <Label class="text-sm font-medium flex items-center gap-2">
              <Sparkles class="size-4 text-primary" />
              <span>数据源类型</span>
              <span class="text-destructive">*</span>
            </Label>
            <div class="grid grid-cols-3 gap-4">
              <!-- 手动录入 -->
              <button
                type="button"
                :class="[
                  'group relative flex flex-col items-center gap-3 rounded-xl border-2 p-5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]',
                  form.sourceType === 'manual'
                    ? 'border-sky-500/50 bg-gradient-to-br from-sky-500/10 to-sky-600/5 shadow-lg shadow-sky-500/15 scale-[1.02]'
                    : 'border-border/60 bg-card/30 hover:border-sky-500/30 hover:bg-sky-500/5 hover:scale-[1.01]'
                ]"
                @click="form.sourceType = 'manual'; form.apiTestResult = null; form.dbConnected = false; form.previewColumns = []; form.previewRows = []"
              >
                <div
                  :class="[
                    'flex size-12 items-center justify-center rounded-xl transition-all duration-300',
                    form.sourceType === 'manual'
                      ? 'bg-sky-500/20 text-sky-400 shadow-lg shadow-sky-500/25'
                      : 'bg-muted/50 text-muted-foreground group-hover:bg-sky-500/10 group-hover:text-sky-400'
                  ]"
                >
                  <Hand class="size-6" />
                </div>
                <span
                  :class="[
                    'text-sm font-semibold transition-colors duration-200',
                    form.sourceType === 'manual' ? 'text-sky-400' : 'text-foreground group-hover:text-sky-400'
                  ]"
                >手动录入</span>
                <span class="text-xs text-muted-foreground text-center leading-relaxed">手动添加和管理术语</span>
                <!-- 选中指示器 -->
                <div
                  v-if="form.sourceType === 'manual'"
                  class="absolute top-3 right-3 size-5 rounded-full bg-sky-500 flex items-center justify-center shadow-lg shadow-sky-500/50"
                >
                  <CheckCircle2 class="size-3.5 text-white" />
                </div>
              </button>

              <!-- 接口拉取 -->
              <button
                type="button"
                :class="[
                  'group relative flex flex-col items-center gap-3 rounded-xl border-2 p-5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]',
                  form.sourceType === 'api'
                    ? 'border-emerald-500/50 bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 shadow-lg shadow-emerald-500/15 scale-[1.02]'
                    : 'border-border/60 bg-card/30 hover:border-emerald-500/30 hover:bg-emerald-500/5 hover:scale-[1.01]'
                ]"
                @click="form.sourceType = 'api'; form.apiTestResult = null; form.previewColumns = []; form.previewRows = []"
              >
                <div
                  :class="[
                    'flex size-12 items-center justify-center rounded-xl transition-all duration-300',
                    form.sourceType === 'api'
                      ? 'bg-emerald-500/20 text-emerald-400 shadow-lg shadow-emerald-500/25'
                      : 'bg-muted/50 text-muted-foreground group-hover:bg-emerald-500/10 group-hover:text-emerald-400'
                  ]"
                >
                  <Globe class="size-6" />
                </div>
                <span
                  :class="[
                    'text-sm font-semibold transition-colors duration-200',
                    form.sourceType === 'api' ? 'text-emerald-400' : 'text-foreground group-hover:text-emerald-400'
                  ]"
                >接口拉取</span>
                <span class="text-xs text-muted-foreground text-center leading-relaxed">通过HTTP API拉取数据</span>
                <!-- 选中指示器 -->
                <div
                  v-if="form.sourceType === 'api'"
                  class="absolute top-3 right-3 size-5 rounded-full bg-emerald-500 flex items-center justify-center shadow-lg shadow-emerald-500/50"
                >
                  <CheckCircle2 class="size-3.5 text-white" />
                </div>
              </button>

              <!-- 数据库 -->
              <button
                type="button"
                :class="[
                  'group relative flex flex-col items-center gap-3 rounded-xl border-2 p-5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]',
                  form.sourceType === 'db'
                    ? 'border-violet-500/50 bg-gradient-to-br from-violet-500/10 to-violet-600/5 shadow-lg shadow-violet-500/15 scale-[1.02]'
                    : 'border-border/60 bg-card/30 hover:border-violet-500/30 hover:bg-violet-500/5 hover:scale-[1.01]'
                ]"
                @click="form.sourceType = 'db'; form.dbConnected = false; form.previewColumns = []; form.previewRows = []"
              >
                <div
                  :class="[
                    'flex size-12 items-center justify-center rounded-xl transition-all duration-300',
                    form.sourceType === 'db'
                      ? 'bg-violet-500/20 text-violet-400 shadow-lg shadow-violet-500/25'
                      : 'bg-muted/50 text-muted-foreground group-hover:bg-violet-500/10 group-hover:text-violet-400'
                  ]"
                >
                  <DbIcon class="size-6" />
                </div>
                <span
                  :class="[
                    'text-sm font-semibold transition-colors duration-200',
                    form.sourceType === 'db' ? 'text-violet-400' : 'text-foreground group-hover:text-violet-400'
                  ]"
                >数据库</span>
                <span class="text-xs text-muted-foreground text-center leading-relaxed">直连MySQL数据库</span>
                <!-- 选中指示器 -->
                <div
                  v-if="form.sourceType === 'db'"
                  class="absolute top-3 right-3 size-5 rounded-full bg-violet-500 flex items-center justify-center shadow-lg shadow-violet-500/50"
                >
                  <CheckCircle2 class="size-3.5 text-white" />
                </div>
              </button>
            </div>
          </div>
        </div>

        <Separator class="bg-border/60" />

        <!-- 手动录入提示 - 视觉优化 -->
        <div v-if="form.sourceType === 'manual'" class="rounded-xl bg-gradient-to-r from-sky-500/10 via-sky-500/5 to-transparent border border-sky-500/20 p-4">
          <div class="flex items-center gap-3">
            <div class="flex size-8 items-center justify-center rounded-lg bg-sky-500/20 shrink-0">
              <CheckCircle2 class="size-5 text-sky-400" />
            </div>
            <div>
              <p class="text-sm font-medium text-foreground">准备就绪</p>
              <p class="text-sm text-muted-foreground mt-0.5">创建后将直接进入术语集内部，您可以手动添加和管理术语条目。</p>
            </div>
          </div>
        </div>

        <!-- API 配置 - 视觉优化 -->
        <div v-if="form.sourceType === 'api'" class="space-y-5 rounded-xl border border-border/60 bg-card/30 p-5 backdrop-blur-sm">
          <h3 class="font-semibold flex items-center gap-2.5 text-base">
            <div class="p-1.5 rounded-lg bg-emerald-500/15">
              <Globe class="size-4 text-emerald-400" />
            </div>
            <span>接口配置</span>
          </h3>

          <div class="grid grid-cols-[100px_1fr] gap-4 items-start">
            <Label class="pt-2.5 text-sm font-medium">请求方法</Label>
            <Select
              :model-value="form.apiMethod"
              :options="[{ value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' }]"
              @update:model-value="(v: any) => form.apiMethod = v"
              class="bg-card/50 border-border/60 rounded-lg h-11"
            />

            <Label class="pt-2.5 text-sm font-medium">接口地址 <span class="text-destructive">*</span></Label>
            <Input
              v-model="form.apiUrl"
              placeholder="https://api.example.com/terms"
              class="bg-card/50 border-border/60 focus:border-primary/50 focus:ring-primary/20 rounded-lg h-11"
            />

            <Label class="pt-2.5 text-sm font-medium">数据路径</Label>
            <Input
              v-model="form.apiJsonPath"
              placeholder="可选，如 data.list（返回结果中数组所在的JSON路径）"
              class="bg-card/50 border-border/60 focus:border-primary/50 focus:ring-primary/20 rounded-lg h-11"
            />
          </div>

          <!-- 请求参数 -->
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <Label class="text-sm font-medium">请求参数</Label>
              <div class="flex gap-1 flex-wrap">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  class="h-8 text-xs rounded-lg hover:bg-emerald-500/10 hover:text-emerald-400 transition-colors"
                  @click="addApiParam('path')"
                >+ 路径参数</Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  class="h-8 text-xs rounded-lg hover:bg-emerald-500/10 hover:text-emerald-400 transition-colors"
                  @click="addApiParam('query')"
                >+ Query参数</Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  class="h-8 text-xs rounded-lg hover:bg-emerald-500/10 hover:text-emerald-400 transition-colors"
                  @click="addApiParam('header')"
                >+ 请求头</Button>
              </div>
            </div>
            <div v-if="form.apiParams.length === 0" class="text-sm text-muted-foreground py-3 px-4 rounded-lg bg-muted/30">
              未配置参数
            </div>
            <div v-for="(p, idx) in form.apiParams" :key="idx" class="flex items-center gap-2.5">
              <Checkbox
                v-model="p.enabled"
                class="data-[state=checked]:bg-emerald-500 data-[state=checked]:border-emerald-500"
              />
              <Badge
                :class="cn(
                  'text-xs w-16 shrink-0 justify-center font-medium rounded-lg border',
                  p.inLocation === 'path' ? 'bg-sky-500/15 text-sky-400 border-sky-500/30' :
                  p.inLocation === 'query' ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' :
                  'bg-violet-500/15 text-violet-400 border-violet-500/30'
                )"
              >{{ p.inLocation }}</Badge>
              <Input
                v-model="p.key"
                placeholder="参数名"
                class="flex-1 bg-card/50 border-border/60 focus:border-primary/50 h-9 rounded-lg"
              />
              <Input
                v-model="p.value"
                placeholder="参数值"
                class="flex-1 bg-card/50 border-border/60 focus:border-primary/50 h-9 rounded-lg"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                class="size-9 shrink-0 rounded-lg hover:bg-destructive/10 hover:text-destructive transition-colors"
                @click="removeApiParam(idx)"
              >
                <X class="size-4" />
              </Button>
            </div>
          </div>

          <!-- POST Body -->
          <div v-if="form.apiMethod === 'POST'" class="space-y-2.5">
            <Label class="text-sm font-medium">请求体 (JSON)</Label>
            <Textarea
              v-model="form.apiBody"
              placeholder='{"key": "value"}'
              :rows="3"
              class="font-mono text-xs bg-card/50 border-border/60 focus:border-primary/50 rounded-lg resize-none"
            />
          </div>

          <!-- 测试按钮 & 状态 -->
          <div class="flex items-center gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              @click="testApi"
              :disabled="form.apiTesting"
              class="h-10 px-4 rounded-lg border-emerald-500/30 bg-emerald-500/5 hover:bg-emerald-500/10 hover:border-emerald-500/50
                     text-emerald-400 transition-all duration-200"
            >
              <Play v-if="!form.apiTesting" class="mr-2 size-4" />
              <Loader2 v-else class="mr-2 size-4 animate-spin" />
              测试接口
            </Button>
            <!-- 状态指示器 - 优化版 -->
            <div
              v-if="form.apiTestResult?.ok"
              class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20"
            >
              <CheckCircle2 class="size-4 text-emerald-400" />
              <span class="text-sm font-medium text-emerald-400">测试成功</span>
              <span class="text-xs text-muted-foreground">({{ form.apiTestResult.total_rows }} 条数据)</span>
            </div>
            <div
              v-else-if="form.apiTestResult && !form.apiTestResult.ok"
              class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-destructive/10 border border-destructive/20"
            >
              <XCircle class="size-4 text-destructive" />
              <span class="text-sm font-medium text-destructive">{{ form.apiTestResult.error }}</span>
            </div>
          </div>

          <!-- 测试结果预览 -->
          <div v-if="form.apiTestResult?.ok && form.previewColumns.length > 0" class="space-y-2.5">
            <Label class="text-sm font-medium">返回结果预览（前5条）</Label>
            <div class="overflow-auto rounded-xl border border-border/60 bg-card/30 max-h-56 backdrop-blur-sm">
              <table class="w-full text-sm">
                <thead class="bg-muted/50 sticky top-0 backdrop-blur-sm">
                  <tr>
                    <th v-for="col in form.previewColumns" :key="col.name" class="px-3 py-2.5 text-left font-medium text-muted-foreground">
                      {{ col.label }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in form.previewRows.slice(0, 5)" :key="ri" class="border-t border-border/40 hover:bg-muted/30 transition-colors">
                    <td v-for="col in form.previewColumns" :key="col.name" class="px-3 py-2.5 truncate max-w-[180px]">
                      {{ row[col.name] ?? '' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- 数据库配置 - 视觉优化 -->
        <div v-if="form.sourceType === 'db'" class="space-y-5 rounded-xl border border-border/60 bg-card/30 p-5 backdrop-blur-sm">
          <h3 class="font-semibold flex items-center gap-2.5 text-base">
            <div class="p-1.5 rounded-lg bg-violet-500/15">
              <DbIcon class="size-4 text-violet-400" />
            </div>
            <span>MySQL 数据库连接</span>
          </h3>

          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-2.5">
              <Label class="text-sm font-medium">主机地址 <span class="text-destructive">*</span></Label>
              <Input
                v-model="form.dbHost"
                placeholder="localhost 或 127.0.0.1"
                :disabled="form.dbConnected"
                class="bg-card/50 border-border/60 focus:border-primary/50 h-11 rounded-lg disabled:opacity-60"
              />
            </div>
            <div class="space-y-2.5">
              <Label class="text-sm font-medium">端口</Label>
              <Input
                v-model.number="form.dbPort"
                type="number"
                placeholder="3306"
                :disabled="form.dbConnected"
                class="bg-card/50 border-border/60 focus:border-primary/50 h-11 rounded-lg disabled:opacity-60"
              />
            </div>
            <div class="space-y-2.5">
              <Label class="text-sm font-medium">用户名 <span class="text-destructive">*</span></Label>
              <Input
                v-model="form.dbUser"
                placeholder="root"
                :disabled="form.dbConnected"
                class="bg-card/50 border-border/60 focus:border-primary/50 h-11 rounded-lg disabled:opacity-60"
              />
            </div>
            <div class="space-y-2.5">
              <Label class="text-sm font-medium">密码</Label>
              <Input
                v-model="form.dbPassword"
                type="password"
                placeholder="密码"
                :disabled="form.dbConnected"
                class="bg-card/50 border-border/60 focus:border-primary/50 h-11 rounded-lg disabled:opacity-60"
              />
            </div>
            <div class="space-y-2.5">
              <Label class="text-sm font-medium">数据库名 <span class="text-destructive">*</span></Label>
              <Input
                v-model="form.dbDatabase"
                placeholder="my_database"
                :disabled="form.dbConnected"
                class="bg-card/50 border-border/60 focus:border-primary/50 h-11 rounded-lg disabled:opacity-60"
              />
            </div>
            <div class="space-y-2.5">
              <Label class="text-sm font-medium">字符集</Label>
              <Input
                v-model="form.dbCharset"
                placeholder="utf8mb4"
                :disabled="form.dbConnected"
                class="bg-card/50 border-border/60 focus:border-primary/50 h-11 rounded-lg disabled:opacity-60"
              />
            </div>
          </div>

          <!-- 测试连接按钮 & 状态 -->
          <div class="flex items-center gap-3 pt-1">
            <Button
              v-if="!form.dbConnected"
              type="button"
              variant="outline"
              size="sm"
              @click="testDb"
              :disabled="form.dbConnecting"
              class="h-10 px-4 rounded-lg border-violet-500/30 bg-violet-500/5 hover:bg-violet-500/10 hover:border-violet-500/50
                     text-violet-400 transition-all duration-200"
            >
              <Play v-if="!form.dbConnecting" class="mr-2 size-4" />
              <Loader2 v-else class="mr-2 size-4 animate-spin" />
              测试连接
            </Button>
            <Button
              v-else
              type="button"
              variant="outline"
              size="sm"
              @click="form.dbConnected = false; form.dbPreviewResult = null; form.previewColumns = []"
              class="h-10 px-4 rounded-lg"
            >
              重新连接
            </Button>
            <!-- 连接成功指示器 -->
            <div
              v-if="form.dbConnected"
              class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20"
            >
              <CheckCircle2 class="size-4 text-emerald-400" />
              <span class="text-sm font-medium text-emerald-400">连接成功</span>
            </div>
            <div
              v-if="form.dbConnectError"
              class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-destructive/10 border border-destructive/20"
            >
              <XCircle class="size-4 text-destructive" />
              <span class="text-sm font-medium text-destructive">{{ form.dbConnectError }}</span>
            </div>
          </div>

          <!-- 连接成功后：选择表或SQL -->
          <div v-if="form.dbConnected" class="space-y-4 border-t border-border/60 pt-5">
            <Tabs v-model="form.dbMode" class="w-full">
              <TabsList class="grid w-full grid-cols-2 bg-muted/50 p-1 rounded-lg h-11">
                <TabsTrigger
                  value="table"
                  class="rounded-md data-[state=active]:bg-card data-[state=active]:shadow-sm transition-all duration-200"
                >选择表格</TabsTrigger>
                <TabsTrigger
                  value="sql"
                  class="rounded-md data-[state=active]:bg-card data-[state=active]:shadow-sm transition-all duration-200"
                >SQL查询</TabsTrigger>
              </TabsList>
              <TabsContent value="table" class="space-y-3 pt-4">
                <div class="space-y-2.5">
                  <Label class="text-sm font-medium">选择数据表 <span class="text-destructive">*</span></Label>
                  <Select
                    :model-value="form.dbTable"
                    :options="form.dbTables.map(t => ({ value: t, label: t }))"
                    :placeholder="form.dbLoadingTables ? '加载中...' : '选择一个数据表'"
                    @update:model-value="(v: any) => form.dbTable = v"
                    class="bg-card/50 border-border/60 h-11 rounded-lg"
                  />
                </div>
              </TabsContent>
              <TabsContent value="sql" class="space-y-3 pt-4">
                <div class="space-y-2.5">
                  <Label class="text-sm font-medium">SQL查询语句 <span class="text-destructive">*</span></Label>
                  <Textarea
                    v-model="form.dbSql"
                    placeholder="SELECT * FROM my_table WHERE ..."
                    :rows="4"
                    class="font-mono text-xs bg-card/50 border-border/60 focus:border-primary/50 rounded-lg resize-none"
                  />
                  <p class="text-xs text-muted-foreground flex items-center gap-1.5">
                    <div class="size-1 rounded-full bg-muted-foreground/50" />
                    将自动 LIMIT 5 预览，创建时将查询所有结果
                  </p>
                </div>
              </TabsContent>
            </Tabs>

            <Button
              type="button"
              variant="outline"
              size="sm"
              @click="previewDb"
              :disabled="form.dbPreviewing"
              class="h-10 px-4 rounded-lg"
            >
              <Eye v-if="!form.dbPreviewing" class="mr-2 size-4" />
              <Loader2 v-else class="mr-2 size-4 animate-spin" />
              预览数据
            </Button>

            <!-- 预览结果 -->
            <div v-if="form.dbPreviewResult" class="space-y-2.5">
              <Label class="text-sm font-medium">数据预览（前5条）</Label>
              <div class="overflow-auto rounded-xl border border-border/60 bg-card/30 max-h-56 backdrop-blur-sm">
                <table class="w-full text-sm">
                  <thead class="bg-muted/50 sticky top-0 backdrop-blur-sm">
                    <tr>
                      <th v-for="col in form.previewColumns" :key="col.name" class="px-3 py-2.5 text-left font-medium text-muted-foreground">
                        {{ col.label }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, ri) in form.previewRows.slice(0, 5)" :key="ri" class="border-t border-border/40 hover:bg-muted/30 transition-colors">
                      <td v-for="col in form.previewColumns" :key="col.name" class="px-3 py-2.5 truncate max-w-[180px]">
                        {{ row[col.name] ?? '' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 弹窗底部按钮 -->
      <div class="mt-6 flex justify-end gap-3 border-t border-border/60 pt-5">
        <Button
          variant="ghost"
          @click="resetCreateDialog"
          class="h-11 px-5 rounded-lg hover:bg-muted/50 transition-colors"
        >取消</Button>
        <Button
          @click="submitCreate"
          :disabled="createSubmitting || (form.sourceType !== 'manual' && form.previewColumns.length === 0)"
          class="h-11 px-6 rounded-lg shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:-translate-y-0.5
                 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]
                 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none disabled:shadow-none"
        >
          <Loader2 v-if="createSubmitting" class="mr-2 size-4 animate-spin" />
          {{ form.sourceType === 'manual' ? '创建术语集' : '创建并导入数据' }}
        </Button>
      </div>
    </Dialog>
  </div>
</template>
