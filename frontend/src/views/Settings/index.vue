<script setup lang="ts">
import { ref, onMounted } from 'vue'
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
} from 'lucide-vue-next'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { toast } from '@/components/ui/toast'

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

// ---------- 模型状态（只读） ----------
interface ModelStatus {
  key: string
  label: string
  value: string
  status: 'healthy' | 'warning' | 'error' | 'unknown'
  icon: typeof Cpu
}

const modelStatuses = ref<ModelStatus[]>([
  { key: 'llm', label: 'LLM', value: 'Qwen3.5-9B（vLLM）', status: 'unknown', icon: Sparkles },
  { key: 'embedding', label: 'Embedding', value: 'BAAI/bge-m3', status: 'unknown', icon: Boxes },
  { key: 'reranker', label: 'Reranker', value: 'bge-reranker-v2-m3', status: 'unknown', icon: Activity },
  { key: 'ocr', label: 'OCR', value: 'PaddleOCR-VL', status: 'unknown', icon: Scan },
  { key: 'layout', label: '版面分析', value: 'MinerU + MinerU-Popo', status: 'unknown', icon: FileText },
  { key: 'kg', label: '实体抽取', value: 'OneKE / DeepKE-LLM', status: 'unknown', icon: Network },
])

const statusConfig = {
  healthy: { label: '健康', variant: 'success' as const, icon: Check },
  warning: { label: '警告', variant: 'warning' as const, icon: AlertTriangle },
  error: { label: '错误', variant: 'danger' as const, icon: AlertTriangle },
  unknown: { label: '未知', variant: 'secondary' as const, icon: Info },
}

// ---------- 存储统计（模拟） ----------
const storageStats = ref([
  { label: '文档存储', used: 0, total: 1024 * 1024 * 1024 * 10, unit: 'GB' },
  { label: '向量数据库', used: 0, total: 1024 * 1024 * 1024 * 50, unit: 'GB' },
  { label: '图数据库', used: 0, total: 1024 * 1024 * 1024 * 20, unit: 'GB' },
])

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function getUsagePercent(used: number, total: number): number {
  if (total === 0) return 0
  return Math.min(100, (used / total) * 100)
}

// ---------- 用户信息 ----------
const userInfo = ref({
  username: 'admin',
  email: 'admin@hansight.local',
  role: '超级管理员',
  createdAt: '-',
})

onMounted(() => {
  // 从 auth store 获取用户信息
  if (authStore.user) {
    userInfo.value = {
      username: authStore.user.username || 'admin',
      email: authStore.user.email || 'admin@hansight.local',
      role: authStore.user.is_superuser ? '超级管理员' : '普通用户',
      createdAt: authStore.user.created_at || '-',
    }
  }

  // 应用 reduce-motion 类
  if (motionReduced.value) {
    document.documentElement.classList.add('reduce-motion')
  }
})
</script>

<template>
  <div>
    <PageHeader title="系统设置" description="管理应用偏好与系统状态" />

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
        <TabsTrigger value="notifications">
          <Bell class="size-3.5" :stroke-width="1.5" />
          通知
        </TabsTrigger>
      </TabsList>

      <!-- 外观设置 -->
      <TabsContent value="appearance">
        <div class="space-y-4">
          <!-- 主题模式 -->
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
                  <Check
                    v-if="appStore.themeMode === opt.value"
                    class="size-4 text-primary"
                    :stroke-width="1.5"
                  />
                </button>
              </div>
            </CardContent>
          </Card>

          <!-- 布局偏好 -->
          <Card>
            <CardContent class="space-y-4 p-6">
              <div>
                <h3 class="text-sm font-medium text-foreground">布局偏好</h3>
                <p class="text-xs text-muted-foreground">调整界面密度与动效</p>
              </div>

              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>紧凑模式</Label>
                  <p class="text-xs text-muted-foreground">
                    减小间距与字号以容纳更多内容
                  </p>
                </div>
                <Switch
                  :checked="compactMode"
                  @update:checked="updateCompactMode"
                />
              </div>

              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>减弱动效</Label>
                  <p class="text-xs text-muted-foreground">
                    减少过渡动画以提升性能
                  </p>
                </div>
                <Switch
                  :checked="motionReduced"
                  @update:checked="updateMotionReduced"
                />
              </div>

              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>侧边栏折叠</Label>
                  <p class="text-xs text-muted-foreground">
                    折叠侧边栏以扩展内容区
                  </p>
                </div>
                <Switch
                  :checked="appStore.sidebarCollapsed"
                  @update:checked="appStore.toggleSidebar"
                />
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
                  {{ userInfo.username.slice(0, 2).toUpperCase() }}
                </AvatarFallback>
              </Avatar>

              <div class="flex-1 space-y-4">
                <div>
                  <h3 class="text-lg font-medium text-foreground">
                    {{ userInfo.username }}
                  </h3>
                  <p class="text-sm text-muted-foreground">{{ userInfo.email }}</p>
                </div>

                <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div class="rounded-md border border-border bg-muted/20 p-3">
                    <p class="text-[10px] uppercase tracking-wide text-muted-foreground">角色</p>
                    <Badge variant="secondary" class="mt-1 text-[10px]">
                      {{ userInfo.role }}
                    </Badge>
                  </div>
                  <div class="rounded-md border border-border bg-muted/20 p-3">
                    <p class="text-[10px] uppercase tracking-wide text-muted-foreground">创建时间</p>
                    <p class="mt-1 font-mono text-xs text-foreground">{{ userInfo.createdAt }}</p>
                  </div>
                </div>

                <div class="flex gap-2 border-t border-border pt-4">
                  <Button variant="outline" size="sm">
                    修改密码
                  </Button>
                  <Button variant="outline" size="sm">
                    编辑资料
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
                <p class="text-xs text-muted-foreground">
                  所有模型由后端配置，前端只读展示
                </p>
              </div>
              <Badge variant="secondary" class="text-[10px]">
                只读
              </Badge>
            </div>

            <div class="space-y-2">
              <div
                v-for="model in modelStatuses"
                :key="model.key"
                class="flex items-center gap-3 rounded-md border border-border bg-muted/20 p-3"
              >
                <div class="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <component :is="model.icon" class="size-4" :stroke-width="1.5" />
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs text-muted-foreground">{{ model.label }}</p>
                  <p class="truncate font-mono text-sm text-foreground" :title="model.value">
                    {{ model.value }}
                  </p>
                </div>
                <Badge
                  :variant="statusConfig[model.status].variant"
                  class="flex items-center gap-1 text-[10px]"
                >
                  <component :is="statusConfig[model.status].icon" class="size-3" :stroke-width="1.5" />
                  {{ statusConfig[model.status].label }}
                </Badge>
              </div>
            </div>

            <div class="mt-4 flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-3">
              <Info class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
              <p class="text-xs text-muted-foreground">
                模型状态由后端健康检查接口实时返回。当前页面仅作展示用途，如需修改请调整后端配置文件。
              </p>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- 存储统计 -->
      <TabsContent value="storage">
        <Card>
          <CardContent class="p-6">
            <div class="mb-4">
              <h3 class="text-sm font-medium text-foreground">存储使用情况</h3>
              <p class="text-xs text-muted-foreground">
                展示各存储服务的使用情况
              </p>
            </div>

            <div class="space-y-3">
              <div
                v-for="storage in storageStats"
                :key="storage.label"
                class="space-y-1.5"
              >
                <div class="flex items-center justify-between text-sm">
                  <span class="font-medium text-foreground">{{ storage.label }}</span>
                  <span class="font-mono text-xs text-muted-foreground">
                    {{ formatBytes(storage.used) }} / {{ formatBytes(storage.total) }}
                  </span>
                </div>
                <div class="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    class="h-full rounded-full bg-primary transition-all duration-300"
                    :style="{ width: `${getUsagePercent(storage.used, storage.total)}%` }"
                  />
                </div>
              </div>
            </div>

            <div class="mt-4 flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-3">
              <Info class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
              <p class="text-xs text-muted-foreground">
                存储统计由后端监控接口提供。当前显示为占位数据，实际使用量请以后端返回为准。
              </p>
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
                <p class="text-xs text-muted-foreground">
                  开启后将在任务完成、错误等事件发生时显示提示
                </p>
              </div>
              <Switch
                :checked="notificationsEnabled"
                @update:checked="updateNotifications"
              />
            </div>

            <div class="border-t border-border pt-4">
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>任务完成通知</Label>
                  <p class="text-xs text-muted-foreground">
                    文档解析、索引构建等任务完成时提示
                  </p>
                </div>
                <Switch
                  :checked="notificationsEnabled"
                  disabled
                />
              </div>
            </div>

            <div class="border-t border-border pt-4">
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <Label>错误通知</Label>
                  <p class="text-xs text-muted-foreground">
                    任务失败或系统错误时提示
                  </p>
                </div>
                <Switch
                  :checked="notificationsEnabled"
                  disabled
                />
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
