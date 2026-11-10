import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '@/components/ui/toast'
import IntegrationTaskResultPage from './IntegrationTaskResultPage'

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  sessionToken: vi.fn(),
  retrigger: vi.fn(),
}))

vi.mock('@/api/modules/integration', () => ({
  integrationApi: {
    status: mocks.status,
    sessionToken: mocks.sessionToken,
    retrigger: mocks.retrigger,
  },
}))

vi.mock('@/stores/auth', () => ({
  isAuthenticated: () => true,
  useAuthStore: () => ({
    requireAuth: false,
    loadPublicConfig: vi.fn(),
  }),
}))

vi.mock('@/views/KbExtractionDetailPage', () => ({
  default: ({ openFeedbackSignal }: { openFeedbackSignal?: number }) => (
    <div data-testid="extraction-detail" data-signal={openFeedbackSignal ?? 0} />
  ),
}))

const TASK = {
  task_id: 'task-1',
  kb_id: 'kb-1',
  document_id: '11111111-1111-1111-1111-111111111111',
  prompt_id: 'prompt-1',
  schema_template_id: 'schema-1',
  filename: 'demo.pdf',
  ocr_status: 'completed',
  ocr_progress: 100,
  extract_status: 'completed',
  extract_progress: 100,
  error: '',
  result_version: 1,
  created_at: null,
  updated_at: null,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/integration/task/task-1']}>
      <ToastProvider>
        <Routes>
          <Route
            path="/integration/task/:taskId"
            element={<IntegrationTaskResultPage />}
          />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  )
}

describe('IntegrationTaskResultPage', () => {
  beforeEach(() => {
    mocks.status.mockResolvedValue(TASK)
    mocks.sessionToken.mockResolvedValue({
      task_id: TASK.task_id,
      token: 'share-token',
      document_id: TASK.document_id,
      kb_id: TASK.kb_id,
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        blob: async () => new Blob(['{}'], { type: 'application/json' }),
      }),
    )
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:test'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  it('对接页展示问题反馈与导出，并内嵌结构化抽取页', async () => {
    renderPage()

    expect(await screen.findByText('demo.pdf')).toBeInTheDocument()
    const detail = screen.getByTestId('extraction-detail')
    expect(detail).toHaveAttribute('data-signal', '0')

    fireEvent.click(screen.getByRole('button', { name: '问题反馈' }))
    await waitFor(() => {
      expect(screen.getByTestId('extraction-detail')).toHaveAttribute(
        'data-signal',
        '1',
      )
    })

    fireEvent.click(screen.getByRole('button', { name: '导出' }))
    expect(
      await screen.findByRole('heading', { name: '导出结果' }),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Schema JSON/ }))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/v1/share/share-token/export?format=hanson',
      )
    })
  })
})
