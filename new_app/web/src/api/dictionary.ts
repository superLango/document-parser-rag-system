import { apiRequest, toQuery } from "./client";
import type { DictionaryPayload } from "./types";

export const dictionaryApi = {
  query: (params: { type?: string; q?: string; family?: string; status?: string } = {}) =>
    apiRequest<DictionaryPayload>(`/dictionary${toQuery(params)}`)
};
