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

export interface Document {
  id: number
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
}

export interface DocumentCreate {
  title: string
  doc_type: string
  standard_number?: string
}

// ---------- 解析任务 ----------
export type TaskStatus = 'queued' | 'running' | 'success' | 'failed'

export interface Task {
  id: number
  document_id: number
  task_type: string
  status: TaskStatus
  progress: number
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  result: Record<string, unknown> | null
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
  document_id: number
  document_title: string
  page: number
  snippet: string
  score: number
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
