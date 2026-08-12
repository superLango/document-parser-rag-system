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
  updateSchemaTemplate(kbId: string, templateId: string, data: Partial<{ name: string; description: string; is_active: boolean }>): Promise<SchemaTemplate> {
    return http.put(`/kb/${kbId}/schema-templates/${templateId}`, data)
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
