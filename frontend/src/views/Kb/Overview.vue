<script setup lang="ts">
/**
 * 知识库概览页
 *
 * 展示知识库统计、资源状态、快速入口。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  FileText,
  Database,
  ListChecks,
  Users,
  Settings,
  FileSearch,
  MessageSquare,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import type { KbStats, ServiceCheckResult } from '@/api/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

const router = useRouter()
const kbStore = useKbStore()
const kb = kbStore.currentKb

const stats = ref<KbStats | null>(null)
const statsLoading = ref(true)
const servicesStatus = ref<{
  checked_at: string | null
  total: number
  ok_count: number
  error_count: number
  warning_count: number
  services: ServiceCheckResult[]
  never_checked: boolean
} | null>(null)
const verifyLoading = ref(false)

const statCards = [
  { key: 'total_documents' as const, label: '文档数', icon: FileText, color: 'bg-primary/10 text-primary' },
  { key: 'total_chunks' as const, label: '分块数', icon: Database, color: 'bg-success/10 text-success' },
  { key: 'total_tasks' as const, label: '任务数', icon: ListChecks, color: 'bg-warning/10 text-warning' },
  { key: 'total_members' as const, label: '成员数', icon: Users, color: 'bg-primary/10 text-primary' },
]

const quickActions = [
  { name: 'KbDocuments', label: '文档解析', icon: FileText, description: '上传与解析文档' },
  { name: 'KbExtraction', label: '结构化抽取', icon: FileSearch, description: '配置抽取类别与执行抽取' },
  { name: 'KbConfig', label: '资源与配置', icon: Settings, description: 'OCR/向量/抽取/问答配置' },
  { name: 'KbQA', label: '知识问答', icon: MessageSquare, description: '基于 RAG 的问答' },
]

async function fetchStats() {
  if (!kb) return
  statsLoading.value = true
  try {
    stats.value = await kbApi.stats(kb.id)
  } catch {
    stats.value = null
  } finally {
    statsLoading.value = false
  }
}

async function fetchServicesStatus() {
  if (!kb) return
  try {
    const result = await kbApi.getServicesStatus(kb.id)
    // 将 services 对象转为数组
    const servicesList = Array.isArray(result.services)
      ? result.services
      : Object.values(result.services)
    servicesStatus.value = {
      ...result,
      services: servicesList,
    }
  } catch {
    servicesStatus.value = null
  }
}

async function runDiagnose() {
  if (!kb) return
  verifyLoading.value = true
  try {
    const result = await kbApi.diagnoseAllServices(kb.id)
    servicesStatus.value = {
      checked_at: result.checked_at,
      total: result.total,
      ok_count: result.ok_count,
      error_count: result.error_count,
      warning_count: result.warning_count,
      services: result.services,
      never_checked: false,
    }
  } catch {
    // 诊断失败不清除已有状态
  } finally {
    verifyLoading.value = false
  }
}

function goTo(routeName: string) {
  router.push({ name: routeName, params: { kb_id: kb?.id } })
}

onMounted(() => {
  fetchStats()
  fetchServicesStatus()
})
</script>

<template>
  <div v-if="kb" class="space-y-6">
    <!-- 知识库信息 -->
    <Card class="rounded-xl shadow-sm transition-all duration-200 hover:shadow-md hover:border-primary/20 hover:-translate-y-0.5">
      <CardContent class="p-5">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1 min-w-0">
            <h2 class="text-lg font-semibold text-foreground">{{ kb.name }}</h2>
            <p class="mt-1 text-sm text-muted-foreground">{{ kb.description || '暂无描述' }}</p>
            <div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="secondary" class="font-mono">{{ kb.domain_code }}</Badge>
              <Badge v-if="kb.template_code" variant="outline" class="font-mono">
                模板: {{ kb.template_code }}
              </Badge>
              <span class="text-muted-foreground">创建于 {{ new Date(kb.created_at).toLocaleString('zh-CN') }}</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Card
        v-for="card in statCards"
        :key="card.key"
        class="rounded-xl shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md hover:border-primary/20"
      >
        <CardContent class="flex items-center gap-3 p-4">
          <div
            class="flex size-11 shrink-0 items-center justify-center rounded-lg shadow-sm transition-all duration-200 hover:scale-110"
            :class="card.color"
          >
            <component :is="card.icon" class="size-5" :stroke-width="1.5" />
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-xs text-muted-foreground/80">{{ card.label }}</p>
            <Skeleton v-if="statsLoading" class="mt-1 h-6 w-16 rounded-md" />
            <p v-else class="text-2xl font-semibold tracking-tight text-foreground tabular-nums">
              {{ stats?.[card.key] ?? 0 }}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 快速入口 -->
    <div>
      <h3 class="mb-3 text-sm font-medium text-foreground">快速入口</h3>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card
          v-for="action in quickActions"
          :key="action.name"
          class="group cursor-pointer rounded-xl shadow-sm transition-all duration-300 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 hover:-translate-y-1"
          @click="goTo(action.name)"
        >
          <CardContent class="p-4">
            <div class="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary shadow-sm transition-all duration-300 group-hover:scale-110 group-hover:bg-primary/15 group-hover:shadow-md">
              <component :is="action.icon" class="size-5" :stroke-width="1.5" />
            </div>
            <p class="text-sm font-medium text-foreground transition-colors">{{ action.label }}</p>
            <p class="mt-0.5 text-xs text-muted-foreground">{{ action.description }}</p>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- 服务诊断 -->
    <Card class="rounded-xl shadow-sm transition-all duration-200 hover:shadow-md">
      <CardContent class="p-5">
        <div class="mb-4 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <h3 class="text-sm font-medium text-foreground">服务状态诊断</h3>
            <Badge v-if="servicesStatus && !servicesStatus.never_checked && !verifyLoading" variant="secondary" class="text-[10px]">
              {{ servicesStatus.ok_count }}/{{ servicesStatus.total }} 正常
              <span v-if="servicesStatus.checked_at" class="ml-1 text-muted-foreground">
                ({{ new Date(servicesStatus.checked_at).toLocaleString('zh-CN') }})
              </span>
            </Badge>
          </div>
          <Button variant="outline" size="sm" :disabled="verifyLoading" @click="runDiagnose">
            <RefreshCw v-if="!verifyLoading" class="size-3.5" :stroke-width="1.5" />
            <Loader2 v-else class="size-3.5 animate-spin" :stroke-width="1.5" />
            {{ servicesStatus?.never_checked ? '一键诊断' : '重新诊断' }}
          </Button>
        </div>

        <div v-if="verifyLoading" class="space-y-2">
          <Skeleton v-for="i in 5" :key="i" class="h-9 w-full rounded-lg" />
        </div>

        <div v-else-if="servicesStatus && !servicesStatus.never_checked" class="space-y-2">
          <div
            v-for="svc in servicesStatus.services"
            :key="svc.name"
            class="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2.5 transition-all duration-200 hover:border-primary/20 hover:bg-primary/5 hover:shadow-sm hover:-translate-y-0.5"
          >
            <div class="flex flex-col">
              <span class="text-sm text-foreground">{{ svc.display_name || svc.name }}</span>
              <span v-if="svc.message" class="text-xs text-muted-foreground">{{ svc.message }}</span>
            </div>
            <div class="flex items-center gap-2">
              <component
                :is="svc.status === 'ok' ? CheckCircle2 : svc.status === 'warning' ? AlertTriangle : XCircle"
                class="size-4 transition-transform duration-200 hover:scale-110"
                :class="svc.status === 'ok' ? 'text-success' : svc.status === 'warning' ? 'text-warning' : 'text-danger'"
                :stroke-width="1.5"
              />
              <span
                class="text-xs font-medium"
                :class="svc.status === 'ok' ? 'text-success' : svc.status === 'warning' ? 'text-warning' : 'text-danger'"
              >
                {{ svc.status === 'ok' ? '正常' : svc.status === 'warning' ? '警告' : '异常' }}
              </span>
            </div>
          </div>
        </div>

        <p v-else class="py-4 text-center text-sm text-muted-foreground">
          点击「一键诊断」检查所有服务连接状态
        </p>
      </CardContent>
    </Card>
  </div>
</template>
