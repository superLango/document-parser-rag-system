/**
 * 通用 SSE 消费组合式函数
 * 封装 fetch + ReadableStream 消费 Server-Sent Events 的逻辑
 */

import { ref } from 'vue'

export interface SSECallbacks<T = unknown> {
  onChunk?: (data: T) => void
  onDone?: (data: T) => void
  onError?: (message: string) => void
}

export function useSSE() {
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  let controller: AbortController | null = null

  /**
   * 消费 SSE 流
   * @param url 请求地址
   * @param body POST 请求体（可选）
   * @param callbacks 回调函数
   */
  async function consume<T = unknown>(
    url: string,
    callbacks: SSECallbacks<T>,
    body?: Record<string, unknown>,
  ): Promise<void> {
    controller = new AbortController()
    isConnected.value = true
    error.value = null

    try {
      const token = localStorage.getItem('token')
      const response = await fetch(url, {
        method: body ? 'POST' : 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      })

      if (!response.ok) {
        error.value = `HTTP ${response.status}`
        callbacks.onError?.(error.value)
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        error.value = '无法读取响应流'
        callbacks.onError?.(error.value)
        return
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          if (buffer.trim()) {
            handleEvent(buffer, callbacks)
          }
          break
        }
        buffer += decoder.decode(value, { stream: true })
        let separatorIndex: number
        while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
          const eventBlock = buffer.slice(0, separatorIndex)
          buffer = buffer.slice(separatorIndex + 2)
          handleEvent(eventBlock, callbacks)
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // 用户主动取消，不视为错误
        return
      }
      error.value = err instanceof Error ? err.message : '流读取异常'
      callbacks.onError?.(error.value)
    } finally {
      isConnected.value = false
    }
  }

  /** 停止 SSE 流 */
  function stop() {
    if (controller) {
      controller.abort()
      controller = null
    }
    isConnected.value = false
  }

  return { isConnected, error, consume, stop }
}

/**
 * 处理单个 SSE 事件块
 * 支持 type 字段（token/done/error）和 event 字段（progress/done/error）两种格式
 */
function handleEvent<T>(block: string, callbacks: SSECallbacks<T>): void {
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    const trimmed = line.trimStart()
    if (trimmed.startsWith('data:')) {
      dataLines.push(trimmed.slice(5).replace(/^\s/, ''))
    }
  }
  if (dataLines.length === 0) return

  try {
    const payload = JSON.parse(dataLines.join('\n'))
    // QA SSE 格式：type 字段
    if (payload.type === 'token') {
      callbacks.onChunk?.(payload)
    } else if (payload.type === 'done') {
      callbacks.onDone?.(payload)
    } else if (payload.type === 'error') {
      callbacks.onError?.(payload.message ?? '未知错误')
    }
    // 任务进度 SSE 格式：event 字段
    else if (payload.event === 'progress') {
      callbacks.onChunk?.(payload)
    } else if (payload.event === 'done') {
      callbacks.onDone?.(payload)
    } else if (payload.event === 'error') {
      callbacks.onError?.(payload.error ?? payload.message ?? '未知错误')
    }
  } catch {
    // JSON 解析失败，忽略
  }
}
