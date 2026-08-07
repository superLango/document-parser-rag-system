// ============================================================
// 后端数据模型类型定义
// 与 FastAPI 后端模型对应
// ============================================================

// ---------- 通用响应 ----------
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---------- 认证 ----------
export interface LoginRequest {
  username: string
  password: string
}

export interface Token {
  access_token: string
  token_type: string
  expires_in: number
}

export interface User {
  id: string
  username: string
  email: string
  is_active: boolean
  is_superuser?: boolean
  full_name?: string | null
  phone?: string | null
  department?: string | null
  avatar?: string | null
  last_login_at?: string | null
  created_at: string
}

// ---------- 文档 ----------
export type DocumentStatus = 'pending' | 'processing' | 'completed' | 'failed'

/**
 * 版面分析区域（BoundingBox）
 * bbox 坐标 [x1, y1, x2, y2] 基于原始 PDF 页面尺寸
 */
export interface LayoutRegion {
  type: string // text/table/figure/title/header/footer
  bbox: [number, number, number, number] // [x1, y1, x2, y2]
  text?: string
  confidence?: number | null
  page?: number // 可选页码（1-based）
}

/**
 * 版面分析结果
 * merged 为合并后的区域列表，用于 BoundingBox 叠加
 */
export interface LayoutData {
  merged?: LayoutRegion[]
  ocr_layout?: unknown
  text_blocks?: unknown
  term_replacements?: unknown
  [key: string]: unknown
}

/**
 * 文档模型
 * 字段与后端 DocumentResponse（backend/app/schemas/document.py）严格对齐
 * - id: UUID 字符串
 * - filename: 原始文件名
 * - file_size: 文件字节数
 * - file_type: 扩展名（不含点），如 'pdf'
 * - status: pending / processing / completed / failed
 * - parsed_text: OCR 解析后的纯文本，未解析时为 null
 * - structured_data: 结构化抽取结果，未抽取时为 null
 * - layout_data: 版面分析结果（含 merged 区域列表），未解析时为 null
 * - created_at: 创建时间 ISO 字符串
 * - updated_at: 更新时间，可为 null
 */
export interface Document {
  id: string
  filename: string
  file_size: number
  file_type: string | null
  status: DocumentStatus
  parsed_text?: string | null
  structured_data?: Record<string, unknown> | null
  layout_data?: LayoutData | null
  created_at: string
  updated_at: string | null
}

export interface DocumentCreate {
  filename: string
  file_size: number
  file_type?: string | null
}

// ---------- 解析任务 ----------
export type TaskStatus = 'pending' | 'queued' | 'running' | 'started' | 'progress' | 'success' | 'completed' | 'failed'

export interface Task {
  id: string
  document_id: string | null
  task_type: string
  status: TaskStatus
  progress: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  error_message: string | null
  result: Record<string, unknown> | null
  retry_count?: number
  parent_task_id?: string | null
}

// ---------- 任务提交 ----------
export interface TaskCreateRequest {
  document_id: string
  schema_id?: string
  term_base_id?: string
  /** OCR 引擎覆盖：paddleocr / mineru / glmocr / auto，留空走全局配置 */
  engine?: 'paddleocr' | 'mineru' | 'glmocr' | 'auto'
}

export interface TaskSubmitResponse {
  task_id: string
  status: string
}

// ---------- 抽取 Schema ----------
export interface SchemaField {
  name: string
  description: string
  field_type: 'string' | 'number' | 'boolean' | 'date' | 'enum' | 'array'
  required: boolean
  enum_values?: string[]
}

/**
 * Schema 配置，支持父子层级结构
 * - parent_id 为 null 时表示父分类
 * - parent_id 不为空时表示该分类下的子 Schema
 * - sample_fields 为字段抽取示例，作为 LangExtract 抽取依据
 */
export interface Schema {
  id: string
  parent_id: string | null
  name: string
  description: string
  doc_type: string
  fields: SchemaField[]
  sample_fields: Record<string, string | string[]>
  is_active: boolean
  sort_order: number
  is_parent: boolean
  children_count?: number
  created_at: string
  updated_at: string
}

export interface SchemaCreate {
  name: string
  description: string
  doc_type?: string
  fields: SchemaField[]
  sample_fields?: Record<string, string | string[]>
  parent_id?: string | null
  is_active?: boolean
  sort_order?: number
}

/**
 * 合并后的整体 Schema（由 /schemas/{parent_id}/merged 返回）
 * 用于 LangExtract 抽取时获取完整字段定义
 */
export interface MergedSchema {
  id: string
  name: string
  description: string
  fields: SchemaField[]
  sample_fields: Record<string, string | string[]>
  children_count: number
  children_ids: string[]
}

// ---------- 术语 ----------
export interface Term {
  id: number
  term: string
  english_term: string
  definition: string
  category: string
  standard_number: string
  synonyms: string[]
  created_at: string
}

export interface TermCreate {
  term: string
  english_term?: string
  definition: string
  category: string
  standard_number?: string
  synonyms?: string[]
}

// ---------- 知识图谱 ----------
export interface GraphNode {
  id: number | string
  name: string
  labels: string[]
  type?: string
  label?: string
  properties?: Record<string, unknown>
}

export interface GraphEdge {
  source: string
  target: string
  type: string
  label?: string
  id?: string
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ---------- 智能问答 ----------
export interface QAMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: QAReference[]
  created_at: string
}

export interface QAReference {
  document_id: string
  chunk_id?: string
  content?: string
  score: number
  source?: string // vector/graph
}

export interface QARequest {
  question: string
  conversation_id?: string
  top_k?: number
}

export interface QAResponse {
  answer: string
  sources: QAReference[]
  conversation_id: string
}

// ---------- 知识库 ----------
export interface KBStats {
  total_chunks: number
  total_docs: number
  indexed_docs: number
  completed_docs: number
}

export interface KBSearchResult {
  id: string
  chunk_id: string
  text: string
  doc_id: string
  title_chain: string
  metadata: Record<string, unknown>
  score: number
  rank: number
}

export interface KBSearchResponse {
  query: string
  results: KBSearchResult[]
  total: number
}

// ---------- 仪表盘统计 ----------
export interface DashboardStats {
  documents_count: number
  tasks_count: number
  schemas_count: number
  terms_count: number
  success_rate: number
  recent_documents: Document[]
  recent_tasks: Task[]
}

// ============================================================
// 新架构：知识库（HansonDOC RAG）—— 以知识库为隔离边界
// 对应后端 app.api.v1.endpoints.kbs / kb_config
// ============================================================

/** 知识库角色 */
export type KbRole = 'owner' | 'admin' | 'editor' | 'viewer'

/** 知识库基础信息 */
export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  domain_code: string
  template_code: string | null
  owner_id: string
  config: Record<string, unknown>
  is_active: boolean
  sort_order: number
  created_at: string
  updated_at: string | null
  my_role?: KbRole | null
  member_count?: number
}

/** 新建知识库请求 */
export interface KbCreateRequest {
  name: string
  description?: string
  domain_code: string
  template_code?: string
  config?: Record<string, unknown>
}

/** 更新知识库请求 */
export interface KbUpdateRequest {
  name?: string
  description?: string
  sort_order?: number
}

/** 知识库统计 */
export interface KbStats {
  kb_id: string
  kb_name: string
  total_documents: number
  total_chunks: number
  total_tasks: number
  total_members: number
}

/** 知识库成员 */
export interface KbMember {
  id: string
  kb_id: string
  user_id: string
  username?: string
  email?: string
  avatar?: string
  role: KbRole
  created_at: string
}

/** 领域模板摘要 */
export interface DomainTemplateSummary {
  code: string
  name: string
  description: string
  domain_code: string
  category_count: number
  regex_rule_count: number
  has_hook: boolean
}

/** 领域模板详情 */
export interface DomainTemplateDetail extends DomainTemplateSummary {
  categories: Record<string, unknown>[]
  field_templates: Record<string, unknown>[]
  regex_rules: Record<string, unknown>[]
  dict_config: Record<string, unknown>
  config_override: Record<string, unknown>
}

/** 应用模板结果 */
export interface ApplyTemplateResult {
  template_code: string
  template_name: string
  categories_written: number
  field_templates_written: number
  regex_rules_written: number
  dict_config_written: boolean
  config_override_merged: boolean
  hook_script_written: boolean
}

/** KB 完整配置（合并后） */
export interface KbConfig {
  kb_id: string
  config: Record<string, unknown>
  categories: Record<string, unknown>[]
  field_templates: Record<string, Record<string, unknown>[]>
  regex_rules: Record<string, unknown>[]
  dict_config: Record<string, unknown>
  template_code: string | null
}

/** Hook 信息 */
export interface KbHookInfo {
  kb_id: string
  has_hook: boolean
  path: string
  overridden_interfaces: string[]
  size?: number
  mtime?: number
}

/** Hook 脚本内容 */
export interface KbHookContent {
  kb_id: string
  has_hook: boolean
  content: string
  overridden_interfaces: string[]
}

/** 配置校验结果 */
export interface KbConfigValidation {
  valid: boolean
  errors: string[]
  warnings: string[]
  checks: Record<string, boolean>
}

/** 资源诊断结果 */
export interface KbResourceVerify {
  kb_id: string
  steps: Record<string, { ok: boolean; detail?: string; error?: string }>
}

/** KB 备份记录 */
export interface KbBackup {
  id: string
  kb_id: string
  user_id: string
  file_name: string
  file_size: number
  status: string
  item_counts: Record<string, number>
  created_at: string
}

/** 备份恢复统计 */
export interface KbBackupRestoreStats {
  documents: number
  documents_skipped: number
  schemas: number
  schemas_skipped: number
  terms: number
  terms_skipped: number
  domain_config: number
}

/** 单个服务校验结果 */
export interface ServiceCheckResult {
  name: string
  display_name: string
  status: 'ok' | 'error' | 'warning'
  message: string
  response_time_ms: number
  details?: Record<string, unknown>
}

/** 一键诊断所有服务结果 */
export interface ServicesDiagnoseResult {
  kb_id: string
  total: number
  ok_count: number
  error_count: number
  warning_count: number
  services: ServiceCheckResult[]
  checked_at: string
}

/** 服务配置项 */
export interface ServiceConfigItem {
  key: string
  label: string
  type: 'string' | 'number' | 'boolean' | 'password'
  value: unknown
  default?: unknown
  required?: boolean
  placeholder?: string
  description?: string
}

/** 服务配置节 */
export interface ServiceConfigSection {
  name: string
  display_name: string
  description: string
  icon?: string
  category: 'storage' | 'vector' | 'graph' | 'llm' | 'model' | 'cache'
  configurable: boolean
  fields: ServiceConfigItem[]
  last_status?: ServiceCheckResult
}

/** 新建知识库响应（含资源初始化与模板应用结果） */
export interface KbCreateResponse {
  knowledge_base: KnowledgeBase
  resources: Record<string, { ok: boolean; error: string | null; skipped?: boolean }>
  template: { applied: boolean; template_code?: string; error?: string; skipped?: boolean; reason?: string }
}
