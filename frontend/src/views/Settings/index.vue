<script setup lang="ts">
/**
 * 系统设置
 *
 * 5 个 Tab：外观 / 账户 / 模型 / 存储 / 系统信息
 * - 外观：主题模式、布局偏好（本地存储）
 * - 账户：当前用户信息卡片，跳转个人中心
 * - 模型：对接 /system/health/deep，展示 LLM/Embedding 等模型健康状态
 * - 存储：对接 /system/health/deep，展示 PostgreSQL/Redis/MinIO/Milvus/Nebula 状态
 * - 系统信息：对接 /system/info，展示应用版本、环境、组件版本
 */
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  Palette,
  Sun,
  Moon,
  Monitor,
  Cpu,
  Check,
  AlertTriangle,
  Info,
  User as UserIcon,
  HardDrive,
  Bell,
  Activity,
  Boxes,
  FileText,
  Scan,
  Network,
  Sparkles,
  Server,
  RefreshCw,
  Loader2,
  ChevronRight,
} from 'lucide-vue-next'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { systemApi, type HealthCheck } from '@/api/modules/system'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { toast } from '@/components/ui/toast'

const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

// ---------- 主题 ----------
type ThemeMode = 'light' | 'dark' | 'system'

const themeOptions: Array<{ value: ThemeMode; label: string; icon: typeof Sun }> = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
  { value: 'system', label: '跟随系统', icon: Monitor },
]

function setTheme(mode: ThemeMode) {
  appStore.setThemeMode(mode)
  toast.success('主题已切换', `当前主题：${themeOptions.find((t) => t.value === mode)?.label}`)
}

// ---------- 偏好（仅本地） ----------
const compactMode = ref(localStorage.getItem('compact-mode') === 'true')
const motionReduced = ref(localStorage.getItem('motion-reduced') === 'true')
const notificationsEnabled = ref(localStorage.getItem('notifications') !== 'false')

function updateCompactMode(value: boolean) {
  compactMode.value = value
  localStorage.setItem('compact-mode', String(value))
  toast.success('设置已保存', `紧凑模式：${value ? '开启' : '关闭'}`)
}

function updateMotionReduced(value: boolean) {
  motionReduced.value = value
  localStorage.setItem('motion-reduced', String(value))
  document.documentElement.classList.toggle('reduce-motion', value)
  toast.success('设置已保存', `动效：${value ? '减弱' : '正常'}`)
}

function updateNotifications(value: boolean) {
  notificationsEnabled.value = value
  localStorage.setItem('notifications', String(value))
  toast.success('设置已保存', `通知：${value ? '开启' : '关闭'}`)
}

// ---------- 深度健康检查 ----------
const healthLoading = ref(false)
const deepHealth = ref<Awaited<ReturnType<typeof systemApi.deepHealth>> | null>(null)
const systemInfo = ref<Awaited<ReturnType<typeof systemApi.info>> | null>(null)

const statusConfig: Record<string, { label: string; variant: 'success' | 'warning' | 'danger' | 'secondary'; icon: typeof Check }> = {
  healthy: { label: '健康', variant: 'success', icon: Check },
  degraded: { label: '降级', variant: 'warning', icon: AlertTriangle },
  unhealthy: { label: '异常', variant: 'danger', icon: AlertTriangle },
  unavailable: { label: '不可用', variant: 'danger', icon: AlertTriangle },
  unknown: { label: '未知', variant: 'secondary', icon: Info },
}

function getStatusInfo(status: string) {
  return statusConfig[status] || statusConfig.unknown
}

const overallStatus = computed(() => {
  if (!deepHealth.value) return statusConfig.unknown
  return statusConfig[deepHealth.value.status] || statusConfig.unknown
})

// 模型相关检查项
const modelChecks = computed(() => {
  if (!deepHealth.value) return []
  const checks = deepHealth.value.checks
  return [
    { key: 'llm', label: 'LLM', value: '抽取/问答大语言模型', check: checks.llm },
    { key: 'embedding', label: 'Embedding', value: '向量编码模型', check: checks.embedding },
  ].filter((m) => m.check)
})

// 存储相关检查项
const storageChecks = computed(() => {
  if (!deepHealth.value) return []
  const checks = deepHealth.value.checks
  return [
    { key: 'postgres', label: 'PostgreSQL', value: '主数据库（含 RLS 行级安全）', check: checks.postgres },
    { key: 'redis', label: 'Redis', value: '缓存与任务队列', check: checks.redis },
    { key: 'minio', label: 'MinIO', value: '对象存储（文档原文件）', check: checks.minio },
    { key: 'milvus', label: 'Milvus', value: '向量数据库', check: checks.milvus },
    { key: 'nebula', label: 'NebulaGraph', value: '知识图谱数据库', check: checks.nebula },
  ].filter((s) => s.check)
})

async function fetchHealth() {
  healthLoading.value = true
  try {
    const [health, info] = await Promise.all([systemApi.deepHealth(), systemApi.info()])
    deepHealth.value = health
    systemInfo.value = info
  } catch {
    // 错误已由拦截器提示
  } finally {
    healthLoading.value = false
  }
}

function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

onMounted(() => {
  // 应用 reduce-motion 类
  if (motionReduced.value) {
    document.documentElement.classList.add('reduce-motion')
  }
  // 拉取健康状态
  fetchHealth()
})
</script>

<template>
  <div>
    <PageHeader title="系统设置" description="管理应用偏好与系统状态">
      <template #actions>
        <Button variant="outline" size="sm" :disabled="healthLoading" @click="fetchHealth">
          <RefreshCw class="size-4" :class="{ 'animate-spin': healthLoading }" :stroke-width="1.5" />
          刷新状态
        </Button>
      </template>
    </PageHeader>

    <Tabs default-value="appearance" class="w-full">
      <TabsList class="mb-4">
        <TabsTrigger value="appearance">
          <Palette class="size-3.5" :stroke-width="1.5" />
          外观
        </TabsTrigger>
        <TabsTrigger value="account">
          <UserIcon class="size-3.5" :stroke-width="1.5" />
          账户
        </TabsTrigger>
        <TabsTrigger value="models">
          <Cpu class="size-3.5" :stroke-width="1.5" />
          模型
        </TabsTrigger>
        <TabsTrigger value="storage">
          <HardDrive class="size-3.5" :stroke-width="1.5" />
          存储
        </TabsTrigger>
        <TabsTrigger value="system">
          <Server class="size-3.5" :stroke-width="1.5" />
          系统信息
        </TabsTrigger>
        <TabsTrigger value="notifications">
          <Bell class="size-3.5" :stroke-width="1.5" />
          通知
        </TabsTrigger>
      </TabsList>

      <!-- 外观设置 -->
      <TabsContent value="appearance">
        <div class="space-y-4">
          <Card>
            <CardContent class="p-6">
              <div class="mb-4">
                <h3 class="text-sm font-medium text-foreground">主题模式</h3>
                <p class="text-xs text-muted-foreground">选择应用的色彩主题</p>
              </div>
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <button
                  v-for="opt in themeOptions"
                  :key="opt.value"
                  type="button"
                  :class="[
                    'flex items-center gap-3 rounded-md border p-3 transition-colors',
                    appStore.themeMode === opt.value
                      ? 'border-primary bg-primary/5 text-foreground'
                      : 'border-border bg-background text-muted-foreground hover:bg-muted/40',
                  ]"
                  @click="setTheme(opt.value)"
                >
                  <component :is="opt.icon" class="size-5" :stroke-width="1.5" />
                  <div class="flex-1 text-left">
                    <p class="text-sm font-medium">{{ opt.label }}</p>
                  </div>
                  <Check v-if="appStore.themeMode === opt.value" class="size-4 text-primary" :stroke-width="1.5" />
                </button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent class="space-y-4 p-6">
              <div>
                <h3 class="text-sm font-medium text-foreground">布局偏好</h3>
                <p class="text-xs text-muted-foreground">调整界面密度与动效</p>
              </div>
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>紧凑模式</Label>
                  <p class="text-xs text-muted-foreground">减小间距与字号以容纳更多内容</p>
                </div>
                <Switch :checked="compactMode" @update:checked="updateCompactMode" />
              </div>
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>减弱动效</Label>
                  <p class="text-xs text-muted-foreground">减少过渡动画以提升性能</p>
                </div>
                <Switch :checked="motionReduced" @update:checked="updateMotionReduced" />
              </div>
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>侧边栏折叠</Label>
                  <p class="text-xs text-muted-foreground">折叠侧边栏以扩展内容区</p>
                </div>
                <Switch :checked="appStore.sidebarCollapsed" @update:checked="appStore.toggleSidebar" />
              </div>
            </CardContent>
          </Card>
        </div>
      </TabsContent>

      <!-- 账户设置 -->
      <TabsContent value="account">
        <Card>
          <CardContent class="p-6">
            <div class="flex items-start gap-4">
              <Avatar class="size-16">
                <AvatarFallback class="bg-primary text-primary-foreground text-xl">
                  {{ (authStore.user?.username || 'U').slice(0, 2).toUpperCase() }}
                </AvatarFallback>
              </Avatar>
              <div class="flex-1 space-y-4">
                <div>
                  <h3 class="text-lg font-medium text-foreground">{{ authStore.user?.username || '-' }}</h3>
                  <p class="text-sm text-muted-foreground">{{ authStore.user?.email || '-' }}</p>
                </div>
                <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div class="rounded-md border border-border bg-muted/20 p-3">
                    <p class="text-[10px] uppercase tracking-wide text-muted-foreground">角色</p>
                    <Badge
                      :variant="authStore.isSuperuser ? 'warning' : 'secondary'"
                      class="mt-1 text-[10px]"
                    >
                      {{ authStore.isSuperuser ? '超级管理员' : '普通用户' }}
                    </Badge>
                  </div>
                  <div class="rounded-md border border-border bg-muted/20 p-3">
                    <p class="text-[10px] uppercase tracking-wide text-muted-foreground">创建时间</p>
                    <p class="mt-1 font-mono text-xs text-foreground">{{ formatTime(authStore.user?.created_at) }}</p>
                  </div>
                  <div v-if="authStore.user?.full_name" class="rounded-md border border-border bg-muted/20 p-3">
                    <p class="text-[10px] uppercase tracking-wide text-muted-foreground">姓名</p>
                    <p class="mt-1 text-sm text-foreground">{{ authStore.user.full_name }}</p>
                  </div>
                  <div v-if="authStore.user?.department" class="rounded-md border border-border bg-muted/20 p-3">
                    <p class="text-[10px] uppercase tracking-wide text-muted-foreground">部门</p>
                    <p class="mt-1 text-sm text-foreground">{{ authStore.user.department }}</p>
                  </div>
                </div>
                <div class="flex gap-2 border-t border-border pt-4">
                  <Button variant="outline" size="sm" @click="router.push('/profile')">
                    <UserIcon class="size-4" :stroke-width="1.5" />
                    前往个人中心
                    <ChevronRight class="size-4" :stroke-width="1.5" />
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- 模型状态 -->
      <TabsContent value="models">
        <Card>
          <CardContent class="p-6">
            <div class="mb-4 flex items-center justify-between">
              <div>
                <h3 class="text-sm font-medium text-foreground">AI 模型状态</h3>
                <p class="text-xs text-muted-foreground">由后端 /system/health/deep 实时返回</p>
              </div>
              <Badge :variant="overallStatus.variant" class="text-[10px]">
                <component :is="overallStatus.icon" class="mr-0.5 size-3" :stroke-width="1.5" />
                {{ overallStatus.label }}
              </Badge>
            </div>

            <div v-if="healthLoading" class="flex items-center justify-center py-8">
              <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
            </div>

            <div v-else-if="modelChecks.length === 0" class="py-8 text-center text-sm text-muted-foreground">
              暂无模型健康数据，请确认后端服务已启动
            </div>

            <div v-else class="space-y-2">
              <div
                v-for="item in modelChecks"
                :key="item.key"
                class="flex items-center gap-3 rounded-md border border-border bg-muted/20 p-3"
              >
                <div class="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <component :is="item.key === 'llm' ? Sparkles : Boxes" class="size-4" :stroke-width="1.5" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs text-muted-foreground">{{ item.label }}</p>
                  <p class="truncate font-mono text-sm text-foreground">{{ item.check?.model || item.value }}</p>
                  <p v-if="item.check?.endpoint" class="truncate text-[10px] text-muted-foreground">{{ item.check.endpoint }}</p>
                </div>
                <div class="flex flex-col items-end gap-1">
                  <Badge :variant="getStatusInfo(item.check?.status || '').variant" class="text-[10px]">
                    <component :is="getStatusInfo(item.check?.status || '').icon" class="mr-0.5 size-3" :stroke-width="1.5" />
                    {{ getStatusInfo(item.check?.status || '').label }}
                  </Badge>
                  <span v-if="item.check?.latency_ms !== null && item.check?.latency_ms !== undefined" class="text-[10px] text-muted-foreground">
                    {{ formatLatency(item.check?.latency_ms) }}
                  </span>
                </div>
              </div>
            </div>

            <div v-if="deepHealth" class="mt-4 flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-3">
              <Info class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
              <p class="text-xs text-muted-foreground">
                最后检查：{{ formatTime(deepHealth.timestamp) }}。模型状态由后端配置，如需修改请调整后端 .env 与 vLLM 启动参数。
              </p>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- 存储状态 -->
      <TabsContent value="storage">
        <Card>
          <CardContent class="p-6">
            <div class="mb-4">
              <h3 class="text-sm font-medium text-foreground">存储服务状态</h3>
              <p class="text-xs text-muted-foreground">六层隔离架构中的各存储依赖</p>
            </div>

            <div v-if="healthLoading" class="flex items-center justify-center py-8">
              <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
            </div>

            <div v-else-if="storageChecks.length === 0" class="py-8 text-center text-sm text-muted-foreground">
              暂无存储健康数据
            </div>

            <div v-else class="space-y-2">
              <div
                v-for="item in storageChecks"
                :key="item.key"
                class="flex items-center gap-3 rounded-md border border-border bg-muted/20 p-3"
              >
                <div class="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <component :is="item.key === 'postgres' ? Server : item.key === 'redis' ? Activity : item.key === 'minio' ? HardDrive : item.key === 'milvus' ? Boxes : Network" class="size-4" :stroke-width="1.5" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs text-muted-foreground">{{ item.label }}</p>
                  <p class="truncate text-sm text-foreground">{{ item.value }}</p>
                  <p v-if="item.check?.host" class="truncate font-mono text-[10px] text-muted-foreground">{{ item.check.host }}</p>
                  <p v-if="item.check?.error" class="truncate text-[10px] text-danger">{{ item.check.error }}</p>
                </div>
                <Badge :variant="getStatusInfo(item.check?.status || '').variant" class="text-[10px]">
                  <component :is="getStatusInfo(item.check?.status || '').icon" class="mr-0.5 size-3" :stroke-width="1.5" />
                  {{ getStatusInfo(item.check?.status || '').label }}
                </Badge>
              </div>
            </div>

            <div v-if="deepHealth" class="mt-4 flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-3">
              <Info class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
              <p class="text-xs text-muted-foreground">
                整体状态：<strong :class="overallStatus.variant === 'success' ? 'text-success' : overallStatus.variant === 'danger' ? 'text-danger' : 'text-warning'">{{ overallStatus.label }}</strong>
                · 检查时间 {{ formatTime(deepHealth.timestamp) }}
              </p>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- 系统信息 -->
      <TabsContent value="system">
        <Card>
          <CardContent class="p-6">
            <div class="mb-4">
              <h3 class="text-sm font-medium text-foreground">系统信息</h3>
              <p class="text-xs text-muted-foreground">应用版本与运行环境</p>
            </div>

            <div v-if="healthLoading && !systemInfo" class="flex items-center justify-center py-8">
              <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
            </div>

            <div v-else-if="systemInfo" class="space-y-4">
              <div class="grid grid-cols-2 gap-3">
                <div class="rounded-md border border-border bg-muted/20 p-3">
                  <p class="text-[10px] uppercase tracking-wide text-muted-foreground">应用名称</p>
                  <p class="mt-1 text-sm font-medium text-foreground">{{ systemInfo.app_name }}</p>
                </div>
                <div class="rounded-md border border-border bg-muted/20 p-3">
                  <p class="text-[10px] uppercase tracking-wide text-muted-foreground">版本</p>
                  <p class="mt-1 font-mono text-sm text-foreground">{{ systemInfo.version }}</p>
                </div>
                <div class="rounded-md border border-border bg-muted/20 p-3">
                  <p class="text-[10px] uppercase tracking-wide text-muted-foreground">环境</p>
                  <Badge :variant="systemInfo.env === 'production' ? 'success' : 'warning'" class="mt-1 text-[10px]">
                    {{ systemInfo.env }}
                  </Badge>
                </div>
                <div class="rounded-md border border-border bg-muted/20 p-3">
                  <p class="text-[10px] uppercase tracking-wide text-muted-foreground">调试模式</p>
                  <Badge :variant="systemInfo.debug ? 'danger' : 'secondary'" class="mt-1 text-[10px]">
                    {{ systemInfo.debug ? '开启' : '关闭' }}
                  </Badge>
                </div>
                <div class="rounded-md border border-border bg-muted/20 p-3">
                  <p class="text-[10px] uppercase tracking-wide text-muted-foreground">Python 版本</p>
                  <p class="mt-1 font-mono text-xs text-foreground">{{ systemInfo.python }}</p>
                </div>
                <div class="rounded-md border border-border bg-muted/20 p-3">
                  <p class="text-[10px] uppercase tracking-wide text-muted-foreground">平台</p>
                  <p class="mt-1 font-mono text-xs text-foreground">{{ systemInfo.platform }}</p>
                </div>
              </div>

              <div v-if="systemInfo.components && Object.keys(systemInfo.components).length > 0">
                <p class="mb-2 text-xs font-medium text-muted-foreground">组件版本</p>
                <div class="space-y-1">
                  <div
                    v-for="(ver, name) in systemInfo.components"
                    :key="name"
                    class="flex items-center justify-between rounded-md bg-muted/20 px-3 py-1.5 text-xs"
                  >
                    <span class="font-mono text-muted-foreground">{{ name }}</span>
                    <span class="font-mono text-foreground">{{ ver }}</span>
                  </div>
                </div>
              </div>

              <div v-if="systemInfo.features && Object.keys(systemInfo.features).length > 0">
                <p class="mb-2 text-xs font-medium text-muted-foreground">功能开关</p>
                <div class="flex flex-wrap gap-1.5">
                  <Badge
                    v-for="(enabled, name) in systemInfo.features"
                    :key="name"
                    :variant="enabled ? 'success' : 'secondary'"
                    class="text-[10px]"
                  >
                    {{ name }}: {{ enabled ? 'ON' : 'OFF' }}
                  </Badge>
                </div>
              </div>

              <p class="text-[10px] text-muted-foreground">最后更新：{{ formatTime(systemInfo.timestamp) }}</p>
            </div>

            <div v-else class="py-8 text-center text-sm text-muted-foreground">
              暂无系统信息，请确认后端服务已启动
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- 通知设置 -->
      <TabsContent value="notifications">
        <Card>
          <CardContent class="space-y-4 p-6">
            <div>
              <h3 class="text-sm font-medium text-foreground">通知偏好</h3>
              <p class="text-xs text-muted-foreground">控制各类通知的显示</p>
            </div>
            <div class="flex items-center justify-between">
              <div class="space-y-1">
                <Label>启用通知</Label>
                <p class="text-xs text-muted-foreground">开启后将在任务完成、错误等事件发生时显示提示</p>
              </div>
              <Switch :checked="notificationsEnabled" @update:checked="updateNotifications" />
            </div>
            <div class="border-t border-border pt-4">
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>任务完成通知</Label>
                  <p class="text-xs text-muted-foreground">文档解析、索引构建等任务完成时提示</p>
                </div>
                <Switch :checked="notificationsEnabled" disabled />
              </div>
            </div>
            <div class="border-t border-border pt-4">
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>错误通知</Label>
                  <p class="text-xs text-muted-foreground">任务失败或系统错误时提示</p>
                </div>
                <Switch :checked="notificationsEnabled" disabled />
              </div>
            </div>
            <div class="mt-4 flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-3">
              <Info class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
              <p class="text-xs text-muted-foreground">
                通知系统使用浏览器原生 Notification API，首次使用需要在浏览器中授权。
              </p>
            </div>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>
