<script setup lang="ts">
/**
 * 知识库内布局（KBLayout）
 *
 * 进入知识库后的二级布局，提供知识库专属导航
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
  SlidersHorizontal,
  RefreshCw,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import type { KnowledgeBase, KbRole } from '@/api/types'
import { useKbStore } from '@/stores/kb'
import MobileTabBar from '@/components/layout/MobileTabBar.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { Button } from '@/components/ui/button'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()

const kbId = ref<string>('')
const kb = ref<KnowledgeBase | null>(null)
const loading = ref(true)

const navItems = [
  { name: 'KbOverview', label: '概览', icon: LayoutDashboard },
  { name: 'KbDocuments', label: '文档解析', icon: FileText },
  { name: 'KbSearch', label: '向量搜索', icon: Search },
  { name: 'KbExtraction', label: '结构化抽取', icon: FileSearch },
  { name: 'KbExtractionConfig', label: '抽取配置', icon: SlidersHorizontal },
  { name: 'KbTerms', label: '专业术语集', icon: BookMarked },
  { name: 'KbTasks', label: '任务列表', icon: ListChecks },
  { name: 'KbGraph', label: '知识图谱', icon: Share2 },
  { name: 'KbConfig', label: '资源与配置', icon: Settings },
  { name: 'KbQA', label: '知识问答', icon: MessageSquare },
  { name: 'KbMembers', label: '知识库成员', icon: Users },
]

const roleColor: Record<KbRole, string> = {
  owner: 'bg-primary/12 text-primary border border-primary/20',
  admin: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20',
  editor: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20',
  viewer: 'bg-muted text-muted-foreground border border-border/50',
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
    // error handled by interceptor
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
  <div class="flex h-screen flex-col bg-subtle-gradient">
    <!-- fullscreen 模式 -->
    <template v-if="route.meta.fullscreen">
      <ErrorBoundary v-if="kb">
        <router-view v-slot="{ Component, route: viewRoute }">
          <component :is="Component" :key="viewRoute.fullPath" />
        </router-view>
      </ErrorBoundary>
      <div v-else class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        <Loader2 class="mr-2 size-4 animate-spin" :stroke-width="1.5" />
        加载中...
      </div>
    </template>

    <!-- 标准 KB 布局 -->
    <template v-else>
      <!-- KB TopBar - 玻璃态 -->
      <header class="flex h-14 shrink-0 items-center gap-3 border-b border-border/50 glass px-4">
        <button
          class="group inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-all duration-200 hover:bg-muted/80 hover:text-foreground active:scale-95"
          @click="goBack"
        >
          <ArrowLeft class="size-4 transition-transform duration-200 group-hover:-translate-x-0.5" :stroke-width="1.5" />
        </button>

        <div class="flex items-center gap-2.5">
          <div class="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary shadow-sm shadow-primary/10">
            <Database class="size-4" :stroke-width="1.5" />
          </div>
          <div class="min-w-0">
            <p v-if="loading" class="text-sm font-medium text-muted-foreground">加载中...</p>
            <p v-else-if="kb" class="truncate text-sm font-semibold text-foreground">{{ kb.name }}</p>
          </div>
        </div>

        <span
          v-if="kb?.my_role"
          class="rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors"
          :class="roleColor[kb.my_role as KbRole]"
        >
          {{ roleLabel[kb.my_role as KbRole] }}
        </span>

        <span
          v-if="kb && !kb.is_active"
          class="rounded-md bg-red-500/10 px-2 py-0.5 text-[10px] font-medium text-red-600 dark:text-red-400 border border-red-500/20"
        >
          已停用
        </span>

        <div class="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <span v-if="kb?.template_code" class="rounded-md bg-muted/80 px-2 py-0.5 font-mono text-[10px]">
            {{ kb.template_code }}
          </span>
        </div>
      </header>

      <div class="flex flex-1 overflow-hidden">
        <!-- KB 侧边导航 - 增强版 -->
        <nav class="hidden w-56 shrink-0 border-r border-border/50 bg-card/60 backdrop-blur-sm lg:block">
          <ul class="flex flex-col gap-0.5 p-3">
            <li v-for="item in navItems" :key="item.name" class="relative">
              <!-- 活动指示器 -->
              <span
                v-if="route.name === item.name"
                class="nav-indicator nav-indicator-active"
              />
              <router-link
                :to="{ name: item.name, params: { kb_id: route.params.kb_id } }"
                class="group relative flex h-10 items-center gap-2.5 rounded-lg px-3 text-sm transition-all duration-200"
                :class="{
                  'bg-primary/10 text-primary font-medium shadow-sm shadow-primary/10': route.name === item.name,
                  'text-muted-foreground hover:bg-muted/80 hover:text-foreground hover:translate-x-0.5': route.name !== item.name,
                }"
              >
                <component
                  :is="item.icon"
                  :stroke-width="route.name === item.name ? 2 : 1.5"
                  :class="[
                    'shrink-0 transition-all duration-200',
                    route.name === item.name ? 'size-[18px] text-primary' : 'size-4 group-hover:text-foreground',
                  ]"
                />
                <span class="truncate">{{ item.label }}</span>
              </router-link>
            </li>
          </ul>
        </nav>

        <!-- 主内容区 -->
        <main class="flex-1 overflow-auto p-4 pb-20 lg:p-6 lg:pb-6">
          <div v-if="loading" class="flex h-full items-center justify-center">
            <div class="flex flex-col items-center gap-3">
              <Loader2 class="size-6 animate-spin text-primary" :stroke-width="1.5" />
              <span class="text-sm text-muted-foreground">加载知识库...</span>
            </div>
          </div>
          <ErrorBoundary v-else-if="kb">
            <router-view v-slot="{ Component, route: viewRoute }">
              <transition name="fade-slide" mode="out-in">
                <component :is="Component" :key="viewRoute.fullPath" />
              </transition>
            </router-view>
          </ErrorBoundary>
          <div v-else class="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div class="flex size-14 items-center justify-center rounded-full bg-muted/60">
              <Database class="size-6 text-muted-foreground" :stroke-width="1.5" />
            </div>
            <div>
              <p class="text-sm font-medium text-foreground">知识库加载失败</p>
              <p class="mt-1 text-xs text-muted-foreground">请检查网络连接后重试</p>
            </div>
            <Button variant="outline" size="sm" class="gap-1.5" @click="loadKb">
              <RefreshCw class="size-3.5" :stroke-width="1.5" />
              重试
            </Button>
          </div>
        </main>
      </div>

      <MobileTabBar />
    </template>
  </div>
</template>
