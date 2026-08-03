import { http } from '@/api'
import type { Paginated, Document, Task } from '@/api/types'
import type {
  KnowledgeBase,
  KbCreateRequest,
  KbCreateResponse,
  KbUpdateRequest,
  KbStats,
  KbMember,
  KbRole,
  DomainTemplateSummary,
  DomainTemplateDetail,
  ApplyTemplateResult,
  KbConfig,
  KbHookInfo,
  KbHookContent,
  KbConfigValidation,
  KbResourceVerify,
  KbBackup,
  KbBackupRestoreStats,
} from '@/api/types'

/**
 * 新架构知识库 API（HansonDOC RAG）
 *
 * 对应后端 app.api.v1.endpoints.kbs / kb_config
 * 所有 KB 内操作通过 /kbs/{kb_id}/... 路径，后端 get_kb_context 守卫隔离与权限
 */
export const kbApi = {
  // ---------- 知识库 CRUD ----------
  list(params?: { page?: number; page_size?: number }): Promise<Paginated<KnowledgeBase>> {
    return http.get<Paginated<KnowledgeBase>>('/kbs', { params })
  },

  create(data: KbCreateRequest): Promise<KbCreateResponse> {
    return http.post<KbCreateResponse>('/kbs', data)
  },

  get(kbId: string): Promise<KnowledgeBase> {
    return http.get<KnowledgeBase>(`/kbs/${kbId}`)
  },

  update(kbId: string, data: KbUpdateRequest): Promise<KnowledgeBase> {
    return http.put<KnowledgeBase>(`/kbs/${kbId}`, data)
  },

  delete(kbId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}`)
  },

  setActive(kbId: string, isActive: boolean): Promise<KnowledgeBase> {
    return http.patch<KnowledgeBase>(`/kbs/${kbId}/active`, { is_active: isActive })
  },

  stats(kbId: string): Promise<KbStats> {
    return http.get<KbStats>(`/kbs/${kbId}/stats`)
  },

  // ---------- 成员管理 ----------
  listMembers(kbId: string): Promise<{ items: KbMember[]; total: number }> {
    return http.get(`/kbs/${kbId}/members`)
  },

  addMember(kbId: string, userId: string, role: KbRole): Promise<KbMember> {
    return http.post<KbMember>(`/kbs/${kbId}/members`, { user_id: userId, role })
  },

  updateMemberRole(kbId: string, userId: string, role: KbRole): Promise<{ role: string }> {
    return http.put(`/kbs/${kbId}/members/${userId}`, { role })
  },

  removeMember(kbId: string, userId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/members/${userId}`)
  },

  // ---------- 领域模板 ----------
  listTemplates(): Promise<{ items: DomainTemplateSummary[]; total: number }> {
    return http.get('/kbs/templates')
  },

  getTemplate(code: string): Promise<DomainTemplateDetail> {
    return http.get<DomainTemplateDetail>(`/kbs/templates/${code}`)
  },

  applyTemplate(kbId: string, templateCode: string): Promise<ApplyTemplateResult> {
    return http.post<ApplyTemplateResult>(`/kbs/${kbId}/apply-template`, {
      template_code: templateCode,
    })
  },

  // ---------- 配置中心 ----------
  getConfig(kbId: string): Promise<KbConfig> {
    return http.get<KbConfig>(`/kbs/${kbId}/config`)
  },

  getConfigSection(kbId: string, section: string): Promise<{ section: string; config: Record<string, unknown> }> {
    return http.get(`/kbs/${kbId}/config/${section}`)
  },

  updateConfig(kbId: string, config: Record<string, unknown>): Promise<{ config: Record<string, unknown> }> {
    return http.put(`/kbs/${kbId}/config`, { config })
  },

  updateConfigSection(
    kbId: string,
    section: string,
    sectionData: Record<string, unknown>,
  ): Promise<{ section: string; config: Record<string, unknown> }> {
    return http.put(`/kbs/${kbId}/config/${section}`, { section: sectionData })
  },

  validateConfig(kbId: string): Promise<KbConfigValidation> {
    return http.post<KbConfigValidation>(`/kbs/${kbId}/config/validate`)
  },

  verifyResources(kbId: string): Promise<KbResourceVerify> {
    return http.get<KbResourceVerify>(`/kbs/${kbId}/resources/verify`)
  },

  // ---------- 领域配置表 ----------
  listCategories(kbId: string): Promise<{ items: Record<string, unknown>[]; total: number }> {
    return http.get(`/kbs/${kbId}/domain/categories`)
  },

  createCategory(
    kbId: string,
    data: { name: string; extraction_class: string; description?: string; is_active?: boolean; sort_order?: number; enums?: Record<string, string[]> },
  ): Promise<{ id: string; name: string }> {
    return http.post(`/kbs/${kbId}/domain/categories`, data)
  },

  updateCategory(
    kbId: string,
    catId: string,
    data: Partial<{ name: string; extraction_class: string; description: string; is_active: boolean; sort_order: number; recall_filter_threshold: number; enums: Record<string, string[]> }>,
  ): Promise<{ id: string }> {
    return http.put(`/kbs/${kbId}/domain/categories/${catId}`, data)
  },

  deleteCategory(kbId: string, catId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/domain/categories/${catId}`)
  },

  listRegexRules(kbId: string): Promise<{ items: Record<string, unknown>[]; total: number }> {
    return http.get(`/kbs/${kbId}/domain/regex-rules`)
  },

  listFieldTemplates(kbId: string): Promise<{ items: Record<string, unknown>[]; total: number }> {
    return http.get(`/kbs/${kbId}/domain/field-templates`)
  },

  getDictConfig(kbId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/domain/dict-config`)
  },

  // ---------- Hook 管理 ----------
  getHookInfo(kbId: string): Promise<KbHookInfo> {
    return http.get<KbHookInfo>(`/kbs/${kbId}/hook`)
  },

  getHookContent(kbId: string): Promise<KbHookContent> {
    return http.get<KbHookContent>(`/kbs/${kbId}/hook/content`)
  },

  updateHookContent(kbId: string, content: string): Promise<unknown> {
    return http.put(`/kbs/${kbId}/hook/content`, { content })
  },

  reloadHook(kbId: string): Promise<{ kb_id: string; reloaded: boolean; has_script: boolean }> {
    return http.post(`/kbs/${kbId}/hook/reload`)
  },

  deleteHook(kbId: string): Promise<{ deleted: boolean }> {
    return http.delete(`/kbs/${kbId}/hook`)
  },

  // ---------- 文档管理（KB 内隔离） ----------
  listDocuments(
    kbId: string,
    params?: { page?: number; page_size?: number; status?: string },
  ): Promise<Paginated<Document>> {
    return http.get<Paginated<Document>>(`/kbs/${kbId}/documents`, { params })
  },

  uploadDocument(kbId: string, file: File): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    return http.post<Document>(`/kbs/${kbId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  /** 批量上传文档 */
  batchUploadDocuments(
    kbId: string,
    files: File[],
  ): Promise<{
    results: Array<{ filename: string; ok: boolean; error: string | null }>
    total: number
    success: number
    failed: number
  }> {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    return http.post(`/kbs/${kbId}/documents/batch-upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  getDocument(kbId: string, docId: string): Promise<Document> {
    return http.get<Document>(`/kbs/${kbId}/documents/${docId}`)
  },

  downloadDocument(kbId: string, docId: string): Promise<Blob> {
    return http.get<Blob>(`/kbs/${kbId}/documents/${docId}/download`, {
      responseType: 'blob',
    })
  },

  deleteDocument(kbId: string, docId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/documents/${docId}`)
  },

  /** 预览文档原始文件（inline，返回 Blob 供前端 URL.createObjectURL） */
  previewDocument(kbId: string, docId: string): Promise<Blob> {
    return http.get<Blob>(`/kbs/${kbId}/documents/${docId}/preview`, {
      responseType: 'blob',
    })
  },

  /** 获取文档 OCR 解析文本、布局数据与结构化数据 */
  getOcrText(
    kbId: string,
    docId: string,
  ): Promise<{
    document_id: string
    filename: string
    parsed_text: string
    layout_data: any[] | null
    structured_data: Record<string, any> | null
    status: string
    file_type: string
  }> {
    return http.get(`/kbs/${kbId}/documents/${docId}/ocr-text`)
  },

  /** 导出文档列表（Excel/CSV/JSON），返回 Blob */
  exportDocuments(
    kbId: string,
    params?: { format?: 'excel' | 'csv' | 'json'; status?: string },
  ): Promise<Blob> {
    return http.get<Blob>(`/kbs/${kbId}/documents/export`, {
      params,
      responseType: 'blob',
    })
  },

  /** 批量删除文档 */
  batchDeleteDocuments(
    kbId: string,
    documentIds: string[],
  ): Promise<{
    results: Array<{ id: string; ok: boolean; error: string | null }>
    total: number
    success: number
    failed: number
  }> {
    return http.post(`/kbs/${kbId}/documents/batch-delete`, {
      document_ids: documentIds,
    })
  },

  /** 批量解析文档 */
  batchParseDocuments(
    kbId: string,
    documentIds: string[],
    schemaId?: string,
  ): Promise<{
    results: Array<{ document_id: string; ok: boolean; error: string | null; task_id: string | null }>
    total: number
    success: number
    failed: number
  }> {
    return http.post(`/kbs/${kbId}/tasks/batch-parse`, {
      document_ids: documentIds,
      schema_id: schemaId,
    })
  },

  // ---------- 任务管理（KB 内隔离） ----------
  submitParseTask(
    kbId: string,
    docId: string,
    data: { schema_id?: string; term_base_id?: string },
  ): Promise<{ task_id: string; status: string }> {
    return http.post(`/kbs/${kbId}/documents/${docId}/parse`, data)
  },

  listTasks(
    kbId: string,
    params?: { page?: number; page_size?: number; status?: string },
  ): Promise<Paginated<Task>> {
    return http.get<Paginated<Task>>(`/kbs/${kbId}/tasks`, { params })
  },

  getTask(kbId: string, taskId: string): Promise<Task> {
    return http.get<Task>(`/kbs/${kbId}/tasks/${taskId}`)
  },

  retryTask(kbId: string, taskId: string): Promise<unknown> {
    return http.post(`/kbs/${kbId}/tasks/${taskId}/retry`)
  },

  /** 批量重试失败任务 */
  batchRetryTasks(
    kbId: string,
    taskIds: string[],
  ): Promise<{
    results: Array<{ task_id: string; ok: boolean; error: string | null; new_task_id?: string }>
    total: number
    success: number
    failed: number
  }> {
    return http.post(`/kbs/${kbId}/tasks/batch-retry`, { task_ids: taskIds })
  },

  cancelTask(kbId: string, taskId: string): Promise<unknown> {
    return http.post(`/kbs/${kbId}/tasks/${taskId}/cancel`)
  },

  taskStats(kbId: string): Promise<{
    total: number
    by_status: Record<string, number>
    by_type: Record<string, number>
    success_count: number
    failed_count: number
    success_rate: number
  }> {
    return http.get(`/kbs/${kbId}/tasks/stats`)
  },

  // ---------- Schema 管理（KB 内隔离） ----------
  listSchemas(
    kbId: string,
    params?: { page?: number; page_size?: number; parent_id?: string; only_parent?: boolean },
  ): Promise<Paginated<Record<string, unknown>>> {
    return http.get<Paginated<Record<string, unknown>>>(`/kbs/${kbId}/schemas`, { params })
  },

  listSchemaCategories(kbId: string): Promise<Record<string, unknown>[]> {
    return http.get(`/kbs/${kbId}/schemas/categories`)
  },

  listSchemaChildren(kbId: string, parentId: string, onlyActive = false): Promise<Record<string, unknown>[]> {
    return http.get(`/kbs/${kbId}/schemas/${parentId}/children`, {
      params: { only_active: onlyActive },
    })
  },

  getMergedSchema(kbId: string, parentId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/schemas/${parentId}/merged`)
  },

  createSchema(
    kbId: string,
    data: {
      name: string
      description?: string
      doc_type?: string
      fields?: Record<string, unknown>[]
      sample_fields?: Record<string, unknown>
      parent_id?: string
      is_active?: boolean
      sort_order?: number
    },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/schemas`, data)
  },

  updateSchema(kbId: string, schemaId: string, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/schemas/${schemaId}`, data)
  },

  deleteSchema(kbId: string, schemaId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/schemas/${schemaId}`)
  },

  toggleSchemaActive(kbId: string, schemaId: string, isActive: boolean): Promise<unknown> {
    return http.patch(`/kbs/${kbId}/schemas/${schemaId}/active`, { is_active: isActive })
  },

  copySchema(kbId: string, schemaId: string, newName: string, newParentId?: string): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/schemas/${schemaId}/copy`, {
      new_name: newName,
      new_parent_id: newParentId,
    })
  },

  // ---------- 术语库管理（KB 内隔离） ----------
  listTerms(
    kbId: string,
    params?: { page?: number; page_size?: number; status?: string; category?: string; keyword?: string },
  ): Promise<Paginated<Record<string, unknown>>> {
    return http.get<Paginated<Record<string, unknown>>>(`/kbs/${kbId}/terms`, { params })
  },

  listTermCategories(kbId: string): Promise<string[]> {
    return http.get(`/kbs/${kbId}/terms/categories`)
  },

  exportTerms(kbId: string): Promise<{ items: Record<string, unknown>[]; total: number }> {
    return http.get(`/kbs/${kbId}/terms/export`)
  },

  createTerm(
    kbId: string,
    data: {
      term: string
      english_term?: string
      definition?: string
      category?: string
      standard_number?: string
      synonyms?: string[]
    },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/terms`, data)
  },

  batchImportTerms(
    kbId: string,
    data: Array<{
      term: string
      english_term?: string
      definition?: string
      category?: string
      standard_number?: string
      synonyms?: string[]
    }>,
  ): Promise<{ imported: number }> {
    return http.post(`/kbs/${kbId}/terms/batch`, data)
  },

  updateTerm(kbId: string, termId: string, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/terms/${termId}`, data)
  },

  reviewTerm(kbId: string, termId: string, action: 'approve' | 'reject'): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/terms/${termId}/review`, { action })
  },

  deleteTerm(kbId: string, termId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/terms/${termId}`)
  },

  // ---------- 知识图谱（KB 内隔离） ----------
  getGraph(kbId: string, limit = 50): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/graph`, { params: { limit } })
  },

  searchGraphNodes(
    kbId: string,
    params: { label?: string; name?: string; limit?: number },
  ): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[]; total: number }> {
    return http.get(`/kbs/${kbId}/graph/search`, { params })
  },

  getSubgraph(kbId: string, entity: string, maxHops = 2): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/graph/subgraph`, { params: { entity, max_hops: maxHops } })
  },

  graphStats(kbId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/graph/stats`)
  },

  buildGraph(kbId: string, documentId: string): Promise<{ task_id: string; status: string }> {
    return http.post(`/kbs/${kbId}/graph/documents/${documentId}`)
  },

  rebuildGraph(kbId: string): Promise<{ task_id: string; status: string }> {
    return http.post(`/kbs/${kbId}/graph/rebuild`)
  },

  removeGraph(kbId: string, documentId: string): Promise<{ task_id: string; status: string }> {
    return http.delete(`/kbs/${kbId}/graph/documents/${documentId}`)
  },

  // ---------- 智能问答（KB 内隔离） ----------
  /** 问答引用来源（对应后端 CitationModel） */
  ask(
    kbId: string,
    data: {
      question: string
      top_k?: number
      doc_ids?: string[]
      use_graph?: boolean
      use_reranker?: boolean
    },
  ): Promise<{
    answer: string
    intent: string
    entities: Record<string, unknown>[]
    citations: KbQaCitation[]
    retrieval_count: number
    rerank_count: number
    query: string
  }> {
    return http.post(`/kbs/${kbId}/qa/query`, {
      question: data.question,
      top_k: data.top_k ?? 5,
      doc_ids: data.doc_ids,
      use_graph: data.use_graph ?? true,
      use_reranker: data.use_reranker ?? true,
    })
  },

  qaHealth(kbId: string): Promise<{ status: string; service: string; kb_id: string }> {
    return http.get(`/kbs/${kbId}/qa/health`)
  },

  // ---------- 问答会话历史 ----------
  listQaSessions(
    kbId: string,
    params?: { page?: number; page_size?: number },
  ): Promise<Paginated<KbQaSession>> {
    return http.get<Paginated<KbQaSession>>(`/kbs/${kbId}/qa/sessions`, { params })
  },

  createQaSession(
    kbId: string,
    data?: { title?: string; doc_ids?: string[] },
  ): Promise<KbQaSession> {
    return http.post<KbQaSession>(`/kbs/${kbId}/qa/sessions`, data ?? {})
  },

  getQaSession(kbId: string, sessionId: string): Promise<KbQaSession> {
    return http.get<KbQaSession>(`/kbs/${kbId}/qa/sessions/${sessionId}`)
  },

  renameQaSession(kbId: string, sessionId: string, title: string): Promise<KbQaSession> {
    return http.patch<KbQaSession>(`/kbs/${kbId}/qa/sessions/${sessionId}`, { title })
  },

  deleteQaSession(kbId: string, sessionId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/qa/sessions/${sessionId}`)
  },

  listQaMessages(
    kbId: string,
    sessionId: string,
  ): Promise<{ items: KbQaMessage[]; total: number }> {
    return http.get(`/kbs/${kbId}/qa/sessions/${sessionId}/messages`)
  },

  exportQaSession(
    kbId: string,
    sessionId: string,
    format: 'json' | 'markdown' = 'markdown',
  ): Promise<Blob> {
    return http.get<Blob>(`/kbs/${kbId}/qa/sessions/${sessionId}/export`, {
      params: { format },
      responseType: 'blob',
    })
  },

  // ---------- 全文搜索 ----------
  searchDocuments(
    kbId: string,
    query: string,
    limit?: number,
  ): Promise<{
    items: KbSearchResult[]
    total: number
    query: string
  }> {
    return http.get(`/kbs/${kbId}/search`, {
      params: { q: query, limit },
    })
  },

  /**
   * KB 内 SSE 流式问答
   * 通过 fetch + ReadableStream 消费 /kbs/{kb_id}/qa/stream 事件流
   *
   * 历史持久化：后端在流式完成后自动持久化 user + assistant 消息到会话历史，
   * 并通过 done 事件回传 session_id。前端可在 onDone 中保存该 session_id，
   * 后续调用传入同一 session_id 以保持多轮对话上下文连贯。
   */
  async askStream(
    kbId: string,
    query: string,
    callbacks: KbQaStreamCallbacks,
    options?: {
      top_k?: number
      doc_ids?: string[]
      use_graph?: boolean
      use_reranker?: boolean
      session_id?: string
    },
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/kbs/${kbId}/qa/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        question: query,
        top_k: options?.top_k,
        doc_ids: options?.doc_ids,
        use_graph: options?.use_graph ?? true,
        use_reranker: options?.use_reranker ?? true,
        session_id: options?.session_id,
      }),
    })

    if (!response.ok) {
      callbacks.onError?.(`HTTP ${response.status}`)
      return
    }

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
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let sep: number
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const block = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          const payload = block
            .split('\n')
            .filter((l) => l.startsWith('data:'))
            .map((l) => l.slice(5).trim())
            .join('')
          if (!payload) continue
          try {
            const evt = JSON.parse(payload)
            if (evt.chunk) callbacks.onChunk?.(evt.chunk)
            if (evt.done) callbacks.onDone?.(evt.session_id)
            if (evt.error) callbacks.onError?.(evt.error)
          } catch {
            // 忽略非 JSON 事件块
          }
        }
      }
    } catch (err) {
      callbacks.onError?.(err instanceof Error ? err.message : '流读取异常')
    }
  },

  // ---------- 结构化抽取（KB 内隔离，RLS 强制） ----------
  listExtractableDocuments(
    kbId: string,
  ): Promise<{ items: KbExtractableDocument[]; total: number }> {
    return http.get(`/kbs/${kbId}/extraction/documents`)
  },

  listExtractionSchemas(kbId: string): Promise<KbExtractionSchema[]> {
    return http.get(`/kbs/${kbId}/extraction/schemas`)
  },

  getExtractionResults(
    kbId: string,
    documentId: string,
  ): Promise<{
    document_id: string
    filename: string
    extractions: Record<string, { result: Record<string, unknown> }>
    latest_schema_id: string | null
    latest_result: Record<string, unknown> | null
  }> {
    return http.get(`/kbs/${kbId}/extraction/results/${documentId}`)
  },

  /** 导出抽取结果（Excel/CSV/JSON），返回 Blob */
  exportExtractionResults(
    kbId: string,
    format: 'excel' | 'csv' | 'json' = 'excel',
  ): Promise<Blob> {
    return http.get<Blob>(`/kbs/${kbId}/extraction/export`, {
      params: { format },
      responseType: 'blob',
    })
  },

  extract(
    kbId: string,
    data: { document_id: string; schema_id: string; save_result?: boolean },
  ): Promise<{
    document_id: string
    schema_id: string
    schema_name: string
    result: Record<string, unknown>
    missing: string[]
  }> {
    return http.post(`/kbs/${kbId}/extraction/`, {
      document_id: data.document_id,
      schema_id: data.schema_id,
      save_result: data.save_result ?? true,
    })
  },

  /**
   * KB 内 SSE 流式抽取
   * 通过 fetch + ReadableStream 消费 /kbs/{kb_id}/extraction/stream 事件流
   */
  async extractStream(
    kbId: string,
    payload: {
      document_id: string
      schema_id: string
      chunk_size?: number
      overlap?: number
      save_result?: boolean
    },
    callbacks: KbExtractionStreamCallbacks,
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/kbs/${kbId}/extraction/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        document_id: payload.document_id,
        schema_id: payload.schema_id,
        chunk_size: payload.chunk_size ?? 4000,
        overlap: payload.overlap ?? 200,
        save_result: payload.save_result ?? true,
      }),
    })

    if (!response.ok) {
      callbacks.onError?.(`HTTP ${response.status}`)
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      callbacks.onError?.('无法读取响应流')
      return
    }
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    const dispatch = (evt: Record<string, unknown>) => {
      const t = evt.type as string
      if (t === 'schema_info') callbacks.onSchemaInfo?.(evt as never)
      else if (t === 'progress') callbacks.onProgress?.(evt as never)
      else if (t === 'chunk_result') callbacks.onChunkResult?.(evt as never)
      else if (t === 'chunk_error') callbacks.onChunkError?.(evt as never)
      else if (t === 'done') callbacks.onDone?.(evt as never)
      else if (t === 'warning') callbacks.onWarning?.(evt as never)
      else if (t === 'error') callbacks.onError?.(String(evt.message ?? ''))
    }
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let sep: number
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const block = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          const payload = block
            .split('\n')
            .filter((l) => l.startsWith('data:'))
            .map((l) => l.slice(5).trim())
            .join('')
          if (!payload) continue
          try {
            dispatch(JSON.parse(payload))
          } catch {
            // 忽略非 JSON 事件块
          }
        }
      }
    } catch (err) {
      callbacks.onError?.(err instanceof Error ? err.message : '流读取异常')
    }
  },

  // ---------- 备份恢复 ----------
  listBackups(kbId: string, params?: { page?: number; page_size?: number }): Promise<Paginated<KbBackup>> {
    return http.get<Paginated<KbBackup>>(`/kbs/${kbId}/backups`, { params })
  },

  createBackup(kbId: string): Promise<KbBackup> {
    return http.post<KbBackup>(`/kbs/${kbId}/backups`)
  },

  getBackup(kbId: string, backupId: string): Promise<KbBackup> {
    return http.get<KbBackup>(`/kbs/${kbId}/backups/${backupId}`)
  },

  deleteBackup(kbId: string, backupId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/backups/${backupId}`)
  },

  downloadBackupUrl(kbId: string, backupId: string): string {
    return `/api/v1/kbs/${kbId}/backups/${backupId}/download`
  },

  async restoreBackup(kbId: string, file: File): Promise<KbBackupRestoreStats> {
    const formData = new FormData()
    formData.append('file', file)
    const res = await http.post<KbBackupRestoreStats>(`/kbs/${kbId}/backups/restore`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res
  },
}

// ============================================================
// 类型定义：KB 内 QA 与抽取
// ============================================================

/** 问答引用来源（对应后端 CitationModel） */
export interface KbQaCitation {
  document_id: string
  chunk_id: string
  content: string
  score: number
  source: string
}

/** KB 流式问答回调 */
export interface KbQaStreamCallbacks {
  onChunk?: (content: string) => void
  /** 流式完成，sessionId 为后端回传的会话 ID（用于多轮对话关联） */
  onDone?: (sessionId?: string) => void
  onError?: (message: string) => void
}

/** 问答会话 */
export interface KbQaSession {
  id: string
  kb_id: string
  user_id: string
  title: string
  doc_ids: string[]
  message_count: number
  last_message_at: string | null
  created_at: string
  updated_at: string | null
}

/** 问答消息 */
export interface KbQaMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  citations: KbQaCitation[] | null
  tokens: number | null
  created_at: string
}

/** 全文搜索结果 */
export interface KbSearchResult {
  id: string
  filename: string
  filename_highlight: string
  file_type: string | null
  status: string
  snippet: string
  rank: number
  created_at: string
}

/** 可抽取文档（已完成 OCR 解析） */
export interface KbExtractableDocument {
  id: string
  filename: string
  file_size: number
  file_type: string | null
  status: string
  text_length: number
  has_extraction: boolean
  latest_schema_id?: string | null
  created_at: string
  updated_at: string | null
}

/** 可用于抽取的父分类 Schema */
export interface KbExtractionSchema {
  id: string
  name: string
  description: string
  children_count: number
}

/** KB 流式抽取事件回调 */
export interface KbExtractionStreamCallbacks {
  onSchemaInfo?: (data: {
    schema_name: string
    schema_description: string
    field_count: number
    has_samples: boolean
  }) => void
  onProgress?: (data: {
    progress: number
    message: string
    chunk_index: number
    total_chunks: number
  }) => void
  onChunkResult?: (data: {
    data: Record<string, unknown>
    chunk_index: number
    progress: number
    message: string
  }) => void
  onChunkError?: (data: { chunk_index: number; error: string; message: string }) => void
  onDone?: (data: {
    data: Record<string, unknown>
    missing: string[]
    progress: number
    message: string
  }) => void
  onWarning?: (data: { message: string }) => void
  onError?: (message: string) => void
}
