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
export type TaskStatus = 'queued' | 'running' | 'success' | 'failed'

export interface Task {
  id: string
  document_id: string
  task_type: string
  status: TaskStatus
  progress: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  error_message: string | null
  result: Record<string, unknown> | null
}

// ---------- 任务提交 ----------
export interface TaskCreateRequest {
  document_id: string
  schema_id?: string
  term_base_id?: string
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
