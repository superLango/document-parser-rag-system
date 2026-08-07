<script setup lang="ts">
/**
 * 知识库内智能问答页（含对话历史）
 *
 * 布局：左侧会话列表 + 右侧对话区
 * 数据隔离：所有检索通过 /kbs/{kb_id}/qa/stream，后端 kb_id 透传至
 *           vector_store（KB 专属 Collection）+ graph_store（KB 专属 space）+ 缓存键
 * 历史持久化：每轮问答自动持久化到会话历史，后端流式完成后回传 session_id
 * 权限：viewer+ 可问答
 */
import { ref, nextTick, onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Send,
  Sparkles,
  User,
  Bot,
  Loader2,
  Trash2,
  FileText,
  ShieldCheck,
  Plus,
  MessageSquare,
  Download,
  Pencil,
  Check,
  X,
  AlertCircle,
} from 'lucide-vue-next'
import { kbApi, type KbQaCitation, type KbQaSession, type KbQaMessage } from '@/api/modules/kb'
import { useKbStore } from '@/stores/kb'
import { downloadBlob } from '@/composables/useDownload'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { PageHeader } from '@/components/ui/page-header'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { EmptyState } from '@/components/ui/empty-state'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toast'
import { confirm } from '@/composables/useConfirm'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sources?: KbQaCitation[]
  created_at: string
}

const route = useRoute()
const kbStore = useKbStore()
const kbId = computed(() => route.params.kb_id as string)

// 会话列表
const sessions = ref<KbQaSession[]>([])
const sessionsLoading = ref(false)
const currentSessionId = ref<string | null>(null)
const renamingId = ref<string | null>(null)
const renameValue = ref('')

// 对话区
const messages = ref<ChatMessage[]>([])
const input = ref('')
const loading = ref(false)
const scrollRef = ref<HTMLElement>()

// 高级选项
const enableGraph = ref(false)
const enableReranker = ref(false)
const topK = ref(8)

const hasMessages = computed(() => messages.value.length > 1)

async function fetchSessions() {
  sessionsLoading.value = true
  try {
    const res = await kbApi.listQaSessions(kbId.value, { page: 1, page_size: 50 })
    sessions.value = res.items
  } catch {
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

async function selectSession(session: KbQaSession) {
  if (loading.value) return
  currentSessionId.value = session.id
  messages.value = []
  try {
    const res = await kbApi.listQaMessages(kbId.value, session.id)
    messages.value = res.items.map((m: KbQaMessage) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      sources: m.citations ?? undefined,
      created_at: m.created_at,
    }))
    await scrollToBottom()
  } catch {
    // 错误已由拦截器提示
  }
}

async function newSession() {
  if (loading.value) return
  currentSessionId.value = null
  messages.value = []
  initWelcome()
}

async function deleteSession(session: KbQaSession) {
  if (!await confirm(`确定删除会话「${session.title}」？`)) return
  try {
    await kbApi.deleteQaSession(kbId.value, session.id)
    toast.success('会话已删除')
    if (currentSessionId.value === session.id) {
      currentSessionId.value = null
      messages.value = []
    }
    await fetchSessions()
  } catch {
    // 错误已由拦截器提示
  }
}

function startRename(session: KbQaSession) {
  renamingId.value = session.id
  renameValue.value = session.title
}

async function confirmRename(session: KbQaSession) {
  const title = renameValue.value.trim()
  if (!title) {
    renamingId.value = null
    return
  }
  try {
    await kbApi.renameQaSession(kbId.value, session.id, title)
    session.title = title
    toast.success('已重命名')
  } catch {
    // 错误已由拦截器提示
  } finally {
    renamingId.value = null
  }
}

async function exportSession(session: KbQaSession) {
  try {
    const blob = await kbApi.exportQaSession(kbId.value, session.id, 'markdown')
    downloadBlob(blob, `qa_${session.id.slice(0, 8)}.md`)
  } catch {
    // 错误已由拦截器提示
  }
}

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

  messages.value.push({
    id: `u-${Date.now()}`,
    role: 'user',
    content: question,
    created_at: new Date().toISOString(),
  })
  input.value = ''
  loading.value = true
  await scrollToBottom()

  const assistantIdx = messages.value.length
  messages.value.push({
    id: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
  })
  await scrollToBottom()

  try {
    await kbApi.askStream(
      kbId.value,
      question,
      {
        onChunk: (chunk) => {
          const msg = messages.value[assistantIdx]
          if (msg) {
            msg.content += chunk
            scrollToBottom()
          }
        },
        onDone: (sessionId, citations) => {
          if (sessionId && sessionId !== currentSessionId.value) {
            currentSessionId.value = sessionId
          }
          if (citations && citations.length > 0) {
            const msg = messages.value[assistantIdx]
            if (msg) {
              msg.sources = citations
            }
          }
          scrollToBottom()
          fetchSessions()
        },
        onError: (msg) => {
          const current = messages.value[assistantIdx]
          if (current && !current.content) {
            current.content = `抱歉，回答问题时出错：${msg}`
          }
        },
      },
      {
        top_k: topK.value,
        use_graph: enableGraph.value,
        use_reranker: enableReranker.value,
        session_id: currentSessionId.value ?? undefined,
      },
    )
  } catch {
    const current = messages.value[assistantIdx]
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
  currentSessionId.value = null
  initWelcome()
}

function initWelcome() {
  messages.value.push({
    id: 'welcome',
    role: 'assistant',
    content: `你好，我是 HansonDOC 文档智能助手。\n\n我正在基于知识库「${kbStore.currentKb?.name || '当前'}」回答问题，支持：\n\n- **事实查询**：标准号、参数、术语定义等\n- **关系推理**：实体间的关联关系\n- **文档追溯**：定位到原始文档的具体位置\n\n检索范围严格限定在当前知识库内，请输入你的问题开始对话。`,
    created_at: new Date().toISOString(),
  })
}

function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return value
  }
}

function formatScore(score: number | undefined): string {
  if (score === undefined || score === null) return '-'
  return score.toFixed(3)
}

function sourceLabel(source: string): string {
  const map: Record<string, string> = {
    vector: '向量检索',
    graph: '图谱检索',
    llamaindex: '索引检索',
  }
  return map[source] || source
}

onMounted(() => {
  initWelcome()
  fetchSessions()
})
</script>

<template>
  <div class="flex h-[calc(100vh-8rem)] gap-4">
    <!-- 左侧：会话列表 -->
    <Card class="flex w-72 shrink-0 flex-col overflow-hidden shadow-lg">
      <div class="flex items-center justify-between border-b border-border/50 bg-gradient-to-r from-primary/5 to-transparent p-3">
        <div class="flex items-center gap-2">
          <MessageSquare class="size-4 text-primary" :stroke-width="1.5" />
          <span class="text-sm font-semibold text-foreground">对话历史</span>
        </div>
        <Button variant="ghost" size="sm" :disabled="loading" class="hover:bg-primary/10 hover:text-primary transition-all duration-200" @click="newSession">
          <Plus class="size-4" :stroke-width="1.5" />
        </Button>
      </div>

      <div class="flex-1 overflow-y-auto p-2">
        <div v-if="sessionsLoading" class="space-y-2 p-1">
          <Skeleton v-for="i in 4" :key="i" class="h-14 w-full rounded-lg" />
        </div>
        <EmptyState
          v-else-if="sessions.length === 0"
          :icon="MessageSquare"
          title="暂无会话"
          description="开始问答后将自动保存"
          class="py-8"
        />
        <div v-else class="space-y-1.5">
          <div
            v-for="s in sessions"
            :key="s.id"
            class="group relative cursor-pointer rounded-lg border border-transparent px-3 py-2.5 transition-all duration-300 hover:border-primary/20 hover:bg-primary/5 hover:shadow-sm hover:translate-x-0.5"
            :class="currentSessionId === s.id ? 'border-primary/40 bg-primary/10 shadow-sm shadow-primary/10' : ''"
            @click="selectSession(s)"
          >
            <div v-if="currentSessionId === s.id" class="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-primary to-primary/60"></div>
            <!-- 重命名模式 -->
            <div v-if="renamingId === s.id" class="flex items-center gap-1" @click.stop>
              <input
                v-model="renameValue"
                class="min-w-0 flex-1 rounded border border-input bg-background px-1.5 py-0.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                @keyup.enter="confirmRename(s)"
              />
              <Button variant="ghost" size="icon" class="size-6" @click="confirmRename(s)">
                <Check class="size-3" :stroke-width="2" />
              </Button>
              <Button variant="ghost" size="icon" class="size-6" @click="renamingId = null">
                <X class="size-3" :stroke-width="2" />
              </Button>
            </div>
            <!-- 正常显示 -->
            <template v-else>
              <div class="flex items-start gap-1">
                <p class="min-w-0 flex-1 truncate text-sm font-medium text-foreground" :title="s.title">
                  {{ s.title }}
                </p>
                <!-- 悬浮操作 -->
                <div class="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100">
                  <Button variant="ghost" size="icon" class="size-6" title="重命名" @click.stop="startRename(s)">
                    <Pencil class="size-3" :stroke-width="1.5" />
                  </Button>
                  <Button variant="ghost" size="icon" class="size-6" title="导出" @click.stop="exportSession(s)">
                    <Download class="size-3" :stroke-width="1.5" />
                  </Button>
                  <Button variant="ghost" size="icon" class="size-6" title="删除" @click.stop="deleteSession(s)">
                    <Trash2 class="size-3 text-danger" :stroke-width="1.5" />
                  </Button>
                </div>
              </div>
              <div class="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>{{ s.message_count }} 条消息</span>
                <span v-if="s.last_message_at">· {{ formatTime(s.last_message_at) }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Card>

    <!-- 右侧：对话区 -->
    <Card class="flex min-h-0 flex-1 flex-col overflow-hidden shadow-lg">
      <!-- 顶栏 -->
      <div class="flex items-center justify-between border-b border-border/50 bg-gradient-to-r from-card via-card to-muted/30 px-4 py-3">
        <div class="flex items-center gap-3">
          <div class="flex items-center justify-center size-8 rounded-lg bg-primary/10">
            <Bot class="size-4 text-primary" :stroke-width="1.5" />
          </div>
          <span class="text-sm font-semibold text-foreground">
            {{ currentSessionId ? sessions.find(s => s.id === currentSessionId)?.title || '对话中' : '新对话' }}
          </span>
          <Badge variant="secondary" class="gap-1.5 bg-primary/10 text-primary border-primary/20 hover:bg-primary/15">
            <ShieldCheck class="size-3" :stroke-width="1.5" />
            KB 隔离
          </Badge>
        </div>
        <Button variant="outline" size="sm" :disabled="!hasMessages || loading" class="border-border/50 hover:border-destructive/30 hover:text-destructive hover:bg-destructive/5 transition-all duration-200" @click="clearChat">
          <Trash2 class="size-4" :stroke-width="1.5" />
          清空
        </Button>
      </div>

      <!-- 消息区 -->
      <div ref="scrollRef" class="flex-1 overflow-y-auto p-6 bg-gradient-to-b from-background/50 to-background">
        <div class="mx-auto max-w-4xl space-y-8">
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="flex gap-4 animate-in fade-in-0 slide-in-from-bottom-2 duration-300"
            :class="msg.role === 'user' ? 'flex-row-reverse' : ''"
          >
            <!-- 头像 -->
            <Avatar class="size-10 shrink-0 ring-2 ring-transparent transition-all duration-200"
              :class="msg.role === 'user' ? 'ring-primary/20' : 'ring-primary/10'">
              <AvatarFallback
                :class="
                  msg.role === 'user'
                    ? 'bg-gradient-to-br from-primary to-primary/80 text-primary-foreground shadow-lg shadow-primary/25'
                    : 'bg-gradient-to-br from-muted to-muted/80 text-foreground shadow-md'
                "
                class="rounded-xl"
              >
                <User v-if="msg.role === 'user'" class="size-4.5" :stroke-width="1.5" />
                <Bot v-else class="size-4.5" :stroke-width="1.5" />
              </AvatarFallback>
            </Avatar>

            <!-- 消息体 -->
            <div
              class="flex max-w-[80%] flex-col gap-2.5"
              :class="msg.role === 'user' ? 'items-end' : 'items-start'"
            >
              <div class="flex items-center gap-2 px-1">
                <span class="text-xs font-medium" :class="msg.role === 'user' ? 'text-primary' : 'text-muted-foreground'">
                  {{ msg.role === 'user' ? '你' : 'HansonDOC AI' }}
                </span>
                <span v-if="msg.created_at && msg.id !== 'welcome'" class="text-[10px] text-muted-foreground/70">
                  {{ formatTime(msg.created_at) }}
                </span>
                <Sparkles
                  v-if="msg.role === 'assistant' && loading && msg.id === messages[messages.length - 1]?.id"
                  class="size-3.5 animate-pulse text-primary"
                  :stroke-width="1.5"
                />
              </div>

              <!-- 消息内容 -->
              <div
                :class="
                  msg.role === 'user'
                    ? 'rounded-2xl rounded-tr-md bg-gradient-to-br from-primary to-primary/90 px-5 py-3 text-primary-foreground shadow-lg shadow-primary/20 hover:shadow-xl hover:shadow-primary/25 transition-shadow duration-200'
                    : 'rounded-2xl rounded-tl-md border border-border/60 bg-card/80 backdrop-blur-sm px-5 py-3.5 text-foreground shadow-md hover:shadow-lg transition-shadow duration-200'
                "
              >
                <MarkdownRenderer
                  v-if="msg.role === 'assistant' && msg.content"
                  :content="msg.content"
                />
                <p v-else-if="msg.content" class="whitespace-pre-wrap text-sm leading-relaxed">
                  {{ msg.content }}
                </p>
                <div v-else class="flex items-center gap-2 text-sm text-muted-foreground">
                  <div class="flex gap-1">
                    <span class="size-1.5 rounded-full bg-primary animate-bounce" style="animation-delay: 0ms"></span>
                    <span class="size-1.5 rounded-full bg-primary animate-bounce" style="animation-delay: 150ms"></span>
                    <span class="size-1.5 rounded-full bg-primary animate-bounce" style="animation-delay: 300ms"></span>
                  </div>
                  <span>正在思考...</span>
                </div>
              </div>

              <!-- 引用来源 -->
              <div
                v-if="msg.sources && msg.sources.length > 0"
                class="w-full space-y-2 rounded-xl border border-primary/10 bg-gradient-to-br from-primary/5 to-transparent p-4 shadow-sm"
              >
                <div class="flex items-center gap-2">
                  <div class="flex items-center justify-center size-6 rounded-md bg-primary/10">
                    <FileText class="size-3.5 text-primary" :stroke-width="1.5" />
                  </div>
                  <span class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    引用来源
                  </span>
                  <Badge variant="secondary" class="text-[10px] bg-primary/15 text-primary border-primary/20 font-mono">
                    {{ msg.sources.length }} 条
                  </Badge>
                </div>
                <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div
                    v-for="(src, i) in msg.sources"
                    :key="i"
                    class="group flex items-start gap-2.5 rounded-lg border border-border/50 bg-card/60 backdrop-blur-sm px-3 py-2.5 text-xs transition-all duration-200 hover:border-primary/20 hover:bg-card/90 hover:shadow-sm cursor-default"
                  >
                    <Badge variant="outline" class="shrink-0 font-mono text-[10px] bg-primary/10 text-primary border-primary/20 font-semibold min-w-[28px] flex items-center justify-center">
                      #{{ i + 1 }}
                    </Badge>
                    <div class="min-w-0 flex-1">
                      <p class="line-clamp-2 text-foreground leading-relaxed group-hover:text-foreground/90 transition-colors" :title="src.content">
                        {{ src.content?.slice(0, 80) || src.chunk_id || '-' }}{{ src.content?.length > 80 ? '...' : '' }}
                      </p>
                      <p class="mt-1 text-[10px] text-muted-foreground flex items-center gap-1.5">
                        <span v-if="src.source" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                          {{ sourceLabel(src.source) }}
                        </span>
                        <span v-if="src.score !== undefined" class="flex items-center gap-1">
                          <span class="text-primary/70">相关度:</span>
                          <span class="font-mono font-medium">{{ formatScore(src.score) }}</span>
                        </span>
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="border-t border-border/50 bg-gradient-to-t from-card to-card/80 backdrop-blur-sm">
        <div class="mx-auto max-w-4xl space-y-3 p-4">
          <!-- 高级选项 -->
          <div class="flex flex-wrap items-center gap-4 text-xs">
            <Tooltip>
              <template #trigger>
                <label class="flex cursor-pointer items-center gap-2 text-muted-foreground transition-colors hover:text-foreground">
                  <Switch
                    :checked="enableGraph"
                    @update:checked="(val) => (enableGraph = val)"
                    class="data-[state=checked]:bg-primary"
                  />
                  <span>图谱增强</span>
                </label>
              </template>
              <span>启用知识图谱实体检索辅助回答（KB模式下部分功能受限）</span>
            </Tooltip>
            <Tooltip>
              <template #trigger>
                <label class="flex cursor-not-allowed items-center gap-2 text-muted-foreground/50">
                  <Switch
                    :checked="false"
                    :disabled="true"
                  />
                  <span>结果重排</span>
                  <AlertCircle class="size-3 text-muted-foreground/50" />
                </label>
              </template>
              <span>Cross-Encoder 重排模型待配置，功能暂未实现</span>
            </Tooltip>
            <div class="flex items-center gap-2 text-muted-foreground">
              <span>Top-K</span>
              <div class="flex items-center gap-2">
                <input
                  v-model.number="topK"
                  type="range"
                  min="3"
                  max="20"
                  class="h-1.5 w-24 cursor-pointer accent-primary"
                />
                <span class="w-6 text-center font-mono text-xs text-foreground bg-muted px-1.5 py-0.5 rounded font-semibold">{{ topK }}</span>
              </div>
            </div>
          </div>

          <!-- 输入框 -->
          <div class="group flex items-end gap-3 p-1.5 rounded-2xl border-2 border-border/50 bg-card shadow-lg transition-all duration-300 hover:border-primary/30 hover:shadow-xl focus-within:border-primary/50 focus-within:shadow-xl focus-within:shadow-primary/10">
            <div class="flex-1">
              <Textarea
                v-model="input"
                :rows="2"
                placeholder="输入你的问题，回车发送（Shift+Enter 换行）"
                class="min-h-[60px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 px-3 py-2.5 text-sm leading-relaxed placeholder:text-muted-foreground/60"
                @keyup.enter="handleEnter"
              />
            </div>
            <Button
              size="icon"
              class="h-[60px] w-[60px] shrink-0 rounded-xl bg-gradient-to-br from-primary to-primary/90 text-primary-foreground shadow-lg shadow-primary/25 transition-all duration-200 hover:shadow-xl hover:shadow-primary/35 hover:scale-105 active:scale-95 disabled:opacity-50 disabled:shadow-none disabled:hover:scale-100"
              :disabled="!input.trim() || loading"
              @click="ask"
            >
              <Loader2 v-if="loading" class="size-5 animate-spin" :stroke-width="1.5" />
              <Send v-else class="size-5" :stroke-width="1.5" />
            </Button>
          </div>

          <p class="text-center text-[10px] text-muted-foreground/70">
            <span class="inline-flex items-center gap-1">
              <ShieldCheck class="size-3 text-primary/70" :stroke-width="1.5" />
              检索范围限定在当前知识库内
            </span>
            · HansonDOC 基于 RAG 生成，可能存在不准确信息，请核对引用来源
          </p>
        </div>
      </div>
    </Card>
  </div>
</template>
