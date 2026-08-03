/**
 * Blob 下载工具
 *
 * 统一处理 Blob 文件下载：从 Blob 提取文件名（Content-Disposition 回退到默认值），
 * 创建临时 URL 触发浏览器下载，并自动回收 URL。
 */

/**
 * 触发 Blob 下载
 * @param blob 文件二进制内容
 * @param filename 保存的文件名（含扩展名）
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 释放 URL，避免内存泄漏
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * 带时间戳的文件名生成
 * @example stampFilename('documents', 'xlsx') => 'documents_20260802_153000.xlsx'
 */
export function stampFilename(prefix: string, ext: string): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  return `${prefix}_${ts}.${ext}`
}
