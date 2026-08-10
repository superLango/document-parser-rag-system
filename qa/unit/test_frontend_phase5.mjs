// L1 单元测试：Phase 5 前端契约（M21）
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '../..')
const docs = readFileSync(join(root, 'frontend/src/api/modules/documents.ts'), 'utf8')
const types = readFileSync(join(root, 'frontend/src/api/types.ts'), 'utf8')
const page = readFileSync(join(root, 'frontend/src/views/kb/KbDocumentsPage.tsx'), 'utf8')
const tasks = readFileSync(join(root, 'frontend/src/views/kb/KbTasksPage.tsx'), 'utf8')
const router = readFileSync(join(root, 'frontend/src/router/index.tsx'), 'utf8')

test('documentsApi 契约完整', () => {
  for (const m of ['list', 'upload', 'get', 'markdown', 'layout', 'page', 'reparse', 'remove', 'tasks']) {
    assert.ok(docs.includes(`${m}(`), `缺少 documentsApi.${m}`)
  }
})

test('类型字段完整', () => {
  assert.ok(types.includes('pages_cleaned_at'), 'DocumentItem 缺 pages_cleaned_at')
  assert.ok(types.includes('filename: string | null'), 'DocumentTaskItem 缺 filename')
})

test('文档解析页完整功能标记', () => {
  for (const marker of ['open-upload', 'confirm-upload', 'upload-error', 'progress-', 'layout-json', 'open-layout', 'doc-row-', 'page-preview']) {
    assert.ok(page.includes(marker), `文档页缺少标记 ${marker}`)
  }
})

test('任务列表页挂载', () => {
  assert.ok(tasks.includes('TableRow'), '任务页缺表格行')
  assert.ok(tasks.includes('task-row-'), '任务页缺行 testid')
  assert.ok(router.includes('KbTasksPage'), '路由未挂载任务页')
})
