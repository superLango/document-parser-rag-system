import { apiRequest, apiUpload } from "./client";
import type { DocumentItem, RunItem } from "./types";

export const documentsApi = {
  list: () => apiRequest<DocumentItem[]>("/documents"),
  get: (id: string) => apiRequest<DocumentItem>(`/documents/${id}`),
  upload: (file: File) => apiUpload<DocumentItem>("/documents", file),
  remove: (id: string) => apiRequest<void>(`/documents/${id}`, { method: "DELETE" }),
  createRun: (id: string) =>
    apiRequest<RunItem>(`/documents/${id}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe_channel: "stable", parse_profile: "standard" })
    })
};
