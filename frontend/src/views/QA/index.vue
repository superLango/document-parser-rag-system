<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { Promotion } from '@element-plus/icons-vue'
import { qaApi } from '@/api/modules/qa'
import type { QAMessage } from '@/api/types'

const messages = ref<QAMessage[]>([])
const input = ref('')
const loading = ref(false)
const scrollRef = ref<HTMLElement>()

async function scrollToBottom() {
  await nextTick()
  if (scrollRef.value) {
    scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  }
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

  try {
    const res = await qaApi.ask({ question, top_k: 5 })
    messages.value.push({
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: res.answer,
      sources: res.sources,
      created_at: new Date().toISOString(),
    })
  } catch {
    messages.value.push({
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '抱歉，回答问题时出错，请稍后重试。',
      created_at: new Date().toISOString(),
    })
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

onMounted(() => {
  // 欢迎语
  messages.value.push({
    id: 'welcome',
    role: 'assistant',
    content: '你好，我是文档智能助手。可基于已解析的技术标准文档回答问题，请输入你的问题。',
    created_at: new Date().toISOString(),
  })
})
</script>

<template>
  <div class="qa">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">智能问答</h2>
        <p class="page-desc">基于 RAG 检索增强的知识问答</p>
      </div>
    </div>

    <!-- 聊天窗口 -->
    <div class="bp-card chat-card">
      <!-- 消息区 -->
      <div ref="scrollRef" class="messages">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message"
          :class="`is-${msg.role}`"
        >
          <div class="message-avatar">
            <span v-if="msg.role === 'user'">U</span>
            <span v-else>AI</span>
          </div>
          <div class="message-body">
            <div class="message-content">{{ msg.content }}</div>
            <div v-if="msg.sources?.length" class="message-sources">
              <div class="sources-label mono">引用来源</div>
              <div
                v-for="(src, i) in msg.sources"
                :key="i"
                class="source-item"
              >
                <span class="mono source-doc">{{ src.document_title }}</span>
                <span class="source-page">第 {{ src.page }} 页</span>
                <span class="mono source-score">score: {{ src.score.toFixed(2) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="loading" class="message is-assistant">
          <div class="message-avatar"><span>AI</span></div>
          <div class="message-body">
            <div class="typing">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-bar">
        <el-input
          v-model="input"
          type="textarea"
          :rows="1"
          resize="none"
          placeholder="输入你的问题，回车发送"
          @keyup.enter="ask"
        />
        <el-button type="primary" class="btn-glow send-btn" :loading="loading" @click="ask">
          <el-icon><Promotion /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.page-header {
  margin-bottom: 24px;

  .page-title {
    font-size: var(--fs-xl);
    font-weight: 600;
    margin-bottom: 4px;
  }

  .page-desc {
    font-size: var(--fs-sm);
    color: var(--text-secondary);
  }
}

.chat-card {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 200px);
  min-height: 400px;
  overflow: hidden;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  max-width: 85%;

  &.is-user {
    margin-left: auto;
    flex-direction: row-reverse;

    .message-avatar {
      background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-dim));
      color: #FFFFFF;
    }

    .message-content {
      background: rgba(37, 99, 235, 0.08);
      border-color: rgba(37, 99, 235, 0.2);
    }
  }

  &.is-assistant {
    .message-avatar {
      background: var(--bg-surface-hover);
      color: var(--accent-primary);
      border: 1px solid var(--border-base);
    }

    .message-content {
      background: var(--bg-surface-hover);
      border: 1px solid var(--border-light);
    }
  }
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
}

.message-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-content {
  padding: 12px 16px;
  border-radius: var(--radius-md);
  font-size: var(--fs-sm);
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-sources {
  padding: 8px 12px;
  background: var(--bg-base);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-light);

  .sources-label {
    font-size: var(--fs-xs);
    color: var(--text-muted);
    margin-bottom: 6px;
    letter-spacing: 0.05em;
  }

  .source-item {
    display: flex;
    gap: 12px;
    align-items: center;
    font-size: var(--fs-xs);
    padding: 2px 0;

    .source-doc {
      color: var(--accent-primary);
      flex: 1;
    }

    .source-page {
      color: var(--text-secondary);
    }

    .source-score {
      color: var(--text-muted);
    }
  }
}

.typing {
  display: flex;
  gap: 4px;
  padding: 12px 16px;

  span {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent-primary);
    animation: typing-bounce 1.2s infinite;
  }

  span:nth-child(2) { animation-delay: 0.2s; }
  span:nth-child(3) { animation-delay: 0.4s; }
}

@keyframes typing-bounce {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-4px); }
}

.input-bar {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-base);

  :deep(.el-textarea__inner) {
    background-color: var(--bg-base);
    border-color: var(--border-base);
    color: var(--text-primary);
    min-height: 40px !important;
    padding: 10px 14px;
  }

  .send-btn {
    height: 40px;
    width: 44px;
    padding: 0;
    flex-shrink: 0;
    font-size: 18px;
  }
}
</style>
