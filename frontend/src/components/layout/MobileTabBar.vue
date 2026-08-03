<script setup lang="ts">
/**
 * 移动端底部导航栏（KB 内）。
 *
 * 在 lg 以下显示，提供 5 个主要 KB 功能的快捷入口：
 *   概览 / 文档 / 抽取 / 问答 / 配置
 *
 * 其他次要页面（Schema/术语/任务/图谱/成员）可通过概览页快速入口访问。
 * 桌面端（lg+）由 KbLayout 的侧边导航覆盖全部 11 项，本组件隐藏。
 */
import { useRoute } from 'vue-router'
import {
  LayoutDashboard,
  FileText,
  FileSearch,
  MessageSquare,
  Settings,
} from 'lucide-vue-next'

const route = useRoute()

const tabs = [
  { name: 'KbOverview', label: '概览', icon: LayoutDashboard },
  { name: 'KbDocuments', label: '文档', icon: FileText },
  { name: 'KbExtraction', label: '抽取', icon: FileSearch },
  { name: 'KbQA', label: '问答', icon: MessageSquare },
  { name: 'KbConfig', label: '配置', icon: Settings },
] as const
</script>

<template>
  <nav
    class="fixed bottom-0 left-0 right-0 z-[1100] flex border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:hidden"
    aria-label="移动端主导航"
  >
    <router-link
      v-for="tab in tabs"
      :key="tab.name"
      :to="{ name: tab.name, params: { kb_id: route.params.kb_id } }"
      class="flex flex-1 flex-col items-center gap-1 py-2 text-[10px] transition-colors"
      :class="
        route.name === tab.name
          ? 'text-primary'
          : 'text-muted-foreground hover:text-foreground'
      "
    >
      <component :is="tab.icon" class="size-5" :stroke-width="1.5" />
      <span class="font-medium">{{ tab.label }}</span>
    </router-link>
  </nav>
</template>
