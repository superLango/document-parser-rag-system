<script setup lang="ts">
/**
 * 帮助文档页面（阶段 4 - 帮助文档）。
 *
 * 通过 ``import.meta.glob`` 在构建时加载 ``@/content/help/*.md`` 全部 Markdown 文件，
 * 解析 YAML frontmatter（title/category/order）后按分类分组展示。
 *
 * 左侧分类导航 + 右侧 Markdown 渲染，点击导航项切换内容。
 */
import { ref, computed, onMounted } from 'vue'
import { FileText, Loader2, HelpCircle } from 'lucide-vue-next'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

// 构建时加载全部帮助 Markdown 文件（raw 字符串形式）
const helpModules = import.meta.glob('@/content/help/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

interface HelpDoc {
  slug: string
  title: string
  category: string
  order: number
  content: string
}

const docs = ref<HelpDoc[]>([])
const activeSlug = ref('')
const loading = ref(true)

onMounted(() => {
  for (const [path, content] of Object.entries(helpModules)) {
    const slug = path.split('/').pop()!.replace('.md', '')
    // 解析 YAML frontmatter
    const fmMatch = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
    let title = slug
    let category = '其他'
    let order = 99
    let body = content
    if (fmMatch) {
      const fm = fmMatch[1]
      body = fmMatch[2]
      const titleMatch = fm.match(/title:\s*(.+)/)
      const catMatch = fm.match(/category:\s*(.+)/)
      const orderMatch = fm.match(/order:\s*(\d+)/)
      if (titleMatch) title = titleMatch[1].trim()
      if (catMatch) category = catMatch[1].trim()
      if (orderMatch) order = parseInt(orderMatch[1], 10)
    }
    docs.value.push({ slug, title, category, order, content: body })
  }
  // 按 order 升序排序
  docs.value.sort((a, b) => a.order - b.order)
  if (docs.value.length > 0) activeSlug.value = docs.value[0].slug
  loading.value = false
})

// 按分类分组（保持分类内 order 排序）
const groupedDocs = computed(() => {
  const groups: Record<string, HelpDoc[]> = {}
  for (const doc of docs.value) {
    if (!groups[doc.category]) groups[doc.category] = []
    groups[doc.category].push(doc)
  }
  return groups
})

const activeDoc = computed(() =>
  docs.value.find((d) => d.slug === activeSlug.value),
)
</script>

<template>
  <div>
    <PageHeader title="帮助文档" description="系统使用指南与常见问题解答" />

    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="size-6 animate-spin text-muted-foreground" :stroke-width="1.5" />
    </div>

    <div v-else-if="docs.length === 0" class="flex flex-col items-center gap-3 py-16 text-center">
      <HelpCircle class="size-10 text-muted-foreground/40" :stroke-width="1.25" />
      <p class="text-sm text-muted-foreground">暂无帮助文档</p>
    </div>

    <div v-else class="flex flex-col gap-6 lg:flex-row">
      <!-- 左侧分类导航 -->
      <nav class="w-full shrink-0 lg:w-56">
        <div v-for="(groupDocs, category) in groupedDocs" :key="category" class="mb-4">
          <h3 class="mb-2 px-3 text-xs font-medium uppercase tracking-wider text-muted-foreground/70">
            {{ category }}
          </h3>
          <ul class="space-y-1">
            <li v-for="doc in groupDocs" :key="doc.slug">
              <button
                type="button"
                class="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors"
                :class="
                  activeSlug === doc.slug
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                "
                @click="activeSlug = doc.slug"
              >
                <FileText class="size-3.5 shrink-0" :stroke-width="1.5" />
                <span class="truncate">{{ doc.title }}</span>
              </button>
            </li>
          </ul>
        </div>
      </nav>

      <!-- 右侧内容 -->
      <div class="min-w-0 flex-1">
        <Card>
          <CardContent class="p-6">
            <MarkdownRenderer v-if="activeDoc" :content="activeDoc.content" />
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>
