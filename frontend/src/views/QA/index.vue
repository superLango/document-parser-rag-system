<script setup lang="ts">
import { ref, nextTick, onMounted, computed } from 'vue'
import {
  Send,
  Sparkles,
  User,
  Bot,
  Loader2,
  Trash2,
  FileText,
} from 'lucide-vue-next'
import { qaApi } from '@/api/modules/qa'
import type { Citation } from '@/api/modules/qa'
import type { QAMessage } from '@/api/types'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { PageHeader } from '@/components/ui/page-header'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { EmptyState } from '@/components/ui/empty-state'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'

// 本地消息类型：sources 使用 Citation（对齐后端 SSE done 事件的 citations 字段）
type ChatMessage = Omit<QAMessage, 'sources'> & { sources?: Citation[] }

const messages = ref<ChatMessage[]>([])
const input = ref('')
const loading = ref(false)
const scrollRef = ref<HTMLElement>()

// 高级选项
const enableGraph = ref(true)
const onlyReviewed = ref(false)
const topK = ref(5)

const hasMessages = computed(() => messages.value.length > 1)

async function scrollToBottom() {
  await nextTick()
  if (scrollRef.value) {
    scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  }
}

function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) return
  e.preventDefault()
  ask()
}

async function ask() {
  const question = input.value.trim()
  if (!question || loading.value) return

  // 加入用户消息
  messages.value.push({
    id: `u-${Date.now()}`,
    role: 'user',
    content: question,
    created_at: new Date().toISOString(),
  })
  input.value = ''
  loading.value = true
  await scrollToBottom()

  // 创建空的 assistant 消息，流式追加内容实现打字机效果
  // 注意：必须通过 messages.value[idx] 访问响应式代理对象，
  // 直接修改闭包中的 assistantMsg 引用不会触发 Vue 视图更新。
  const assistantMsgIndex = messages.value.length
  messages.value.push({
    id: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
  })
  await scrollToBottom()

  try {
    await qaApi.askStream(
      question,
      {
        onChunk: (chunk) => {
          // 通过索引访问数组内的响应式代理对象，触发视图更新
          const msg = messages.value[assistantMsgIndex]
          if (msg) {
            msg.content += chunk
            scrollToBottom()
          }
        },
        onDone: (data) => {
          const msg = messages.value[assistantMsgIndex]
          if (msg) {
            msg.sources = data.citations
            scrollToBottom()
          }
        },
        onError: (msg) => {
          const current = messages.value[assistantMsgIndex]
          if (current && !current.content) {
            current.content = `抱歉，回答问题时出错：${msg}`
          }
        },
      },
      { top_k: topK.value },
    )
  } catch {
    const current = messages.value[assistantMsgIndex]
    if (current && !current.content) {
      current.content = '抱歉，回答问题时出错，请稍后重试。'
    }
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

function clearChat() {
  messages.value = []
  initWelcome()
}

function initWelcome() {
  messages.value.push({
    id: 'welcome',
    role: 'assistant',
    content:
      '你好，我是 Hansight 文档智能助手。\n\n我可以基于已解析的技术标准文档回答问题，支持：\n\n- **事实查询**：标准号、参数、术语定义等\n- **关系推理**：实体间的关联关系\n- **文档追溯**：定位到原始文档的具体位置\n\n请输入你的问题开始对话。',
    created_at: new Date().toISOString(),
  })
}

function formatScore(score: number | undefined): string {
  if (score === undefined || score === null) return '-'
  return score.toFixed(3)
}

onMounted(() => {
  initWelcome()
})
</script>

<template>
  <div class="flex h-[calc(100vh-8rem)] flex-col">
    <PageHeader title="智能问答" description="基于 RAG 检索增强的知识问答">
      <template #actions>
        <Button variant="outline" size="sm" :disabled="!hasMessages || loading" @click="clearChat">
          <Trash2 class="size-4" :stroke-width="1.5" />
          清空对话
        </Button>
      </template>
    </PageHeader>

    <!-- 聊天窗口 -->
    <Card class="flex min-h-0 flex-1 flex-col overflow-hidden">
      <!-- 消息区 -->
      <div ref="scrollRef" class="flex-1 overflow-y-auto p-6">
        <div class="mx-auto max-w-4xl space-y-6">
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="flex gap-3"
            :class="msg.role === 'user' ? 'flex-row-reverse' : ''"
          >
            <!-- 头像 -->
            <Avatar class="size-9 shrink-0">
              <AvatarFallback
                :class="
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-foreground'
                "
              >
                <User v-if="msg.role === 'user'" class="size-4" :stroke-width="1.5" />
                <Bot v-else class="size-4" :stroke-width="1.5" />
              </AvatarFallback>
            </Avatar>

            <!-- 消息体 -->
            <div
              class="flex max-w-[80%] flex-col gap-2"
              :class="msg.role === 'user' ? 'items-end' : 'items-start'"
            >
              <!-- 角色标签 -->
              <div class="flex items-center gap-2 px-1">
                <span class="text-xs font-medium text-muted-foreground">
                  {{ msg.role === 'user' ? '用户' : 'Hansight' }}
                </span>
                <Sparkles
                  v-if="msg.role === 'assistant' && loading && msg.id === messages[messages.length - 1]?.id"
                  class="size-3 animate-pulse text-primary"
                  :stroke-width="1.5"
                />
              </div>

              <!-- 消息内容 -->
              <div
                :class="
                  msg.role === 'user'
                    ? 'rounded-md rounded-tr-none bg-primary/10 px-4 py-2.5 text-foreground'
                    : 'rounded-md rounded-tl-none border border-border bg-background px-4 py-2.5 text-foreground'
                "
              >
                <MarkdownRenderer
                  v-if="msg.role === 'assistant' && msg.content"
                  :content="msg.content"
                />
                <p v-else-if="msg.content" class="whitespace-pre-wrap text-sm leading-relaxed">
                  {{ msg.content }}
                </p>
                <div v-else class="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Loader2 class="size-3 animate-spin" :stroke-width="1.5" />
                  <span>正在思考...</span>
                </div>
              </div>

              <!-- 引用来源 -->
              <div
                v-if="msg.sources && msg.sources.length > 0"
                class="w-full space-y-1.5 rounded-md border border-border bg-muted/20 p-3"
              >
                <div class="flex items-center gap-2">
                  <FileText class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
                  <span class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    引用来源
                  </span>
                  <Badge variant="secondary" class="text-[10px]">
                    {{ msg.sources.length }}
                  </Badge>
                </div>
                <div class="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  <div
                    v-for="(src, i) in msg.sources"
                    :key="i"
                    class="flex items-center gap-2 rounded-sm border border-border bg-background px-2 py-1.5 text-xs"
                  >
                    <Badge
                      variant="outline"
                      class="shrink-0 font-mono text-[10px]"
                    >
                      #{{ i + 1 }}
                    </Badge>
                    <div class="min-w-0 flex-1">
                      <p class="truncate font-mono text-foreground" :title="src.document_id">
                        {{ src.document_id || '-' }}
                      </p>
                      <p class="text-[10px] text-muted-foreground">
                        <span v-if="src.source">{{ src.source }}</span>
                        <span v-if="src.score !== undefined">
                          · score: {{ formatScore(src.score) }}
                        </span>
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 空态 -->
          <EmptyState
            v-if="messages.length === 0"
            :icon="Sparkles"
            title="开始一个新对话"
            description="在下方输入框中输入你的问题"
            class="py-16"
          />
        </div>
      </div>

      <!-- 输入区 -->
      <div class="border-t border-border bg-background">
        <div class="mx-auto max-w-4xl space-y-3 p-4">
          <!-- 高级选项 -->
          <div class="flex flex-wrap items-center gap-4 text-xs">
            <label class="flex cursor-pointer items-center gap-2 text-muted-foreground">
              <Switch
                :checked="enableGraph"
                @update:checked="(val) => (enableGraph = val)"
              />
              <span>启用图谱增强</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2 text-muted-foreground">
              <Switch
                :checked="onlyReviewed"
                @update:checked="(val) => (onlyReviewed = val)"
              />
              <span>仅检索已审核文档</span>
            </label>
            <div class="flex items-center gap-2 text-muted-foreground">
              <span>Top-K</span>
              <input
                v-model.number="topK"
                type="number"
                min="1"
                max="20"
                class="h-7 w-16 rounded-md border border-input bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          </div>

          <!-- 输入框 -->
          <div class="flex items-end gap-2">
            <div class="flex-1">
              <Textarea
                v-model="input"
                :rows="2"
                placeholder="输入你的问题，回车发送（Shift+Enter 换行）"
                class="min-h-[60px] resize-none"
                @keyup.enter="handleEnter"
              />
            </div>
            <Button
              size="icon"
              class="h-[60px] w-[60px] shrink-0"
              :disabled="!input.trim() || loading"
              @click="ask"
            >
              <Loader2 v-if="loading" class="size-5 animate-spin" :stroke-width="1.5" />
              <Send v-else class="size-5" :stroke-width="1.5" />
            </Button>
          </div>

          <!-- 底部提示 -->
          <p class="text-center text-[10px] text-muted-foreground">
            Hansight 基于 RAG 检索增强生成，可能存在不准确的信息，请核对引用来源
          </p>
        </div>
      </div>
    </Card>
  </div>
</template>
