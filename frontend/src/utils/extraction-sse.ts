/**
 * 抽取专用 SSE 流解析工具
 *
 * 与 qa 模块的 SSE 不同，抽取 SSE 事件类型多样：
 * - schema_info: Schema 信息事件
 * - progress: 进度事件
 * - chunk_result: 单块抽取完成事件
 * - chunk_error: 单块抽取失败事件
 * - done: 抽取完成事件
 * - warning: 警告事件
 * - error: 错误事件
 *
 * 所有事件均以 `data: {JSON}\n\n` 格式推送，JSON 中包含 `type` 字段区分事件类型
 */

import type { extractionApi } from '@/api/modules/extraction'

type Callbacks = Parameters<typeof extractionApi.extractStream>[1]

/**
 * 解析抽取 SSE 流，根据事件类型分发到对应回调
 */
export async function parseExtractionSSEStream(
  response: Response,
  callbacks: Callbacks,
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) {
    callbacks.onError?.('无法读取响应流')
    return
  }

  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        // 处理缓冲区中剩余的事件块
        if (buffer.trim()) {
          handleEventBlock(buffer, callbacks)
        }
        break
      }
      buffer += decoder.decode(value, { stream: true })

      // SSE 事件以 \n\n 分隔
      let separatorIndex: number
      while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
        const eventBlock = buffer.slice(0, separatorIndex)
        buffer = buffer.slice(separatorIndex + 2)
        handleEventBlock(eventBlock, callbacks)
      }
    }
  } catch (err) {
    callbacks.onError?.(err instanceof Error ? err.message : '流读取异常')
  }
}

/**
 * 处理单个 SSE 事件块
 * 解析 data: 前缀的 JSON 内容，根据 type 字段分发回调
 */
function handleEventBlock(block: string, callbacks: Callbacks): void {
  // 收集所有 data: 行（SSE 规范允许同一事件跨多行）
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
    const eventType: string = payload.type || ''

    switch (eventType) {
      case 'schema_info':
        callbacks.onSchemaInfo?.({
          schema_name: payload.schema_name ?? '',
          schema_description: payload.schema_description ?? '',
          field_count: payload.field_count ?? 0,
          has_samples: !!payload.has_samples,
        })
        break

      case 'progress':
        callbacks.onProgress?.({
          progress: payload.progress ?? 0,
          message: payload.message ?? '',
          chunk_index: payload.chunk_index ?? 0,
          total_chunks: payload.total_chunks ?? 0,
        })
        break

      case 'chunk_result':
        callbacks.onChunkResult?.({
          data: payload.data ?? {},
          chunk_index: payload.chunk_index ?? 0,
          progress: payload.progress ?? 0,
          message: payload.message ?? '',
        })
        break

      case 'chunk_error':
        callbacks.onChunkError?.({
          chunk_index: payload.chunk_index ?? 0,
          error: payload.error ?? '',
          message: payload.message ?? '',
        })
        break

      case 'done':
        callbacks.onDone?.({
          data: payload.data ?? {},
          missing: payload.missing ?? [],
          progress: payload.progress ?? 100,
          message: payload.message ?? '',
        })
        break

      case 'warning':
        callbacks.onWarning?.({ message: payload.message ?? '' })
        break

      case 'error':
        callbacks.onError?.(payload.message ?? '抽取失败')
        break

      default:
        // 未知事件类型，忽略
        break
    }
  } catch {
    // JSON 解析失败，忽略该事件块
  }
}
