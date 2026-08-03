<script setup lang="ts">
/**
 * 知识库内布局（KBLayout）
 *
 * 进入知识库后的二级布局，提供知识库专属导航：
 *   概览 / 文档 / 抽取 / 配置 / 问答 / 成员
 *
 * 结构：
 *   ┌──────────────────────────────────┐
 *   │ KB TopBar（返回 + KB名 + 角色）  │
 *   ├────────┬─────────────────────────┤
 *   │ KB Nav │ Content (router-view)    │
 *   └────────┴─────────────────────────┘
 */
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  LayoutDashboard,
  FileText,
  FileSearch,
  Database,
  BookMarked,
  ListChecks,
  Share2,
  Settings,
  MessageSquare,
  Users,
  Loader2,
  Search,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import type { KnowledgeBase, KbRole } from '@/api/types'
import { useKbStore } from '@/stores/kb'
import MobileTabBar from '@/components/layout/MobileTabBar.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()

const kbId = ref<string>('')
const kb = ref<KnowledgeBase | null>(null)
const loading = ref(true)

// 导航项（11 项：概览/文档/搜索/抽取/Schema/术语/任务/图谱/配置/问答/成员）
const navItems = [
  { name: 'KbOverview', label: '概览', icon: LayoutDashboard },
  { name: 'KbDocuments', label: '文档', icon: FileText },
  { name: 'KbSearch', label: '搜索', icon: Search },
  { name: 'KbExtraction', label: '抽取', icon: FileSearch },
  { name: 'KbSchemas', label: 'Schema', icon: Database },
  { name: 'KbTerms', label: '术语', icon: BookMarked },
  { name: 'KbTasks', label: '任务', icon: ListChecks },
  { name: 'KbGraph', label: '图谱', icon: Share2 },
  { name: 'KbConfig', label: '配置', icon: Settings },
  { name: 'KbQA', label: '问答', icon: MessageSquare },
  { name: 'KbMembers', label: '成员', icon: Users },
]

// 角色标签颜色
const roleColor: Record<KbRole, string> = {
  owner: 'bg-primary/10 text-primary',
  admin: 'bg-success/10 text-success',
  editor: 'bg-warning/10 text-warning',
  viewer: 'bg-muted text-muted-foreground',
}
const roleLabel: Record<KbRole, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

async function loadKb() {
  kbId.value = route.params.kb_id as string
  if (!kbId.value) return
  loading.value = true
  try {
    kb.value = await kbApi.get(kbId.value)
    kbStore.setCurrent(kb.value)
  } catch {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push({ name: 'KbList' })
}

onMounted(loadKb)
watch(() => route.params.kb_id, loadKb)
</script>

<template>
  <!-- fullscreen 模式：隐藏侧边导航，内容全屏 -->
  <div v-if="route.meta.fullscreen" class="flex h-screen flex-col bg-background">
    <ErrorBoundary v-if="kb">
      <router-view />
    </ErrorBoundary>
  </div>

  <!-- 标准 KB 布局 -->
  <div v-else class="flex h-screen flex-col">
    <!-- KB TopBar -->
    <header class="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      <button
        class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted"
        @click="goBack"
      >
        <ArrowLeft class="size-4" :stroke-width="1.5" />
      </button>

      <div class="flex items-center gap-2">
        <div class="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Database class="size-4" :stroke-width="1.5" />
        </div>
        <div class="min-w-0">
          <p v-if="loading" class="text-sm font-medium text-muted-foreground">加载中...</p>
          <p v-else-if="kb" class="truncate text-sm font-semibold text-foreground">{{ kb.name }}</p>
        </div>
      </div>

      <span
        v-if="kb?.my_role"
        class="rounded-md px-2 py-0.5 text-[10px] font-medium"
        :class="roleColor[kb.my_role as KbRole]"
      >
        {{ roleLabel[kb.my_role as KbRole] }}
      </span>

      <span
        v-if="kb && !kb.is_active"
        class="rounded-md bg-danger/10 px-2 py-0.5 text-[10px] font-medium text-danger"
      >
        已停用
      </span>

      <div class="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
        <span v-if="kb?.template_code" class="rounded-md bg-muted px-2 py-0.5 font-mono">
          {{ kb.template_code }}
        </span>
      </div>
    </header>

    <div class="flex flex-1 overflow-hidden">
      <!-- KB 侧边导航 -->
      <nav class="hidden w-48 shrink-0 border-r border-border bg-background lg:block">
        <ul class="space-y-1 p-3">
          <li v-for="item in navItems" :key="item.name">
            <router-link
              :to="{ name: item.name, params: { kb_id: route.params.kb_id } }"
              class="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              :class="{
                'bg-primary/10 text-primary font-medium': route.name === item.name,
              }"
            >
              <component :is="item.icon" class="size-4" :stroke-width="1.5" />
              {{ item.label }}
            </router-link>
          </li>
        </ul>
      </nav>

      <!-- 主内容区（移动端底部留白避免被 TabBar 遮挡） -->
      <main class="flex-1 overflow-auto bg-muted/10 p-4 pb-20 lg:p-6 lg:pb-6">
        <div v-if="loading" class="flex h-full items-center justify-center">
          <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
        </div>
        <ErrorBoundary v-else-if="kb">
          <router-view />
        </ErrorBoundary>
      </main>
    </div>

    <!-- 移动端底部导航（lg 以下显示，替代横向滚动导航） -->
    <MobileTabBar />
  </div>
</template>
