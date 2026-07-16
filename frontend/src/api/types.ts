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
export type DocumentStatus = 'pending' | 'parsing' | 'completed' | 'failed'

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

export interface Document {
  id: string
  title: string
  file_name: string
  file_path: string
  file_size: number
  mime_type: string
  doc_type: string
  standard_number: string
  status: DocumentStatus
  page_count: number
  uploaded_at: string
  parsed_at: string | null
  metadata: Record<string, unknown>
  // 解析结果字段（后端 DocumentResponse 暴露，可能为 null）
  parsed_text?: string | null
  structured_data?: Record<string, unknown> | null
  layout_data?: LayoutData | null
}

export interface DocumentCreate {
  title: string
  doc_type: string
  standard_number?: string
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

export interface Schema {
  id: number
  name: string
  description: string
  doc_type: string
  fields: SchemaField[]
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SchemaCreate {
  name: string
  description: string
  doc_type: string
  fields: SchemaField[]
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
