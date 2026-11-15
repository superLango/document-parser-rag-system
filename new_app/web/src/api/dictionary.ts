import { apiRequest, toQuery } from "./client";
import type { DictionaryImportResult, DictionaryPayload } from "./types";

export const dictionaryApi = {
  query: (
    params: {
      type?: string;
      q?: string;
      family?: string;
      status?: string;
      limit?: number;
    } = {}
  ) => apiRequest<DictionaryPayload>(`/dictionary${toQuery(params)}`),
  import: (entries: Record<string, unknown>[], replace = false) =>
    apiRequest<DictionaryImportResult>("/dictionary/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries, replace })
    })
};
