/**
 * SSE 流解析工具
 * 基于 fetch + ReadableStream 实现，支持 POST 请求消费 Server-Sent Events
 */

/**
 * 解析 SSE 流，从 fetch Response 中读取并分发事件
 * @param response fetch 返回的 Response 对象
 * @param onChunk 收到 token 事件时回调
 * @param onDone 收到 done 事件时回调
 * @param onError 收到 error 事件或流异常时回调
 */
export async function parseSSEStream(
  response: Response,
  onChunk: (content: string) => void,
  onDone: (data: { answer: string; citations: any[] }) => void,
  onError: (message: string) => void,
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) {
    onError('无法读取响应流')
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
          handleEventBlock(buffer, onChunk, onDone, onError)
        }
        break
      }
      buffer += decoder.decode(value, { stream: true })

      // SSE 事件以 \n\n 分隔
      let separatorIndex: number
      while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
        const eventBlock = buffer.slice(0, separatorIndex)
        buffer = buffer.slice(separatorIndex + 2)
        handleEventBlock(eventBlock, onChunk, onDone, onError)
      }
    }
  } catch (err) {
    onError(err instanceof Error ? err.message : '流读取异常')
  }
}

/**
 * 处理单个 SSE 事件块
 * 解析 data: 前缀的 JSON 内容，根据字段判断事件类型并分发回调
 *
 * 后端事件格式（与 backend/app/api/v1/endpoints/qa.py 对齐）：
 * - 文本分片：``{"chunk": "..."}``
 * - 结束标记：``{"done": true}``
 * - 错误信息：``{"error": "..."}``
 */
function handleEventBlock(
  block: string,
  onChunk: (content: string) => void,
  onDone: (data: { answer: string; citations: any[] }) => void,
  onError: (message: string) => void,
): void {
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
    if (typeof payload.chunk === 'string') {
      onChunk(payload.chunk)
    } else if (payload.done === true) {
      onDone({
        answer: payload.answer ?? '',
        citations: payload.citations ?? [],
      })
    } else if (typeof payload.error === 'string') {
      onError(payload.error)
    }
  } catch {
    // JSON 解析失败，忽略该事件块（如心跳注释等）
  }
}
