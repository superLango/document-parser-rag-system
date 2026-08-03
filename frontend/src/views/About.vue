<script setup lang="ts">
/**
 * 关于页面（阶段 4 - 帮助文档）。
 *
 * 展示 HansonDOC RAG 系统信息、核心特性与技术栈。
 */
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Database, Shield, Layers, GitBranch, Server, Cpu } from 'lucide-vue-next'

const features = [
  {
    icon: Database,
    title: '六层隔离',
    desc: '数据库 / 向量库 / 对象存储 / 图谱 / 缓存 / 配置六层物理隔离',
  },
  {
    icon: Layers,
    title: '领域模板',
    desc: '4 个内置模板，支持自定义领域配置化抽取',
  },
  {
    icon: GitBranch,
    title: 'Hook 机制',
    desc: '每 KB 独立 Hook 脚本，扩展特殊业务逻辑',
  },
  {
    icon: Shield,
    title: 'RBAC 权限',
    desc: 'owner / admin / editor / viewer 四级角色控制',
  },
  {
    icon: Cpu,
    title: '流式抽取',
    desc: '基于 vLLM + SSE 的流式结构化字段抽取',
  },
  {
    icon: Server,
    title: '生产级运维',
    desc: '审计 / 备份恢复 / 资源清理 / 限流 / IP 白名单',
  },
]

const stack = [
  'FastAPI',
  'SQLAlchemy 2.0',
  'PostgreSQL',
  'Milvus',
  'MinIO',
  'NebulaGraph',
  'Redis',
  'arq',
  'Vue 3',
  'TypeScript',
  'Tailwind CSS v4',
  'shadcn-vue',
]
</script>

<template>
  <div>
    <PageHeader title="关于" description="HansonDOC RAG 系统信息" />

    <div class="space-y-6">
      <!-- 系统简介 -->
      <Card>
        <CardContent class="p-6">
          <div class="flex items-center gap-3">
            <div class="flex size-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Database class="size-6" :stroke-width="1.5" />
            </div>
            <div>
              <h2 class="text-2xl font-bold text-foreground">HansonDOC RAG</h2>
              <p class="text-sm text-muted-foreground">以知识库为隔离边界的垂直领域文档智能产品</p>
            </div>
          </div>
          <p class="mt-4 text-sm leading-relaxed text-muted-foreground">
            HansonDOC RAG 集成结构化抽取与 RAG 问答，采用六层物理隔离架构确保多租户数据安全。
            支持多领域模板、Hook 扩展机制与流式抽取，适用于材料检测、医疗器械、合同分析等垂直场景。
          </p>

          <div class="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="f in features" :key="f.title" class="space-y-2">
              <div class="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <component :is="f.icon" class="size-5" :stroke-width="1.5" />
              </div>
              <h3 class="text-sm font-medium text-foreground">{{ f.title }}</h3>
              <p class="text-xs leading-relaxed text-muted-foreground">{{ f.desc }}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- 技术栈 -->
      <Card>
        <CardContent class="p-6">
          <h3 class="mb-3 text-sm font-medium text-foreground">技术栈</h3>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="s in stack"
              :key="s"
              class="rounded-md border border-border bg-muted px-2.5 py-1 font-mono text-xs text-muted-foreground"
            >
              {{ s }}
            </span>
          </div>
        </CardContent>
      </Card>

      <!-- 架构亮点 -->
      <Card>
        <CardContent class="p-6">
          <h3 class="mb-3 text-sm font-medium text-foreground">架构亮点</h3>
          <ul class="space-y-2 text-sm text-muted-foreground">
            <li class="flex items-start gap-2">
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
              <span>知识库为隔离边界，PostgreSQL RLS 行级安全 + Milvus/MinIO/NebulaGraph 物理隔离</span>
            </li>
            <li class="flex items-start gap-2">
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
              <span>GLM-OCR 混合模式：PP-DocLayoutV3 版面分析 + 全并行 OCR 识别</span>
            </li>
            <li class="flex items-start gap-2">
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
              <span>领域模板纯数据配置 + Hook 脚本承载特殊逻辑，配置与代码分离</span>
            </li>
            <li class="flex items-start gap-2">
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
              <span>arq 异步任务 + cron 定时清理，生产级运维完备</span>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
