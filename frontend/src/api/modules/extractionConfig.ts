import { http } from '@/api/client'

export interface QuerySource {
  label: string
  term_base_id: string
  group_field: string
  value_field: string
  in_query: boolean
  dedupe: boolean
  query_main_limit: number
  query_refined_limit: number
}

export interface SchemaField {
  id: string
  name: string
  type: string
  description: string
  example: string | null
  required: boolean
  sort_order: number
}

export interface SchemaCategory {
  id: string
  template_id: string
  name: string
  description: string
  return_type: string
  extraction_strategy: string
  fixed_query: string
  confidence_threshold: number | null
  top_k: number | null
  rerank_top_k: number | null
  max_tokens: number | null
  name_source: string
  name_term_base_id: string | null
  name_term_field: string
  query_sources: QuerySource[]
  is_active: boolean
  sort_order: number
  fields: SchemaField[]
}

export interface SchemaTemplate {
  id: string
  name: string
  description: string
  is_active: boolean
  sort_order: number
  created_at: string
  updated_at: string | null
  categories: SchemaCategory[]
}

export const extractionConfigApi = {
  listSchemaTemplates(kbId: string): Promise<{ items: SchemaTemplate[] }> {
    return http.get(`/kb/${kbId}/schema-templates`)
  },
  createSchemaTemplate(kbId: string, data: { name: string; description?: string; is_active?: boolean }): Promise<SchemaTemplate> {
    return http.post(`/kb/${kbId}/schema-templates`, data)
  },
  getSchemaTemplate(kbId: string, templateId: string): Promise<SchemaTemplate> {
    return http.get(`/kb/${kbId}/schema-templates/${templateId}`)
  },
  deleteSchemaTemplate(kbId: string, templateId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/schema-templates/${templateId}`)
  },
  createSchemaCategory(kbId: string, templateId: string, data: Record<string, unknown>): Promise<SchemaCategory> {
    return http.post(`/kb/${kbId}/schema-templates/${templateId}/categories`, data)
  },
  updateSchemaCategory(kbId: string, templateId: string, categoryId: string, data: Record<string, unknown>): Promise<SchemaCategory> {
    return http.put(`/kb/${kbId}/schema-templates/${templateId}/categories/${categoryId}`, data)
  },
  deleteSchemaCategory(kbId: string, templateId: string, categoryId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/schema-templates/${templateId}/categories/${categoryId}`)
  },
  createSchemaField(kbId: string, templateId: string, categoryId: string, data: Record<string, unknown>): Promise<SchemaField> {
    return http.post(`/kb/${kbId}/schema-templates/${templateId}/categories/${categoryId}/fields`, data)
  },
  updateSchemaField(kbId: string, templateId: string, categoryId: string, fieldId: string, data: Record<string, unknown>): Promise<SchemaField> {
    return http.put(`/kb/${kbId}/schema-templates/${templateId}/categories/${categoryId}/fields/${fieldId}`, data)
  },
  deleteSchemaField(kbId: string, templateId: string, categoryId: string, fieldId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/schema-templates/${templateId}/categories/${categoryId}/fields/${fieldId}`)
  },
}


export interface PromptCategoryContent {
  category_id: string
  category_name?: string
  user_prompt: string
}

export interface PromptTemplate {
  id: string
  name: string
  description: string
  scope: 'simple' | 'schema'
  schema_template_id: string | null
  category_ids: string[]
  is_active: boolean
  system_prompt: string
  user_prompt: string
  categories: PromptCategoryContent[]
  created_at: string
  updated_at: string | null
}

export const promptApi = {
  list(kbId: string): Promise<{ items: PromptTemplate[] }> {
    return http.get(`/kb/${kbId}/extraction-config/prompts`)
  },
  get(kbId: string, promptId: string): Promise<PromptTemplate> {
    return http.get(`/kb/${kbId}/extraction-config/prompts/${promptId}`)
  },
  create(kbId: string, data: Record<string, unknown>): Promise<PromptTemplate> {
    return http.post(`/kb/${kbId}/extraction-config/prompts`, data)
  },
  save(
    kbId: string,
    promptId: string,
    data: {
      system_prompt?: string
      user_prompt?: string
      categories?: PromptCategoryContent[]
      is_active?: boolean
    },
  ): Promise<PromptTemplate> {
    return http.put(`/kb/${kbId}/extraction-config/prompts/${promptId}/save`, data)
  },
  remove(kbId: string, promptId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/extraction-config/prompts/${promptId}`)
  },
}


export interface RuleGroupItem {
  id: string
  category_id: string | null
  category_name: string
  script_id: string
  script_name: string
  script_description: string
  stage: 'post' | 'validation'
  sort_order: number
}

export interface RuleGroup {
  id: string
  name: string
  schema_template_id: string | null
  schema_template_name: string
  description: string
  enabled: boolean
  category_count: number
  item_count: number
  created_at: string
}

export interface RuleGroupCategory {
  id: string
  name: string
  rules: RuleGroupItem[]
}

export interface RuleGroupDetail {
  id: string
  name: string
  schema_template_id: string | null
  schema_template_name: string
  description: string
  categories: RuleGroupCategory[]
}

export const ruleGroupApi = {
  list(kbId: string): Promise<{ items: RuleGroup[] }> {
    return http.get(`/kb/${kbId}/extraction-config/rule-groups`)
  },
  create(kbId: string, data: { schema_template_id: string; name?: string; description?: string }): Promise<{ id: string }> {
    return http.post(`/kb/${kbId}/extraction-config/rule-groups`, data)
  },
  get(kbId: string, groupId: string): Promise<RuleGroupDetail> {
    return http.get(`/kb/${kbId}/extraction-config/rule-groups/${groupId}`)
  },
  saveItems(
    kbId: string,
    groupId: string,
    data: { category_id?: string; items: Array<{ script_id: string; stage: 'post' | 'validation'; category_name?: string; sort_order?: number }> },
  ): Promise<{ message: string }> {
    return http.put(`/kb/${kbId}/extraction-config/rule-groups/${groupId}/items`, data)
  },
  remove(kbId: string, groupId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/extraction-config/rule-groups/${groupId}`)
  },
}


export interface KbScript {
  id: string
  folder: 'post' | 'validation'
  name: string
  description: string
  enabled: boolean
  code: string
  created_at: string
  updated_at: string | null
}

export interface ScriptIOFolderTool {
  name: string
  desc: string
  params: Array<{ name: string; type: string; desc: string }>
  returns: string
  usage: string
}

export interface ScriptIOFolder {
  input: Array<{ name: string; type: string; description: string }>
  output: Array<{ name: string; type: string; description: string }>
  tools: ScriptIOFolderTool[]
}

export interface ScriptRunResult {
  ok: boolean
  result?: unknown
  error?: string
}

export const scriptApi = {
  io(kbId: string): Promise<{ folders: Record<string, ScriptIOFolder> }> {
    return http.get(`/kb/${kbId}/extraction-config/scripts/io`)
  },
  list(kbId: string, folder?: string): Promise<{ items: KbScript[] }> {
    return http.get(`/kb/${kbId}/extraction-config/scripts`, { params: folder ? { folder } : undefined })
  },
  create(kbId: string, data: Record<string, unknown>): Promise<{ id: string }> {
    return http.post(`/kb/${kbId}/extraction-config/scripts`, data)
  },
  update(kbId: string, scriptId: string, data: Partial<{ folder: string; name: string; description: string; enabled: boolean; code: string }>): Promise<{ message: string }> {
    return http.put(`/kb/${kbId}/extraction-config/scripts/${scriptId}`, data)
  },
  remove(kbId: string, scriptId: string): Promise<unknown> {
    return http.delete(`/kb/${kbId}/extraction-config/scripts/${scriptId}`)
  },
  run(kbId: string, data: { script_id?: string; code?: string; args?: Record<string, unknown> }): Promise<ScriptRunResult> {
    return http.post(`/kb/${kbId}/extraction-config/scripts/run`, data)
  },
}


export interface GlobalRetrievalConfig {
  top_k: number
  candidate_mult: number
  weights: { title: number; content: number }
  default_confidence_threshold: number
  context_top_k: number
  context_max_tokens: number
  context: { chars_per_token: number; min_keep_chars: number; truncate_marker: string }
  category_recall: { mode: 'loose' | 'strict' | 'off'; top_k: number; per_dim_top_k: number }
  query_embed: { content_max_chars: number; dedupe_similarity_threshold: number }
  hybrid: { enabled: boolean; rrf_k: number; dense_weight: number; keyword_weight: number; keyword_min_hits: number }
  reranker: { enabled: boolean; model: string; top_n: number }
}

export interface GlobalEngineConfig {
  temperature: number
  top_p: number
  top_k: number
  max_tokens: number
  timeout: number
  enable_thinking: boolean
  concurrency: { max_concurrency: number; cross_category: number; within_category: number }
  batch: { single_threshold: number; batch_chars: number; overlap: number; context_truncate: number }
  format_type?: 'JSON' | 'YAML'
  fence_output?: boolean
  max_examples?: number
  passes?: number
  context_window_chars?: number
  max_char_buffer?: number
  batch_length?: number
  max_workers?: number
}

export interface GlobalLLMConfig {
  engine: 'BaseExtract' | 'LangExtractPkg'
  engines: { BaseExtract: GlobalEngineConfig; LangExtractPkg: GlobalEngineConfig }
}

export interface GlobalKbToolConfig {
  embed_batch_size: number
  search_concurrency: number
  semantic_top_k: number
  match_top_k: number
  match_threshold: number
  script_timeout: number
  script_max_output_bytes: number
  script_max_term_rows: number
}

export interface GlobalConfigContent {
  retrieval: GlobalRetrievalConfig
  llm: GlobalLLMConfig
  kb_tool: GlobalKbToolConfig
}

export interface GlobalConfig {
  enabled: boolean
  content: GlobalConfigContent
  version: number
}

export const globalConfigApi = {
  get(kbId: string): Promise<GlobalConfig> {
    return http.get(`/kb/${kbId}/extraction-config/global`)
  },
  save(kbId: string, data: { enabled: boolean; content: GlobalConfigContent }): Promise<GlobalConfig> {
    return http.put(`/kb/${kbId}/extraction-config/global`, data)
  },
}
