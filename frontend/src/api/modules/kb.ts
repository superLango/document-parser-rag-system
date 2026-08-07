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
  ServiceCheckResult,
  ServicesDiagnoseResult,
  ServiceConfigSection,
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

  // ---------- 服务配置与诊断 ----------
  listServiceConfigs(kbId: string): Promise<{
    services: ServiceConfigSection[]
    last_diagnose?: {
      checked_at: string | null
      total: number
      ok_count: number
      error_count: number
      warning_count: number
    } | null
  }> {
    return http.get(`/kbs/${kbId}/services`)
  },

  updateServiceConfig(
    kbId: string,
    serviceName: string,
    config: Record<string, unknown>,
  ): Promise<{ service: string; config: Record<string, unknown> }> {
    return http.put(`/kbs/${kbId}/services/${serviceName}`, config)
  },

  validateService(kbId: string, serviceName: string): Promise<ServiceCheckResult> {
    return http.post<ServiceCheckResult>(`/kbs/${kbId}/services/${serviceName}/validate`)
  },

  diagnoseAllServices(kbId: string): Promise<ServicesDiagnoseResult> {
    return http.post<ServicesDiagnoseResult>(`/kbs/${kbId}/diagnose`)
  },

  getServicesStatus(kbId: string): Promise<{
    checked_at: string | null
    total: number
    ok_count: number
    error_count: number
    warning_count: number
    services: ServiceCheckResult[] | Record<string, ServiceCheckResult>
    never_checked: boolean
  }> {
    return http.get(`/kbs/${kbId}/services/status`)
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

  /** 获取文档 OCR 解析文本、Popo JSON、布局数据 */
  getOcrText(
    kbId: string,
    docId: string,
  ): Promise<{
    document_id: string
    filename: string
    parsed_text: string
    layout_data: any[] | null
    popo_json: Record<string, any> | null
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
    params?: { page?: number; page_size?: number; status?: string; task_type?: string },
  ): Promise<Paginated<Task>> {
    return http.get<Paginated<Task>>(`/kbs/${kbId}/tasks`, { params })
  },

  getTask(kbId: string, taskId: string): Promise<Task> {
    return http.get<Task>(`/kbs/${kbId}/tasks/${taskId}`)
  },

  retryTask(kbId: string, taskId: string): Promise<unknown> {
    return http.post(`/kbs/${kbId}/tasks/${taskId}/retry`)
  },

  deleteTask(kbId: string, taskId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/tasks/${taskId}`)
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

  // ---------- 术语集管理（KB 内隔离） ----------
  listTermBases(kbId: string): Promise<{ items: TermBase[]; total: number }> {
    return http.get(`/kbs/${kbId}/term-bases`)
  },

  createTermBase(
    kbId: string,
    data: {
      name: string
      description?: string
      source_type?: 'manual' | 'api' | 'db'
      source_config?: Record<string, any>
      columns?: Array<Record<string, any>>
      column_aliases?: Record<string, string>
      auto_import?: boolean
      import_data?: Array<Record<string, any>>
    },
  ): Promise<TermBase & { imported?: number }> {
    return http.post(`/kbs/${kbId}/term-bases`, data)
  },

  updateTermBase(
    kbId: string,
    baseId: string,
    data: {
      name?: string
      description?: string
      source_config?: Record<string, any>
      columns?: Array<Record<string, any>>
      column_aliases?: Record<string, string>
      sync_enabled?: boolean
    },
  ): Promise<TermBase> {
    return http.put(`/kbs/${kbId}/term-bases/${baseId}`, data)
  },

  deleteTermBase(kbId: string, baseId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/term-bases/${baseId}`)
  },

  /** 测试API数据源连接（不保存） */
  testTermBaseApi(
    kbId: string,
    config: {
      url: string
      method: 'GET' | 'POST' | 'PUT' | 'DELETE'
      params?: Array<{ key: string; value: string; in_location: string; enabled: boolean }>
      headers?: Record<string, string>
      body?: string
      json_path?: string
      timeout?: number
    },
  ): Promise<{
    status_code: number
    raw_response: any
    extracted_rows: any[]
    total_rows: number
    columns: Array<{ name: string; type: string; label: string }>
  }> {
    return http.post(`/kbs/${kbId}/term-bases/test-api`, config)
  },

  /** 测试数据库连接（不保存） */
  testTermBaseDb(
    kbId: string,
    config: {
      db_type: 'mysql'
      host: string
      port?: number
      user: string
      password: string
      database: string
      charset?: string
    },
  ): Promise<{ connected: boolean; version: string; message: string }> {
    return http.post(`/kbs/${kbId}/term-bases/test-db`, config)
  },

  /** 获取数据库表列表 */
  listDbTables(
    kbId: string,
    config: {
      db_type: 'mysql'
      host: string
      port?: number
      user: string
      password: string
      database: string
      charset?: string
    },
  ): Promise<{ tables: string[] }> {
    return http.post(`/kbs/${kbId}/term-bases/db-tables`, config)
  },

  /** 预览SQL查询结果（前5条） */
  previewSql(
    kbId: string,
    config: {
      db_type: 'mysql'
      host: string
      port?: number
      user: string
      password: string
      database: string
      charset?: string
      mode: 'table' | 'sql'
      table?: string
      sql_query?: string
    },
  ): Promise<{
    rows: any[]
    columns: Array<{ name: string; type: string; label: string }>
    total_preview: number
    sql: string
  }> {
    return http.post(`/kbs/${kbId}/term-bases/preview-sql`, config)
  },

  /** 从已配置的数据源同步术语 */
  syncTermBase(
    kbId: string,
    baseId: string,
  ): Promise<{ imported: number; synced_at: string }> {
    return http.post(`/kbs/${kbId}/term-bases/${baseId}/sync`)
  },

  importTermBaseJson(kbId: string, baseId: string, file: File): Promise<{ imported: number }> {
    const formData = new FormData()
    formData.append('file', file)
    return http.post(`/kbs/${kbId}/term-bases/${baseId}/import-json`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  importTermBaseFromSource(
    kbId: string,
    baseId: string,
    data: { source_type: 'feature' | 'item' | 'method' | 'term_category'; category_filter?: string },
  ): Promise<{ imported: number }> {
    return http.post(`/kbs/${kbId}/term-bases/${baseId}/import-from-source`, data)
  },

  listTermBaseTerms(
    kbId: string,
    baseId: string,
    params?: { page?: number; page_size?: number; keyword?: string; search_field?: string },
  ): Promise<Paginated<TermBaseTerm>> {
    return http.get<Paginated<TermBaseTerm>>(`/kbs/${kbId}/term-bases/${baseId}/terms`, { params })
  },

  batchSaveTermBaseTerms(
    kbId: string,
    baseId: string,
    data: {
      items: Array<{
        id?: string
        term: string
        english_term?: string
        aliases?: string[]
        definition?: string
        category?: string
        synonyms?: string[]
      }>
      deleted_ids?: string[]
    },
  ): Promise<{ created: number; updated: number; deleted: number }> {
    return http.put(`/kbs/${kbId}/term-bases/${baseId}/terms/batch`, data)
  },

  // ---------- Schema 模板（KB 内隔离，三层结构） ----------
  listSchemaTemplates(kbId: string): Promise<Record<string, unknown>[]> {
    return http.get(`/kbs/${kbId}/schema-templates`)
  },

  createSchemaTemplate(
    kbId: string,
    data: { name: string; description?: string; is_active?: boolean },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/schema-templates`, data)
  },

  getSchemaTemplate(kbId: string, templateId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/schema-templates/${templateId}`)
  },

  updateSchemaTemplate(
    kbId: string,
    templateId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/schema-templates/${templateId}`, data)
  },

  deleteSchemaTemplate(kbId: string, templateId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/schema-templates/${templateId}`)
  },

  createSchemaCategory(
    kbId: string,
    templateId: string,
    data: {
      name: string
      description?: string
      return_type?: string
      extraction_strategy?: string
      query_mode?: string
      fixed_query?: string | null
      confidence_threshold?: number | null
      top_k?: number | null
      datasets?: Record<string, unknown>[]
      is_active?: boolean
      sort_order?: number
      name_source?: string
      name_term_base_id?: string | null
      name_term_field?: string | null
      query_sources?: Record<string, unknown>[]
    },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/schema-templates/${templateId}/categories`, data)
  },

  updateSchemaCategory(
    kbId: string,
    templateId: string,
    categoryId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/schema-templates/${templateId}/categories/${categoryId}`, data)
  },

  deleteSchemaCategory(kbId: string, templateId: string, categoryId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/schema-templates/${templateId}/categories/${categoryId}`)
  },

  createSchemaField(
    kbId: string,
    templateId: string,
    categoryId: string,
    data: {
      name: string
      type?: string
      description?: string
      example?: string | null
      required?: boolean
      sort_order?: number
    },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/schema-templates/${templateId}/categories/${categoryId}/fields`, data)
  },

  updateSchemaField(
    kbId: string,
    templateId: string,
    categoryId: string,
    fieldId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/schema-templates/${templateId}/categories/${categoryId}/fields/${fieldId}`, data)
  },

  deleteSchemaField(
    kbId: string,
    templateId: string,
    categoryId: string,
    fieldId: string,
  ): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/schema-templates/${templateId}/categories/${categoryId}/fields/${fieldId}`)
  },

  // ---------- 抽取配置中心（KB 内隔离） ----------
  getExtractionConfig(kbId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/extraction-config`)
  },

  getExtractionGlobal(kbId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/extraction-config/global`)
  },

  saveExtractionGlobal(
    kbId: string,
    data: { enabled?: boolean; content?: Record<string, unknown> },
  ): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/extraction-config/global`, data)
  },

  listExtractionPrompts(kbId: string): Promise<{ items: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/extraction-config/prompts`)
  },

  getExtractionPrompt(kbId: string, promptId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/extraction-config/prompts/${promptId}`)
  },

  createExtractionPrompt(
    kbId: string,
    data: {
      name: string
      description?: string
      scope?: string
      system_prompt?: string
      user_prompt?: string
      schema_template_id?: string | null
      category_ids?: string[]
      is_active?: boolean
    },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/extraction-config/prompts`, data)
  },

  updateExtractionPrompt(
    kbId: string,
    promptId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/extraction-config/prompts/${promptId}`, data)
  },

  saveExtractionPrompt(
    kbId: string,
    promptId: string,
    data: {
      system_prompt?: string
      user_prompt?: string
      categories?: { category_id: string; user_prompt: string }[]
      is_active?: boolean
    },
  ): Promise<Record<string, unknown>> {
    return http.put(`/kbs/${kbId}/extraction-config/prompts/${promptId}/save`, data)
  },

  deleteExtractionPrompt(kbId: string, promptId: string): Promise<unknown> {
    return http.delete(`/kbs/${kbId}/extraction-config/prompts/${promptId}`)
  },

  listExtractionRules(kbId: string): Promise<{ items: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/extraction-config/rules`)
  },

  getExtractionRuleRegistry(
    kbId: string,
  ): Promise<{ stages: Record<string, string[]>; rules: Record<string, Record<string, unknown>> }> {
    return http.get(`/kbs/${kbId}/extraction-config/rules/registry`)
  },

  saveExtractionRules(
    kbId: string,
    items: Record<string, unknown>[],
  ): Promise<{ message: string }> {
    return http.put(`/kbs/${kbId}/extraction-config/rules`, items)
  },

  getScriptIO(kbId: string): Promise<{ folders: Record<string, Record<string, unknown>> }> {
    return http.get(`/kbs/${kbId}/extraction-config/scripts/io`)
  },

  listScripts(kbId: string, folder?: string): Promise<{ items: Record<string, unknown>[] }> {
    const q = folder ? `?folder=${folder}` : ''
    return http.get(`/kbs/${kbId}/extraction-config/scripts${q}`)
  },

  createScript(kbId: string, data: Record<string, unknown>): Promise<{ id: string }> {
    return http.post(`/kbs/${kbId}/extraction-config/scripts`, data)
  },

  updateScript(kbId: string, scriptId: string, data: Record<string, unknown>): Promise<{ message: string }> {
    return http.put(`/kbs/${kbId}/extraction-config/scripts/${scriptId}`, data)
  },

  deleteScript(kbId: string, scriptId: string): Promise<{ message: string }> {
    return http.delete(`/kbs/${kbId}/extraction-config/scripts/${scriptId}`)
  },

  runScript(
    kbId: string,
    data: Record<string, unknown>,
  ): Promise<{ ok: boolean; result?: Record<string, unknown>; error?: string }> {
    return http.post(`/kbs/${kbId}/extraction-config/scripts/run`, data)
  },

  listRuleGroups(kbId: string): Promise<{ items: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/extraction-config/rule-groups`)
  },

  createRuleGroup(
    kbId: string,
    data: { name?: string; schema_template_id: string; description?: string },
  ): Promise<{ id: string }> {
    return http.post(`/kbs/${kbId}/extraction-config/rule-groups`, data)
  },

  getRuleGroup(kbId: string, groupId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/extraction-config/rule-groups/${groupId}`)
  },

  saveRuleGroupItems(
    kbId: string,
    groupId: string,
    data: {
      category_id: string
      category_name?: string
      items: Record<string, unknown>[]
    },
  ): Promise<{ message: string }> {
    return http.put(`/kbs/${kbId}/extraction-config/rule-groups/${groupId}/items`, data)
  },

  deleteRuleGroup(kbId: string, groupId: string): Promise<{ message: string }> {
    return http.delete(`/kbs/${kbId}/extraction-config/rule-groups/${groupId}`)
  },

  listExtractionValidation(kbId: string): Promise<{ items: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/extraction-config/validation`)
  },

  saveExtractionValidation(
    kbId: string,
    items: Record<string, unknown>[],
  ): Promise<{ message: string }> {
    return http.put(`/kbs/${kbId}/extraction-config/validation`, items)
  },

  listExtractionBindings(kbId: string): Promise<{ items: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/extraction-config/bindings`)
  },

  saveExtractionBindings(
    kbId: string,
    items: Record<string, unknown>[],
  ): Promise<{ message: string }> {
    return http.put(`/kbs/${kbId}/extraction-config/bindings`, items)
  },

  listExtractionVersions(kbId: string): Promise<{ items: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/extraction-config/versions`)
  },

  createExtractionVersion(
    kbId: string,
    data: { name: string; description?: string },
  ): Promise<Record<string, unknown>> {
    return http.post(`/kbs/${kbId}/extraction-config/versions`, data)
  },

  rollbackExtractionVersion(kbId: string, versionId: string): Promise<{ message: string }> {
    return http.post(`/kbs/${kbId}/extraction-config/versions/${versionId}/rollback`)
  },

  deleteExtractionVersion(kbId: string, versionId: string): Promise<{ message: string }> {
    return http.delete(`/kbs/${kbId}/extraction-config/versions/${versionId}`)
  },

  getExtractionVersionDetail(kbId: string, versionId: string): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/extraction-config/versions/${versionId}`)
  },

  diffExtractionVersion(
    kbId: string,
    versionId: string,
  ): Promise<{ version: number; name: string; diff: Record<string, unknown> }> {
    return http.get(`/kbs/${kbId}/extraction-config/versions/${versionId}/diff`)
  },

  // ---------- 知识图谱（KB 内隔离） ----------
  getGraph(kbId: string, limit = 50, config?: any): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/graph`, { params: { limit }, ...config })
  },

  searchGraphNodes(
    kbId: string,
    params: { label?: string; name?: string; limit?: number },
    config?: any,
  ): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[]; total: number }> {
    return http.get(`/kbs/${kbId}/graph/search`, { params, ...config })
  },

  getSubgraph(kbId: string, entity: string, maxHops = 2, config?: any): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] }> {
    return http.get(`/kbs/${kbId}/graph/subgraph`, { params: { entity, max_hops: maxHops }, ...config })
  },

  graphStats(kbId: string, config?: any): Promise<Record<string, unknown>> {
    return http.get(`/kbs/${kbId}/graph/stats`, config)
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
            if (evt.done) callbacks.onDone?.(evt.session_id, evt.citations)
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
    latest_schema_id: string | null
    latest_schema_name: string | null
    latest_result: Record<string, unknown> | null
    latest_extracted_at: string | null
    history: Array<Record<string, unknown>>
  }> {
    return http.get(`/kbs/${kbId}/extraction/results/${documentId}`)
  },

  getExtractionHistory(
    kbId: string,
    documentId: string,
  ): Promise<{ items: KbExtractionHistoryItem[]; total: number }> {
    return http.get(`/kbs/${kbId}/extraction/history/${documentId}`)
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
  onDone?: (sessionId?: string, citations?: KbQaCitation[]) => void
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
  latest_schema_name?: string | null
  latest_extracted_at?: string | null
  history_count?: number
  created_at: string
  updated_at: string | null
}

/** 可用于抽取的父分类 Schema */
export interface KbExtractionSchema {
  id: string
  name: string
  description: string
  children_count: number
  field_count: number
}

/** 抽取历史记录项 */
export interface KbExtractionHistoryItem {
  schema_id: string | null
  schema_name: string | null
  result: Record<string, unknown>
  extracted_at: string | null
  archived_at?: string | null
  is_latest: boolean
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

/** 术语集（统一术语集，支持 manual/api/db 三种数据源） */
export interface TermBase {
  id: string
  kb_id: string
  name: string
  description: string
  source_type: 'manual' | 'api' | 'db'
  source_config: Record<string, any>
  columns: Array<{ name: string; type: string; label: string }>
  column_aliases: Record<string, string>
  sync_enabled: boolean
  last_synced_at: string | null
  term_count: number
  created_at: string
  updated_at: string | null
}

/** 术语集中的术语项 */
export interface TermBaseTerm {
  id: string
  term_base_id: string | null
  term: string
  english_term: string
  aliases: string[]
  definition: string
  category: string
  synonyms: string[]
  extras: Record<string, any>
  standard_number?: string
  status: string
  created_at: string
  updated_at: string | null
}
