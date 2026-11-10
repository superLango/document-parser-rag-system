export const DOCUMENT_STATUS_META: Record<
  string,
  { label: string; variant: 'success' | 'warning' | 'destructive' | 'secondary' | 'outline' }
> = {
  queued: { label: '待解析', variant: 'outline' },
  parsing: { label: '解析中', variant: 'warning' },
  completed: { label: '已完成', variant: 'success' },
  failed: { label: '失败', variant: 'destructive' },
  deleted: { label: '已删除', variant: 'secondary' },
}

export const PROCESS_STEPS = ['queued', 'rendering', 'layout', 'ocr', 'rebuild', 'completed']

export const PROCESS_LABELS: Record<string, string> = {
  queued: '排队中',
  rendering: '页面渲染',
  layout: '版面分析',
  ocr: 'OCR 识别',
  rebuild: '版面重建',
  completed: '已完成',
  failed: '失败',
}

export const TERMINAL_STATUSES = new Set(['completed', 'failed', 'deleted'])

export function progressPercent(processStatus: string | null | undefined): number {
  if (processStatus === 'failed') return 0
  const idx = PROCESS_STEPS.indexOf(processStatus ?? '')
  if (idx < 0) return 0
  return Math.round((idx / (PROCESS_STEPS.length - 1)) * 100)
}

export function pageProgressPercent(
  page: number | null | undefined,
  total: number | null | undefined,
): number | null {
  if (!page || !total || page < 1 || total < 1) return null
  return Math.min(100, Math.round((page / total) * 100))
}

export function progressPercentForDoc(
  processStatus: string | null | undefined,
  page: number | null | undefined,
  total: number | null | undefined,
): number {
  if (processStatus === 'completed') return 100
  const stageIdx = PROCESS_STEPS.indexOf(processStatus ?? '')
  if (stageIdx < 0) return 0
  const stageSpan = 100 / (PROCESS_STEPS.length - 1)
  let base = stageIdx * stageSpan
  if (page && total && total > 0) {
    base += Math.min(1, page / total) * stageSpan
  }
  return Math.min(99, Math.round(base))
}

export function pageProgressText(
  page: number | null | undefined,
  total: number | null | undefined,
): string | null {
  if (!page || !total || total < 1) return null
  return '第 ' + Math.min(page, total) + ' / ' + total + ' 页'
}
