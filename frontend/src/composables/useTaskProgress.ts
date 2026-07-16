import { ref, onUnmounted } from 'vue'

/**
 * 任务进度 SSE 事件数据
 * 后端 stream_task_progress 端点事件格式（与 QA SSE 不同）：
 *   data: {"event":"progress","state":"PROGRESS","progress":50,"message":"处理中"}
 *   data: {"event":"done","state":"SUCCESS","progress":100,"result":{...}}
 *   data: {"event":"error","state":"FAILURE","error":"..."}
 */
interface TaskProgressEvent {
  event: 'progress' | 'done' | 'error'
  state?: string
  progress?: number
  message?: string
  result?: Record<string, unknown> | null
  error?: string
}

export type TaskProgressStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'

/**
 * 任务进度 SSE 消费组合式函数
 *
 * 通过 fetch 消费 /api/v1/tasks/{id}/stream 的 SSE 流，实时反映任务进度。
 * 因后端任务进度事件格式（event/state 字段）与 utils/sse.ts 的 parseSSEStream
 * （type 字段）不同，此处实现独立的流解析逻辑。
 */
export function useTaskProgress() {
  const progress = ref(0)
  const status = ref<TaskProgressStatus>('idle')
  const message = ref('')
  const result = ref<Record<string, unknown> | null>(null)
  let abortController: AbortController | null = null

  /**
   * 将后端 state 映射为前端 status
   */
  function mapStatus(state: string | undefined, event: string): TaskProgressStatus {
    if (event === 'done') return 'completed'
    if (event === 'error') return 'failed'
    const s = (state || '').toUpperCase()
    if (s === 'PENDING') return 'queued'
    if (s === 'PROGRESS' || s === 'STARTED') return 'running'
    return status.value
  }

  /**
   * 解析单个 SSE 事件块并更新状态
   */
  function handleEventBlock(block: string): void {
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      const trimmed = line.trimStart()
      if (trimmed.startsWith('data:')) {
        dataLines.push(trimmed.slice(5).replace(/^\s/, ''))
      }
    }
    if (dataLines.length === 0) return

    let payload: TaskProgressEvent
    try {
      payload = JSON.parse(dataLines.join('\n'))
    } catch {
      // JSON 解析失败（如心跳注释），忽略
      return
    }

    if (payload.progress !== undefined) {
      progress.value = payload.progress
    }
    if (payload.message) {
      message.value = payload.message
    }
    status.value = mapStatus(payload.state, payload.event)

    if (payload.event === 'done') {
      progress.value = 100
      status.value = 'completed'
      result.value = payload.result ?? null
    } else if (payload.event === 'error') {
      status.value = 'failed'
      message.value = payload.error || '任务执行失败'
    }
  }

  /**
   * 开始监听任务进度
   */
  async function startProgress(taskId: string): Promise<void> {
    // 重置状态
    progress.value = 0
    status.value = 'queued'
    message.value = '等待中'
    result.value = null

    const token = localStorage.getItem('token')
    abortController = new AbortController()
    try {
      const response = await fetch(`/api/v1/tasks/${taskId}/stream`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: abortController.signal,
      })
      if (!response.ok || !response.body) {
        status.value = 'failed'
        message.value = `HTTP ${response.status}`
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          if (buffer.trim()) handleEventBlock(buffer)
          break
        }
        buffer += decoder.decode(value, { stream: true })
        let separatorIndex: number
        while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
          const eventBlock = buffer.slice(0, separatorIndex)
          buffer = buffer.slice(separatorIndex + 2)
          handleEventBlock(eventBlock)
        }
      }
    } catch (err) {
      // 主动中止不算失败
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (err instanceof Error && err.name === 'AbortError') return
      status.value = 'failed'
      message.value = err instanceof Error ? err.message : '流读取异常'
    }
  }

  /**
   * 停止监听
   */
  function stopProgress(): void {
    abortController?.abort()
    abortController = null
  }

  onUnmounted(() => stopProgress())

  return { progress, status, message, result, startProgress, stopProgress }
}
