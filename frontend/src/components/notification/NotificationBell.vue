<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Bell,
  CheckCheck,
  Trash2,
  Loader2,
  CheckCircle2,
  XCircle,
  Info,
  AlertTriangle,
  Users,
} from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { notificationApi, type Notification } from '@/api/modules/notification'
import { useSSE } from '@/composables/useSSE'

const router = useRouter()
const { consume: consumeSSE, stop: stopSSE } = useSSE()

const unreadCount = ref(0)
const notifications = ref<Notification[]>([])
const loading = ref(false)
const open = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null
let sseReconnectTimer: ReturnType<typeof setTimeout> | null = null
let sseStopped = false

// 通知类型 → 图标映射
const typeIcon = {
  task_done: CheckCircle2,
  task_failed: XCircle,
  system: Info,
  audit_alert: AlertTriangle,
  kb_member: Users,
} as const

// 通知类型 → 颜色映射
const typeColor = {
  task_done: 'text-success',
  task_failed: 'text-danger',
  system: 'text-info',
  audit_alert: 'text-warning',
  kb_member: 'text-muted-foreground',
} as const

const hasUnread = computed(() => unreadCount.value > 0)

async function fetchUnreadCount() {
  try {
    const res = await notificationApi.unreadCount()
    unreadCount.value = res.count
  } catch {
    /* 静默：未读数轮询失败不打扰用户 */
  }
}

async function fetchNotifications() {
  loading.value = true
  try {
    const res = await notificationApi.list({ page: 1, page_size: 20 })
    notifications.value = res.items
  } catch {
    notifications.value = []
  } finally {
    loading.value = false
  }
}

async function markRead(n: Notification) {
  try {
    await notificationApi.markRead(n.id)
    n.read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch {
    /* 静默 */
  }
  // 跳转到对应资源
  navigateToResource(n)
}

async function markAllRead() {
  try {
    const res = await notificationApi.markAllRead()
    notifications.value.forEach((n) => (n.read = true))
    unreadCount.value = 0
    toast.success('全部已读', `已标记 ${res.updated} 条`)
  } catch {
    toast.error('操作失败', '请稍后重试')
  }
}

async function deleteNotification(n: Notification, event: Event) {
  event.stopPropagation()
  try {
    await notificationApi.delete(n.id)
    notifications.value = notifications.value.filter((item) => item.id !== n.id)
    if (!n.read) unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch {
    toast.error('删除失败', '请稍后重试')
  }
}

function navigateToResource(n: Notification) {
  if (!n.resource_type || !n.kb_id) return
  // 按资源类型跳转（当前仅支持 task → KB 任务页）
  if (n.resource_type === 'task') {
    router.push({ name: 'KbTasks', params: { kb_id: n.kb_id } })
  } else if (n.resource_type === 'document') {
    router.push({ name: 'KbDocuments', params: { kb_id: n.kb_id } })
  }
}

// 打开时加载通知列表
watch(open, (val) => {
  if (val) fetchNotifications()
})

function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now.getTime() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 2592000) return `${Math.floor(diff / 86400)} 天前`
  return d.toLocaleDateString('zh-CN')
}

function getIcon(type: string) {
  return typeIcon[type as keyof typeof typeIcon] || Bell
}

function getColor(type: string) {
  return typeColor[type as keyof typeof typeColor] || 'text-muted-foreground'
}

// SSE 实时推送连接（轮询作为兜底）
async function connectSSE() {
  if (sseStopped) return
  const url = notificationApi.subscribeUrl()
  await consumeSSE<Notification>(
    url,
    {
      onChunk: (event) => {
        // 收到实时通知事件，更新未读数
        if (event && event.id) {
          unreadCount.value++
          // 如果弹窗已打开，同步插入列表顶部
          if (open.value) {
            notifications.value.unshift(event as Notification)
          }
        }
      },
      onError: () => {
        // 连接出错，5 秒后自动重连
        scheduleReconnect(5000)
      },
    },
  )
  // consume 返回（连接断开），自动重连
  if (!sseStopped) scheduleReconnect(5000)
}

function scheduleReconnect(delay: number) {
  if (sseStopped) return
  if (sseReconnectTimer) clearTimeout(sseReconnectTimer)
  // 指数退避，最大 60 秒
  sseReconnectTimer = setTimeout(() => {
    connectSSE()
  }, Math.min(delay, 60000))
}

onMounted(() => {
  fetchUnreadCount()
  // 30 秒轮询未读数（SSE 兜底）
  pollTimer = setInterval(fetchUnreadCount, 30000)
  // 建立 SSE 长连接
  connectSSE()
})

onUnmounted(() => {
  sseStopped = true
  if (pollTimer) clearInterval(pollTimer)
  if (sseReconnectTimer) clearTimeout(sseReconnectTimer)
  stopSSE()
})
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button
        type="button"
        class="relative inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="通知"
      >
        <Bell class="size-4" :stroke-width="1.5" />
        <!-- 未读数 Badge -->
        <span
          v-if="hasUnread"
          class="absolute -right-0.5 -top-0.5 flex min-w-[16px] h-[16px] items-center justify-center rounded-full bg-danger px-1 text-[10px] font-medium leading-none text-danger-foreground"
        >
          {{ unreadCount > 99 ? '99+' : unreadCount }}
        </span>
      </button>
    </PopoverTrigger>

    <PopoverContent align="end" :side-offset="8" class="w-80 p-0">
      <!-- 顶部操作栏 -->
      <div class="flex items-center justify-between border-b border-border px-3 py-2">
        <span class="text-sm font-medium text-foreground">通知</span>
        <Button
          variant="ghost"
          size="sm"
          class="h-7 px-2 text-xs text-muted-foreground"
          :disabled="!hasUnread"
          @click="markAllRead"
        >
          <CheckCheck class="size-3.5" :stroke-width="1.5" />
          全部已读
        </Button>
      </div>

      <!-- 通知列表 -->
      <div class="max-h-96 overflow-y-auto">
        <div v-if="loading" class="flex justify-center py-8">
          <Loader2 class="size-5 animate-spin text-muted-foreground" :stroke-width="1.5" />
        </div>

        <div
          v-else-if="notifications.length === 0"
          class="flex flex-col items-center gap-2 py-10 text-center"
        >
          <Bell class="size-8 text-muted-foreground/40" :stroke-width="1.25" />
          <p class="text-xs text-muted-foreground">暂无通知</p>
        </div>

        <ul v-else class="divide-y divide-border">
          <li
            v-for="n in notifications"
            :key="n.id"
            class="group relative flex cursor-pointer items-start gap-2.5 px-3 py-2.5 transition-colors hover:bg-muted/60"
            :class="!n.read ? 'bg-primary/[0.03]' : ''"
            @click="!n.read && markRead(n)"
          >
            <!-- 未读左侧色条 -->
            <span
              v-if="!n.read"
              class="absolute left-0 top-0 h-full w-0.5 bg-primary"
            />
            <!-- 类型图标 -->
            <component
              :is="getIcon(n.type)"
              class="mt-0.5 size-4 shrink-0"
              :class="getColor(n.type)"
              :stroke-width="1.5"
            />
            <!-- 内容 -->
            <div class="min-w-0 flex-1">
              <p
                class="truncate text-sm text-foreground"
                :class="!n.read ? 'font-medium' : 'font-normal'"
              >
                {{ n.title }}
              </p>
              <p v-if="n.content" class="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {{ n.content }}
              </p>
              <p class="mt-1 text-[10px] text-muted-foreground/70">
                {{ formatTime(n.created_at) }}
              </p>
            </div>
            <!-- 删除按钮（hover 显示） -->
            <button
              type="button"
              class="shrink-0 rounded p-1 text-muted-foreground/50 opacity-0 transition-opacity hover:bg-muted hover:text-danger group-hover:opacity-100"
              aria-label="删除"
              @click.stop="deleteNotification(n, $event)"
            >
              <Trash2 class="size-3.5" :stroke-width="1.5" />
            </button>
          </li>
        </ul>
      </div>
    </PopoverContent>
  </Popover>
</template>
