<script setup lang="ts">
/**
 * 知识库配置中心（重构版）
 *
 * 模块：
 *   1. 服务配置（Accordion折叠面板，每个服务可单独校验/保存）
 *   2. 一键诊断（校验所有服务连接状态）
 *   3. 备份恢复（创建/下载/删除/恢复备份）
 *
 * 临时隐藏：领域类别、Hook管理、模板应用（后端API保留）
 *
 * 权限：viewer 可查看；admin+ 可修改
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Settings,
  ShieldCheck,
  Loader2,
  RefreshCw,
  Save,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Upload,
  Download,
  DatabaseBackup,
  FileArchive,
  ChevronDown,
  HardDrive,
  Search,
  Network,
  Database,
  Brain,
  FileText,
  Sparkles,
  LayoutGrid,
  Hash,
  PlayCircle,
  Trash2,
  Cpu,
  KeyRound,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbPermission } from '@/composables/useKbPermission'
import type {
  ServiceConfigSection,
  ServiceCheckResult,
  ServicesDiagnoseResult,
  KbBackup,
} from '@/api/types'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { PageHeader } from '@/components/ui/page-header'
import { Progress } from '@/components/ui/progress'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Alert } from '@/components/ui/alert'
import { confirm } from '@/composables/useConfirm'

const route = useRoute()
const kbId = computed(() => route.params.kb_id as string)
const { isAdmin } = useKbPermission()

const iconMap: Record<string, any> = {
  Settings,
  HardDrive,
  Search,
  Network,
  Database,
  Brain,
  FileText,
  Sparkles,
  LayoutGrid,
  Hash,
  PlayCircle,
  Cpu,
}

// ===== 服务配置 =====
const servicesLoading = ref(true)
const services = ref<ServiceConfigSection[]>([])
const serviceStatuses = ref<Record<string, ServiceCheckResult>>({})
const expandedService = ref<string | null>(null)
const validatingService = ref<string | null>(null)
const savingService = ref<string | null>(null)
const serviceEdits = ref<Record<string, Record<string, unknown>>>({})
const lastDiagnoseTime = ref<string | null>(null)

async function fetchServices() {
  servicesLoading.value = true
  try {
    const res = await kbApi.listServiceConfigs(kbId.value)
    services.value = res.services
    serviceEdits.value = {}
    for (const svc of services.value) {
      serviceEdits.value[svc.name] = {}
      for (const f of svc.fields) {
        serviceEdits.value[svc.name][f.key] = f.value
      }
      if (svc.last_status) {
        serviceStatuses.value[svc.name] = svc.last_status
      }
    }
    lastDiagnoseTime.value = res.last_diagnose?.checked_at || null
    if (res.last_diagnose && Object.keys(serviceStatuses.value).length > 0) {
      diagnoseResult.value = {
        kb_id: kbId.value,
        total: res.last_diagnose.total,
        ok_count: res.last_diagnose.ok_count,
        error_count: res.last_diagnose.error_count,
        warning_count: res.last_diagnose.warning_count,
        services: Object.values(serviceStatuses.value),
        checked_at: res.last_diagnose.checked_at || '',
      }
    }
  } catch {
    services.value = []
  } finally {
    servicesLoading.value = false
  }
}

function toggleService(name: string) {
  expandedService.value = expandedService.value === name ? null : name
}

function updateServiceField(svcName: string, key: string, value: unknown) {
  if (!serviceEdits.value[svcName]) {
    serviceEdits.value[svcName] = {}
  }
  serviceEdits.value[svcName][key] = value
}

async function validateService(name: string) {
  validatingService.value = name
  try {
    const result = await kbApi.validateService(kbId.value, name)
    serviceStatuses.value[name] = result
    if (result.status === 'ok') {
      toast.success(`${result.display_name} 校验通过`, result.message)
    } else if (result.status === 'warning') {
      toast.warning(`${result.display_name} 警告`, result.message)
    } else {
      toast.error(`${result.display_name} 校验失败`, result.message)
    }
  } catch {
    serviceStatuses.value[name] = {
      name,
      display_name: services.value.find(s => s.name === name)?.display_name || name,
      status: 'error',
      message: '校验请求失败',
      response_time_ms: 0,
    }
  } finally {
    validatingService.value = null
  }
}

async function saveServiceConfig(name: string) {
  savingService.value = name
  try {
    await kbApi.updateServiceConfig(kbId.value, name, serviceEdits.value[name] || {})
    toast.success('配置已保存', `${services.value.find(s => s.name === name)?.display_name} 配置更新成功`)
    await fetchServices()
  } catch {
  } finally {
    savingService.value = null
  }
}

function getServiceStatus(name: string): 'ok' | 'error' | 'warning' | 'unknown' {
  return serviceStatuses.value[name]?.status || 'unknown'
}

function getStatusBadgeVariant(status: string): 'default' | 'destructive' | 'secondary' | 'outline' {
  switch (status) {
    case 'ok': return 'default'
    case 'error': return 'destructive'
    case 'warning': return 'secondary'
    default: return 'outline'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'ok': return '正常'
    case 'error': return '异常'
    case 'warning': return '警告'
    default: return '未校验'
  }
}

function getStatusColorClass(status: string): string {
  switch (status) {
    case 'ok': return 'status-ok'
    case 'error': return 'status-error'
    case 'warning': return 'status-warning'
    default: return 'status-unknown'
  }
}

// ===== 一键诊断 =====
const diagnosing = ref(false)
const diagnoseResult = ref<ServicesDiagnoseResult | null>(null)
const diagnoseProgress = ref(0)
const currentDiagnosingService = ref<string | null>(null)

async function runDiagnose() {
  diagnosing.value = true
  diagnoseProgress.value = 0
  diagnoseResult.value = null
  serviceStatuses.value = {}
  currentDiagnosingService.value = null

  try {
    const result = await kbApi.diagnoseAllServices(kbId.value)
    diagnoseResult.value = result
    diagnoseProgress.value = 100
    for (const svc of result.services) {
      serviceStatuses.value[svc.name] = svc
    }
    if (result.error_count === 0 && result.warning_count === 0) {
      toast.success('诊断完成', `所有 ${result.ok_count} 个服务正常`)
    } else if (result.error_count === 0) {
      toast.warning('诊断完成', `${result.ok_count} 个正常，${result.warning_count} 个警告`)
    } else {
      toast.error('诊断完成', `${result.ok_count} 个正常，${result.error_count} 个异常，${result.warning_count} 个警告`)
    }
  } catch {
    toast.error('诊断失败', '请稍后重试')
  } finally {
    diagnosing.value = false
    currentDiagnosingService.value = null
  }
}

// ===== 备份恢复 =====
const backups = ref<KbBackup[]>([])
const backupsLoading = ref(false)
const backupCreating = ref(false)
const backupProgress = ref(0)
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
  backupProgress.value = 0
  try {
    const progressTimer = setInterval(() => {
      if (backupProgress.value < 90) {
        backupProgress.value += Math.random() * 15
      }
    }, 300)
    await kbApi.createBackup(kbId.value)
    clearInterval(progressTimer)
    backupProgress.value = 100
    toast.success('备份成功', '知识库数据已打包为ZIP')
    await fetchBackups()
  } catch {
  } finally {
    backupCreating.value = false
    setTimeout(() => { backupProgress.value = 0 }, 2000)
  }
}

async function deleteBackup(backup: KbBackup) {
  if (!await confirm(`确定删除备份「${backup.file_name}」？此操作不可撤销。`)) return
  try {
    await kbApi.deleteBackup(kbId.value, backup.id)
    toast.success('已删除', backup.file_name)
    await fetchBackups()
  } catch {
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
  if (!await confirm('恢复将覆盖当前 KB 的配置，文档/Schema/术语按去重跳过。确定继续？')) return
  restoring.value = true
  try {
    const stats = await kbApi.restoreBackup(kbId.value, restoreFile.value)
    toast.success('恢复完成', `文档+${stats.documents} Schema+${stats.schemas} 术语+${stats.terms}`)
    restoreFile.value = null
    await fetchServices()
  } catch {
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

// ===== 服务配置 =====

onMounted(() => {
  fetchServices()
  fetchBackups()
})
</script>

<template>
  <div class="config-page">
    <PageHeader title="配置中心" description="服务配置 · 一键诊断 · 备份恢复" />

    <!-- 一键诊断区域 -->
    <Card class="mb-6 diagnose-card hover-lift">
      <CardContent class="p-5">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div class="flex items-center gap-4">
            <div class="icon-wrapper icon-primary">
              <ShieldCheck class="size-6" :stroke-width="1.5" />
            </div>
            <div>
              <h3 class="text-base font-semibold">服务健康诊断</h3>
              <p class="text-sm text-muted-foreground mt-0.5">一键检查所有服务连接状态</p>
              <p v-if="lastDiagnoseTime" class="text-xs text-muted-foreground/70 mt-1">
                上次诊断: {{ formatTime(lastDiagnoseTime) }}
              </p>
            </div>
          </div>
          <div class="flex items-center gap-4">
            <div v-if="diagnoseResult" class="flex items-center gap-2">
              <Badge v-if="diagnoseResult.ok_count > 0" variant="default" class="status-badge badge-ok text-xs px-3 py-1">
                <CheckCircle2 class="size-3 mr-1" :stroke-width="2" />
                {{ diagnoseResult.ok_count }} 正常
              </Badge>
              <Badge v-if="diagnoseResult.warning_count > 0" variant="secondary" class="status-badge badge-warning text-xs px-3 py-1">
                <AlertTriangle class="size-3 mr-1" :stroke-width="2" />
                {{ diagnoseResult.warning_count }} 警告
              </Badge>
              <Badge v-if="diagnoseResult.error_count > 0" variant="destructive" class="status-badge badge-error text-xs px-3 py-1">
                <XCircle class="size-3 mr-1" :stroke-width="2" />
                {{ diagnoseResult.error_count }} 异常
              </Badge>
            </div>
            <Button
              @click="runDiagnose"
              :disabled="diagnosing"
              size="default"
              class="btn-glow-primary px-5"
            >
              <Loader2 v-if="diagnosing" class="size-4 animate-spin mr-2" :stroke-width="2" />
              <PlayCircle v-else class="size-4 mr-2" :stroke-width="2" />
              {{ diagnosing ? '诊断中...' : '一键诊断' }}
            </Button>
          </div>
        </div>
        <Progress v-if="diagnosing" :value="diagnoseProgress" class="mt-5 h-1.5 progress-glow" />
      </CardContent>
    </Card>

    <!-- 诊断结果摘要 -->
    <Transition name="fade-slide">
      <Alert v-if="diagnoseResult && diagnoseResult.error_count > 0" variant="destructive" class="mb-6 alert-glow" title="服务连接异常" :icon="AlertTriangle">
        有 {{ diagnoseResult.error_count }} 个服务连接异常，请展开对应服务卡片查看详情并修复配置。
      </Alert>
    </Transition>

    <!-- 服务配置 Accordion -->
    <div v-if="servicesLoading" class="space-y-4">
      <Skeleton v-for="i in 5" :key="i" class="h-20 w-full rounded-xl skeleton-card" />
    </div>
    <div v-else class="space-y-4">
      <Card
        v-for="svc in services"
        :key="svc.name"
        :class="`service-card overflow-hidden transition-all duration-300 ${expandedService === svc.name ? 'service-card-expanded' : ''}`"
      >
        <button
          class="w-full flex items-center justify-between p-5 text-left service-card-header group"
          @click="toggleService(svc.name)"
        >
          <div class="flex items-center gap-4 min-w-0">
            <div class="relative">
              <div class="icon-wrapper" :class="`icon-${getServiceStatus(svc.name)}`">
                <component :is="iconMap[svc.icon || 'Settings']" class="size-5" :stroke-width="1.8" />
              </div>
              <span
                class="status-indicator absolute -top-0.5 -right-0.5"
                :class="getStatusColorClass(getServiceStatus(svc.name))"
              ></span>
            </div>
            <div class="min-w-0">
              <div class="flex items-center gap-3">
                <span class="font-semibold text-base">{{ svc.display_name }}</span>
                <Badge
                  :variant="getStatusBadgeVariant(getServiceStatus(svc.name))"
                  class="text-xs px-2 py-0.5"
                  :class="`badge-${getServiceStatus(svc.name)}`"
                >
                  {{ getStatusText(getServiceStatus(svc.name)) }}
                </Badge>
              </div>
              <p class="text-sm text-muted-foreground truncate mt-0.5">{{ svc.description }}</p>
            </div>
          </div>
          <div class="flex items-center gap-3 shrink-0 ml-4">
            <Button
              size="sm"
              variant="ghost"
              :class="`h-8 px-3 text-xs action-btn ${validatingService === svc.name ? 'btn-validating' : ''}`"
              :disabled="validatingService === svc.name"
              @click.stop="validateService(svc.name)"
            >
              <Loader2 v-if="validatingService === svc.name" class="size-3.5 animate-spin mr-1.5" :stroke-width="2" />
              <RefreshCw v-else class="size-3.5 mr-1.5" :stroke-width="2" />
              校验
            </Button>
            <div class="chevron-wrapper p-1.5 rounded-lg">
              <ChevronDown
                class="size-5 text-muted-foreground transition-all duration-300"
                :class="{ 'rotate-180 text-primary': expandedService === svc.name }"
                :stroke-width="2"
              />
            </div>
          </div>
        </button>

        <Transition name="accordion">
          <div v-show="expandedService === svc.name" class="accordion-content">
            <Separator class="opacity-50" />
            <div class="p-5 space-y-5 service-card-content">
              <div v-if="serviceStatuses[svc.name]" class="status-message p-4 rounded-xl">
                <component
                  :is="serviceStatuses[svc.name].status === 'ok' ? CheckCircle2 : serviceStatuses[svc.name].status === 'warning' ? AlertTriangle : XCircle"
                  class="size-5 shrink-0 mt-0.5"
                  :class="{
                    'text-success': serviceStatuses[svc.name].status === 'ok',
                    'text-warning': serviceStatuses[svc.name].status === 'warning',
                    'text-destructive': serviceStatuses[svc.name].status === 'error',
                  }"
                  :stroke-width="2"
                />
                <div class="ml-3">
                  <p class="font-medium" :class="{
                    'text-success': serviceStatuses[svc.name].status === 'ok',
                    'text-warning': serviceStatuses[svc.name].status === 'warning',
                    'text-destructive': serviceStatuses[svc.name].status === 'error',
                  }">
                    {{ serviceStatuses[svc.name].message }}
                  </p>
                  <p v-if="serviceStatuses[svc.name].response_time_ms > 0" class="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                    <span class="inline-block w-1.5 h-1.5 rounded-full bg-current opacity-50"></span>
                    响应时间: {{ serviceStatuses[svc.name].response_time_ms.toFixed(0) }}ms
                  </p>
                </div>
              </div>

              <Alert v-if="getServiceStatus(svc.name) === 'error'" class="alert-warning" title="服务连接异常" :icon="AlertTriangle">
                <span class="text-sm">该服务连接异常，配置修改可能无法生效，请先确保服务正常运行。</span>
              </Alert>

              <div class="form-section">
                <div class="form-section-header mb-4">
                  <div class="h-px flex-1 bg-gradient-to-r from-transparent via-border to-transparent"></div>
                  <span class="px-4 text-xs font-medium text-muted-foreground uppercase tracking-wider">配置参数</span>
                  <div class="h-px flex-1 bg-gradient-to-r from-transparent via-border to-transparent"></div>
                </div>
                <div class="grid gap-5 sm:grid-cols-2">
                  <div v-for="field in svc.fields" :key="field.key" class="form-field group">
                    <Label :for="`${svc.name}-${field.key}`" class="text-sm font-medium flex items-center gap-1.5 mb-2">
                      <span class="field-dot w-1.5 h-1.5 rounded-full bg-primary/60 group-hover:bg-primary transition-colors"></span>
                      {{ field.label }}
                      <span v-if="field.required" class="text-destructive">*</span>
                    </Label>
                    <Input
                      v-if="field.type === 'string'"
                      :id="`${svc.name}-${field.key}`"
                      :value="String(serviceEdits[svc.name]?.[field.key] ?? '')"
                      @input="(e: Event) => updateServiceField(svc.name, field.key, (e.target as HTMLInputElement).value)"
                      :placeholder="field.placeholder"
                      :disabled="!isAdmin"
                      class="h-10 text-sm input-premium"
                    />
                    <Input
                      v-else-if="field.type === 'number'"
                      :id="`${svc.name}-${field.key}`"
                      type="number"
                      :value="Number(serviceEdits[svc.name]?.[field.key] ?? 0)"
                      @input="(e: Event) => updateServiceField(svc.name, field.key, Number((e.target as HTMLInputElement).value))"
                      :placeholder="field.placeholder"
                      :disabled="!isAdmin"
                      class="h-10 text-sm input-premium"
                    />
                    <Input
                      v-else-if="field.type === 'password'"
                      :id="`${svc.name}-${field.key}`"
                      type="password"
                      :value="String(serviceEdits[svc.name]?.[field.key] ?? '')"
                      @input="(e: Event) => updateServiceField(svc.name, field.key, (e.target as HTMLInputElement).value)"
                      :placeholder="field.placeholder"
                      :disabled="!isAdmin"
                      class="h-10 text-sm input-premium"
                    />
                    <div v-else-if="field.type === 'boolean'" class="flex items-center gap-3 h-10 px-3 rounded-lg bg-muted/30">
                      <Switch
                        :id="`${svc.name}-${field.key}`"
                        :checked="!!serviceEdits[svc.name][field.key]"
                        :disabled="!isAdmin"
                        @update:checked="(v: boolean) => serviceEdits[svc.name][field.key] = v"
                        class="switch-premium"
                      />
                      <Label :for="`${svc.name}-${field.key}`" class="text-sm cursor-pointer select-none">
                        <span :class="serviceEdits[svc.name][field.key] ? 'text-success font-medium' : 'text-muted-foreground'">
                          {{ serviceEdits[svc.name][field.key] ? '已启用' : '已禁用' }}
                        </span>
                      </Label>
                    </div>
                    <p v-if="field.description" class="text-xs text-muted-foreground/80 mt-1.5 leading-relaxed">{{ field.description }}</p>
                  </div>
                </div>
              </div>

              <div v-if="isAdmin" class="flex justify-end pt-3 border-t border-border/50">
                <Button
                  size="default"
                  class="btn-glow-primary px-6"
                  :disabled="savingService === svc.name"
                  @click="saveServiceConfig(svc.name)"
                >
                  <Loader2 v-if="savingService === svc.name" class="size-4 animate-spin mr-2" :stroke-width="2" />
                  <Save v-else class="size-4 mr-2" :stroke-width="2" />
                  保存配置
                </Button>
              </div>
            </div>
          </div>
        </Transition>
      </Card>
    </div>

    <!-- 备份恢复区域 -->
    <Separator class="my-8 opacity-30" />
    <div class="space-y-5 backup-section">
      <div class="flex items-center gap-3">
        <div class="icon-wrapper icon-primary">
          <DatabaseBackup class="size-5" :stroke-width="1.8" />
        </div>
        <div>
          <h2 class="text-xl font-bold">备份恢复</h2>
          <p class="text-sm text-muted-foreground mt-0.5">保护您的知识库数据安全</p>
        </div>
      </div>

      <div class="grid gap-5 md:grid-cols-2">
        <Card class="backup-card hover-lift">
          <CardContent class="p-5">
            <div class="flex items-start justify-between gap-4">
              <div class="flex-1">
                <div class="flex items-center gap-2 mb-2">
                  <div class="icon-wrapper-sm icon-success">
                    <FileArchive class="size-4" :stroke-width="2" />
                  </div>
                  <h3 class="text-base font-semibold">数据备份</h3>
                </div>
                <p class="text-sm text-muted-foreground leading-relaxed">
                  打包 KB 配置、文档元数据、抽取结果、术语、Schema、领域配置为 ZIP 归档文件
                </p>
              </div>
            </div>
            <div class="mt-5">
              <Button v-if="isAdmin" :disabled="backupCreating" @click="createBackup" class="w-full btn-glow-success">
                <Loader2 v-if="backupCreating" class="size-4 animate-spin mr-2" :stroke-width="2" />
                <FileArchive v-else class="size-4 mr-2" :stroke-width="2" />
                {{ backupCreating ? '备份中...' : '立即备份' }}
              </Button>
              <Progress v-if="backupCreating || backupProgress > 0" :value="backupProgress" class="mt-4 h-1.5 progress-glow" />
            </div>
          </CardContent>
        </Card>

        <Card v-if="isAdmin" class="backup-card hover-lift">
          <CardContent class="p-5">
            <div class="flex items-start justify-between gap-4">
              <div class="flex-1">
                <div class="flex items-center gap-2 mb-2">
                  <div class="icon-wrapper-sm icon-warning">
                    <Upload class="size-4" :stroke-width="2" />
                  </div>
                  <h3 class="text-base font-semibold">数据恢复</h3>
                </div>
                <p class="text-sm text-muted-foreground leading-relaxed">
                  上传备份 ZIP 恢复数据。文档/Schema/术语按去重跳过，配置将被覆盖
                </p>
              </div>
            </div>
            <div class="mt-5 space-y-3">
              <div class="file-input-wrapper">
                <input
                  type="file"
                  accept=".zip"
                  class="text-sm file-input-custom w-full"
                  @change="onRestoreFileChange"
                />
              </div>
              <div v-if="restoreFile" class="flex items-center gap-2 p-2 rounded-lg bg-primary/5 text-sm text-primary">
                <FileArchive class="size-4 shrink-0" :stroke-width="2" />
                <span class="truncate">{{ restoreFile.name }}</span>
              </div>
              <Button :disabled="!restoreFile || restoring" size="default" class="w-full btn-glow-warning" @click="restoreBackup">
                <Loader2 v-if="restoring" class="size-4 animate-spin mr-2" :stroke-width="2" />
                <DatabaseBackup v-else class="size-4 mr-2" :stroke-width="2" />
                {{ restoring ? '恢复中...' : '开始恢复' }}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card class="backup-list-card">
        <CardContent class="p-5">
          <div class="mb-4 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <h3 class="text-base font-semibold">备份记录</h3>
              <Badge v-if="backups.length > 0" variant="secondary" class="text-xs">{{ backups.length }}</Badge>
            </div>
            <Button variant="ghost" size="sm" :disabled="backupsLoading" @click="fetchBackups" class="refresh-btn">
              <RefreshCw class="size-4 mr-1.5" :class="{ 'animate-spin': backupsLoading }" :stroke-width="2" />
              刷新
            </Button>
          </div>
          <div v-if="backupsLoading" class="flex justify-center py-12">
            <Loader2 class="size-8 animate-spin text-primary/70" :stroke-width="1.5" />
          </div>
          <div v-else-if="backups.length === 0" class="py-12 text-center empty-state">
            <div class="icon-wrapper icon-muted mx-auto mb-4">
              <DatabaseBackup class="size-10" :stroke-width="1.5" />
            </div>
            <p class="text-sm text-muted-foreground">暂无备份记录</p>
            <p class="text-xs text-muted-foreground/60 mt-1">点击"立即备份"创建您的第一个备份</p>
          </div>
          <TransitionGroup name="list" tag="div" v-else class="space-y-3">
            <div
              v-for="b in backups"
              :key="b.id"
              class="backup-item flex items-center justify-between rounded-xl p-4 transition-all duration-200"
            >
              <div class="min-w-0 flex-1 flex items-center gap-4">
                <div class="icon-wrapper-sm" :class="b.status === 'completed' ? 'icon-success' : 'icon-error'">
                  <FileArchive class="size-5" :stroke-width="1.8" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="truncate text-sm font-semibold">{{ b.file_name }}</span>
                    <Badge
                      :variant="b.status === 'completed' ? 'default' : 'destructive'"
                      class="text-[10px] px-2 py-0"
                      :class="b.status === 'completed' ? 'badge-ok' : 'badge-error'"
                    >
                      {{ b.status === 'completed' ? '成功' : '失败' }}
                    </Badge>
                  </div>
                  <div class="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span class="flex items-center gap-1">
                      <HardDrive class="size-3" :stroke-width="2" />
                      {{ formatFileSize(b.file_size) }}
                    </span>
                    <span class="flex items-center gap-1">
                      <span class="w-1 h-1 rounded-full bg-current opacity-40"></span>
                      {{ formatTime(b.created_at) }}
                    </span>
                    <span v-if="b.item_counts" class="flex items-center gap-1">
                      <span class="w-1 h-1 rounded-full bg-current opacity-40"></span>
                      文档{{ b.item_counts.documents || 0 }} / Schema{{ b.item_counts.schemas || 0 }} / 术语{{ b.item_counts.terms || 0 }}
                    </span>
                  </div>
                </div>
              </div>
              <div v-if="isAdmin" class="flex shrink-0 items-center gap-1 ml-4">
                <Button variant="ghost" size="sm" class="h-9 w-9 p-0 icon-btn action-btn" @click="downloadBackup(b)" title="下载">
                  <Download class="size-4" :stroke-width="2" />
                </Button>
                <Button variant="ghost" size="sm" class="h-9 w-9 p-0 icon-btn text-destructive action-btn-danger" @click="deleteBackup(b)" title="删除">
                  <Trash2 class="size-4" :stroke-width="2" />
                </Button>
              </div>
            </div>
          </TransitionGroup>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.config-page {
  position: relative;
}

.service-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  transition: all 0.3s var(--ease-out);
  position: relative;
  overflow: hidden;
}

.service-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--primary)/0.03 0%, transparent 50%);
  opacity: 0;
  transition: opacity 0.3s var(--ease-out);
  pointer-events: none;
}

.service-card:hover {
  border-color: var(--primary)/30;
  box-shadow: 0 8px 30px -10px var(--primary)/0.15, var(--shadow-md);
  transform: translateY(-2px);
}

.service-card:hover::before {
  opacity: 1;
}

.service-card-expanded {
  border-color: var(--primary)/40;
  box-shadow: 0 12px 40px -15px var(--primary)/0.2, var(--shadow-lg);
}

.service-card-expanded::before {
  opacity: 1;
}

.service-card-header {
  background: transparent;
  transition: background 0.2s var(--ease-out);
}

.service-card-header:hover {
  background: var(--muted)/30;
}

.icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--muted);
  color: var(--muted-foreground);
  transition: all 0.3s var(--ease-out);
  position: relative;
}

.icon-wrapper-sm {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--muted);
  color: var(--muted-foreground);
  transition: all 0.3s var(--ease-out);
  flex-shrink: 0;
}

.icon-primary {
  background: linear-gradient(135deg, var(--primary)/15, var(--primary)/5);
  color: var(--primary);
  box-shadow: inset 0 0 0 1px var(--primary)/20;
}

.icon-ok, .icon-success {
  background: linear-gradient(135deg, var(--success)/15, var(--success)/5);
  color: var(--success);
  box-shadow: inset 0 0 0 1px var(--success)/20;
}

.icon-error {
  background: linear-gradient(135deg, var(--destructive)/15, var(--destructive)/5);
  color: var(--destructive);
  box-shadow: inset 0 0 0 1px var(--destructive)/20;
}

.icon-warning {
  background: linear-gradient(135deg, var(--warning)/15, var(--warning)/5);
  color: var(--warning);
  box-shadow: inset 0 0 0 1px var(--warning)/20;
}

.icon-muted {
  background: var(--muted);
  color: var(--muted-foreground);
}

.service-card:hover .icon-wrapper {
  transform: scale(1.05);
}

.status-indicator {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--card);
  box-shadow: 0 0 0 0 currentColor;
}

.status-ok {
  background: var(--success);
  color: var(--success);
  animation: pulse-ok 2s ease-in-out infinite;
}

.status-error {
  background: var(--destructive);
  color: var(--destructive);
  animation: pulse-error 1.5s ease-in-out infinite;
}

.status-warning {
  background: var(--warning);
  color: var(--warning);
  animation: pulse-warning 1.8s ease-in-out infinite;
}

.status-unknown {
  background: var(--muted-foreground);
  color: var(--muted-foreground);
  opacity: 0.5;
}

@keyframes pulse-ok {
  0%, 100% {
    box-shadow: 0 0 0 0 var(--success)/0.4;
  }
  50% {
    box-shadow: 0 0 0 6px var(--success)/0;
  }
}

@keyframes pulse-error {
  0%, 100% {
    box-shadow: 0 0 0 0 var(--destructive)/0.5;
  }
  50% {
    box-shadow: 0 0 0 8px var(--destructive)/0;
  }
}

@keyframes pulse-warning {
  0%, 100% {
    box-shadow: 0 0 0 0 var(--warning)/0.4;
  }
  50% {
    box-shadow: 0 0 0 6px var(--warning)/0;
  }
}

.chevron-wrapper {
  background: var(--muted)/50;
  transition: all 0.2s var(--ease-out);
}

.service-card:hover .chevron-wrapper {
  background: var(--muted);
}

.action-btn {
  border-radius: var(--radius-md);
  transition: all 0.2s var(--ease-out);
}

.action-btn:hover:not(:disabled) {
  background: var(--primary)/10;
  color: var(--primary);
}

.action-btn-danger:hover:not(:disabled) {
  background: var(--destructive)/10;
  color: var(--destructive);
}

.btn-validating {
  background: var(--primary)/10;
  color: var(--primary);
}

.btn-glow-primary {
  position: relative;
  background: linear-gradient(135deg, var(--primary), var(--primary-400));
  color: var(--primary-foreground);
  border: none;
  border-radius: var(--radius-lg);
  font-weight: 600;
  transition: all 0.3s var(--ease-out);
  box-shadow: 0 4px 14px var(--primary)/25, 0 2px 6px var(--primary)/15;
}

.btn-glow-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px var(--primary)/0.35, 0 4px 12px var(--primary)/0.2;
}

.btn-glow-primary:active:not(:disabled) {
  transform: translateY(0);
}

.btn-glow-success {
  position: relative;
  background: linear-gradient(135deg, var(--success), oklch(0.55 0.13 150));
  color: var(--success-foreground);
  border: none;
  border-radius: var(--radius-lg);
  font-weight: 600;
  transition: all 0.3s var(--ease-out);
  box-shadow: 0 4px 14px var(--success)/0.25;
}

.btn-glow-success:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px var(--success)/0.35;
}

.btn-glow-warning {
  position: relative;
  background: linear-gradient(135deg, var(--warning), oklch(0.63 0.14 70));
  color: var(--warning-foreground);
  border: none;
  border-radius: var(--radius-lg);
  font-weight: 600;
  transition: all 0.3s var(--ease-out);
  box-shadow: 0 4px 14px var(--warning)/0.25;
}

.btn-glow-warning:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px var(--warning)/0.35;
}

.accordion-content {
  overflow: hidden;
}

.accordion-enter-active,
.accordion-leave-active {
  transition: all 0.3s var(--ease-out);
  overflow: hidden;
}

.accordion-enter-from,
.accordion-leave-to {
  opacity: 0;
  max-height: 0;
}

.accordion-enter-to,
.accordion-leave-from {
  opacity: 1;
  max-height: 1000px;
}

.service-card-content {
  background: linear-gradient(180deg, var(--muted)/20 0%, transparent 100%);
}

.status-message {
  display: flex;
  align-items: flex-start;
  background: var(--muted)/30;
  border-radius: var(--radius-lg);
}

.alert-warning {
  background: linear-gradient(135deg, var(--warning)/10, var(--warning)/5);
  border-color: var(--warning)/30;
}

.form-section-header {
  display: flex;
  align-items: center;
}

.form-field {
  transition: all 0.2s var(--ease-out);
}

.form-field:hover {
  transform: translateX(2px);
}

.input-premium {
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  transition: all 0.2s var(--ease-out);
}

.input-premium:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary)/0.1, 0 2px 8px var(--primary)/0.1;
}

.input-premium:disabled {
  background: var(--muted)/50;
  opacity: 0.7;
}

.switch-premium {
  transition: all 0.2s var(--ease-out);
}

.status-badge {
  border-radius: var(--radius-full);
  font-weight: 500;
}

.badge-ok {
  background: linear-gradient(135deg, var(--success)/20, var(--success)/10);
  color: var(--success);
  border: 1px solid var(--success)/20;
}

.badge-error {
  background: linear-gradient(135deg, var(--destructive)/20, var(--destructive)/10);
  color: var(--destructive);
  border: 1px solid var(--destructive)/20;
}

.badge-warning {
  background: linear-gradient(135deg, var(--warning)/20, var(--warning)/10);
  color: var(--warning);
  border: 1px solid var(--warning)/20;
}

.diagnose-card {
  background: linear-gradient(135deg, var(--card) 0%, var(--card) 100%);
  border: 1px solid var(--border);
  position: relative;
  overflow: hidden;
}

.diagnose-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--primary), transparent);
  opacity: 0.6;
}

.alert-glow {
  animation: alert-glow-pulse 2s ease-in-out infinite;
}

@keyframes alert-glow-pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 var(--destructive)/0.2;
  }
  50% {
    box-shadow: 0 0 0 4px var(--destructive)/0;
  }
}

.progress-glow {
  background: var(--muted);
  border-radius: 999px;
  overflow: hidden;
}

.progress-glow :deep(> div) {
  background: linear-gradient(90deg, var(--primary), var(--primary-400));
  box-shadow: 0 0 10px var(--primary)/0.5;
  border-radius: 999px;
}

.skeleton-card {
  border-radius: var(--radius-xl);
}

.backup-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  transition: all 0.3s var(--ease-out);
  position: relative;
  overflow: hidden;
}

.backup-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--primary)/0.02 0%, transparent 50%);
  pointer-events: none;
  border-radius: inherit;
}

.file-input-wrapper {
  position: relative;
}

.file-input-custom {
  padding: 8px 12px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  background: var(--muted)/20;
  cursor: pointer;
  transition: all 0.2s var(--ease-out);
}

.file-input-custom:hover {
  border-color: var(--primary)/50;
  background: var(--primary)/5;
}

.file-input-custom::file-selector-button {
  margin-right: 12px;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--foreground);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s var(--ease-out);
}

.file-input-custom:hover::file-selector-button {
  background: var(--primary);
  color: var(--primary-foreground);
  border-color: var(--primary);
}

.backup-list-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
}

.refresh-btn {
  border-radius: var(--radius-md);
  transition: all 0.2s var(--ease-out);
}

.refresh-btn:hover:not(:disabled) {
  background: var(--muted);
}

.empty-state {
  opacity: 0.8;
}

.backup-item {
  background: var(--muted)/20;
  border: 1px solid transparent;
}

.backup-item:hover {
  background: var(--muted)/40;
  border-color: var(--primary)/20;
  transform: translateX(4px);
}

.icon-btn {
  border-radius: var(--radius-md);
  transition: all 0.2s var(--ease-out);
}

.icon-btn:hover:not(:disabled) {
  background: var(--primary)/10;
  color: var(--primary);
  transform: scale(1.05);
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s var(--ease-out);
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(-10px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.list-enter-active,
.list-leave-active {
  transition: all 0.3s var(--ease-out);
}

.list-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

.list-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

.list-move {
  transition: transform 0.3s var(--ease-out);
}

.dark .btn-glow-primary {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-400));
  box-shadow: 0 4px 14px var(--primary)/0.35, 0 2px 6px var(--primary)/0.2, inset 0 1px 0 var(--primary-300)/20;
}

.dark .btn-glow-primary:hover:not(:disabled) {
  box-shadow: 0 8px 24px var(--primary)/0.45, 0 4px 12px var(--primary)/0.25;
}

.dark .service-card:hover {
  box-shadow: 0 8px 30px -10px var(--primary)/0.25, var(--shadow-lg);
}

.dark .service-card-expanded {
  box-shadow: 0 12px 40px -15px var(--primary)/0.3, var(--shadow-xl);
}

.dark .diagnose-card::before {
  opacity: 0.8;
}

.dark .input-premium {
  background: var(--card);
}

.dark .backup-item:hover {
  background: var(--muted)/30;
}
</style>
