import { http } from '@/api/client'

export type DictionaryEntryType = 'category' | 'item' | 'method'
export type DictionaryTypePath = 'categories' | 'items' | 'methods'

export const DICTIONARY_TYPE_MAP: Record<DictionaryTypePath, DictionaryEntryType> = {
  categories: 'category',
  items: 'item',
  methods: 'method',
}

export interface DictionaryEntry {
  business_code: string
  business_name: string
  type: DictionaryEntryType
  family: string | null
  aliases: string[]
  standard_no: string | null
  category_code: string | null
  category_name: string | null
  status: string
}

export interface DictionaryPayload {
  module?: string
  kb_id: string
  version: string
  source: string
  counts: { categories: number; items: number; methods: number }
  total: number
  entries: DictionaryEntry[]
}

export interface DictionaryCoverage {
  module?: string
  kb_id: string
  dictionary_version: string
  versions: Record<DictionaryEntryType, string | null>
  counts: { categories: number; items: number; methods: number }
  pending: { total: number; categories: number; items: number; methods: number }
}

export interface DictionaryEntryInput {
  business_code?: string
  business_name: string
  family?: string
  aliases?: string[]
  standard_no?: string
  category_code?: string
  category_name?: string
  facets?: Record<string, string[]>
}

export interface DictionaryAliasResult {
  module?: string
  kb_id: string
  type: DictionaryEntryType
  business_code: string
  alias: string
  aliases: string[]
  version: string
}

export interface DictionaryPendingTerm {
  document_id: string
  job_id: string
  type: DictionaryEntryType
  raw: string
  family: string
  facets: Record<string, string>
}

export interface NewTermReviewPayload {
  type: DictionaryEntryType
  raw: string
  action: 'accept' | 'map' | 'reject'
  business_code?: string
  business_name?: string
  target_code?: string
  category_code?: string
  category_name?: string
  standard_no?: string
  reason?: string
}

export const dictionaryApi = {
  get(
    moduleKey: string,
    params?: { type?: string; q?: string; limit?: number },
  ): Promise<DictionaryPayload> {
    return http.get<DictionaryPayload>(`/modules/${moduleKey}/dictionary`, {
      params: {
        type: params?.type || undefined,
        q: params?.q || undefined,
        limit: params?.limit ?? 2000,
      },
    })
  },
  getByType(
    moduleKey: string,
    dictionaryType: DictionaryTypePath,
    params?: { q?: string; limit?: number },
  ): Promise<DictionaryPayload> {
    return http.get<DictionaryPayload>(
      `/modules/${moduleKey}/dictionaries/${dictionaryType}`,
      {
        params: {
          q: params?.q || undefined,
          limit: params?.limit ?? 2000,
        },
      },
    )
  },
  coverage(moduleKey: string): Promise<DictionaryCoverage> {
    return http.get<DictionaryCoverage>(
      `/modules/${moduleKey}/dictionaries/coverage`,
    )
  },
  createEntry(
    moduleKey: string,
    dictionaryType: DictionaryTypePath,
    payload: DictionaryEntryInput,
  ): Promise<{ entry: DictionaryEntry; version: string }> {
    return http.post(
      `/modules/${moduleKey}/dictionaries/${dictionaryType}/entries`,
      payload,
    )
  },
  updateEntry(
    moduleKey: string,
    dictionaryType: DictionaryTypePath,
    businessCode: string,
    payload: Partial<DictionaryEntryInput> & { status?: string },
  ): Promise<{ entry: DictionaryEntry; version: string }> {
    return http.patch(
      `/modules/${moduleKey}/dictionaries/${dictionaryType}/entries/${encodeURIComponent(businessCode)}`,
      payload,
    )
  },
  addAlias(
    moduleKey: string,
    payload: { type: DictionaryEntryType; business_code: string; alias: string },
  ): Promise<DictionaryAliasResult> {
    return http.post<DictionaryAliasResult>(
      `/modules/${moduleKey}/dictionary/aliases`,
      payload,
    )
  },
  pending(moduleKey: string): Promise<{
    module?: string
    kb_id: string
    total: number
    items: DictionaryPendingTerm[]
  }> {
    return http.get(`/modules/${moduleKey}/dictionary/pending`)
  },
  reviewTerm(
    documentId: string,
    payload: NewTermReviewPayload,
  ): Promise<{ applied_code: string; matched: boolean; term_status: string }> {
    return http.post(`/documents/${documentId}/new-terms/review`, payload)
  },
}
