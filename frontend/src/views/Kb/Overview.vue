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
import type { KbStats, KbResourceVerify } from '@/api/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

const router = useRouter()
const kbStore = useKbStore()
const kb = kbStore.currentKb

const stats = ref<KbStats | null>(null)
const statsLoading = ref(true)
const resourceVerify = ref<KbResourceVerify | null>(null)
const verifyLoading = ref(false)

const statCards = [
  { key: 'total_documents' as const, label: '文档数', icon: FileText, color: 'bg-primary/10 text-primary' },
  { key: 'total_chunks' as const, label: '分块数', icon: Database, color: 'bg-success/10 text-success' },
  { key: 'total_tasks' as const, label: '任务数', icon: ListChecks, color: 'bg-warning/10 text-warning' },
  { key: 'total_members' as const, label: '成员数', icon: Users, color: 'bg-primary/10 text-primary' },
]

const quickActions = [
  { name: 'KbDocuments', label: '文档管理', icon: FileText, description: '上传与管理文档' },
  { name: 'KbExtraction', label: '结构化抽取', icon: FileSearch, description: '配置抽取类别与执行抽取' },
  { name: 'KbConfig', label: '配置中心', icon: Settings, description: 'OCR/向量/抽取/问答配置' },
  { name: 'KbQA', label: '智能问答', icon: MessageSquare, description: '基于 RAG 的问答' },
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

async function fetchResourceVerify() {
  if (!kb) return
  verifyLoading.value = true
  try {
    resourceVerify.value = await kbApi.verifyResources(kb.id)
  } catch {
    resourceVerify.value = null
  } finally {
    verifyLoading.value = false
  }
}

function goTo(routeName: string) {
  router.push({ name: routeName, params: { kb_id: kb?.id } })
}

onMounted(() => {
  fetchStats()
})
</script>

<template>
  <div v-if="kb" class="space-y-6">
    <!-- 知识库信息 -->
    <Card>
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
      <Card v-for="card in statCards" :key="card.key">
        <CardContent class="flex items-center gap-3 p-4">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-md" :class="card.color">
            <component :is="card.icon" class="size-5" :stroke-width="1.5" />
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-xs text-muted-foreground">{{ card.label }}</p>
            <Skeleton v-if="statsLoading" class="mt-1 h-6 w-16" />
            <p v-else class="font-mono text-2xl font-semibold text-foreground">
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
          class="cursor-pointer transition-all hover:border-primary/40 hover:shadow-sm"
          @click="goTo(action.name)"
        >
          <CardContent class="p-4">
            <div class="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
              <component :is="action.icon" class="size-4" :stroke-width="1.5" />
            </div>
            <p class="text-sm font-medium text-foreground">{{ action.label }}</p>
            <p class="mt-0.5 text-xs text-muted-foreground">{{ action.description }}</p>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- 资源诊断 -->
    <Card>
      <CardContent class="p-5">
        <div class="mb-4 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <h3 class="text-sm font-medium text-foreground">物理资源诊断</h3>
            <Badge v-if="resourceVerify && !verifyLoading" variant="secondary" class="text-[10px]">
              {{ Object.values(resourceVerify.steps).filter((s) => s.ok).length }}/{{ Object.keys(resourceVerify.steps).length }} 正常
            </Badge>
          </div>
          <Button variant="outline" size="sm" :disabled="verifyLoading" @click="fetchResourceVerify">
            <RefreshCw v-if="!verifyLoading" class="size-3.5" :stroke-width="1.5" />
            <Loader2 v-else class="size-3.5 animate-spin" :stroke-width="1.5" />
            诊断
          </Button>
        </div>

        <div v-if="verifyLoading" class="space-y-2">
          <Skeleton v-for="i in 5" :key="i" class="h-8 w-full" />
        </div>

        <div v-else-if="resourceVerify" class="space-y-2">
          <div
            v-for="(step, name) in resourceVerify.steps"
            :key="name"
            class="flex items-center justify-between rounded-md border border-border px-3 py-2"
          >
            <span class="text-sm text-foreground">{{ name }}</span>
            <div class="flex items-center gap-2">
              <component
                :is="step.ok ? CheckCircle2 : step.error ? XCircle : AlertTriangle"
                class="size-4"
                :class="step.ok ? 'text-success' : step.error ? 'text-danger' : 'text-warning'"
                :stroke-width="1.5"
              />
              <span class="text-xs" :class="step.ok ? 'text-success' : 'text-danger'">
                {{ step.ok ? '正常' : '异常' }}
              </span>
            </div>
          </div>
        </div>

        <p v-else class="py-4 text-center text-sm text-muted-foreground">
          点击「诊断」检查物理资源完整性
        </p>
      </CardContent>
    </Card>
  </div>
</template>
