import { apiRequest, toQuery } from "./client";
import type {
  OcrPayload,
  RecordsPayload,
  ReviewReport,
  RunItem,
  RunResult,
  RunTimeline
} from "./types";

export const runsApi = {
  list: (documentId?: string) =>
    apiRequest<RunItem[]>(`/runs${toQuery({ document_id: documentId })}`),
  get: (id: string) => apiRequest<RunItem>(`/runs/${id}`),
  result: (id: string) => apiRequest<RunResult>(`/runs/${id}/result`),
  records: (id: string) => apiRequest<RecordsPayload>(`/runs/${id}/records`),
  review: (id: string) => apiRequest<ReviewReport>(`/runs/${id}/review`),
  ocr: (id: string) => apiRequest<OcrPayload>(`/runs/${id}/ocr`),
  timeline: (id: string) => apiRequest<RunTimeline>(`/runs/${id}/timeline`),
  cancel: (id: string) => apiRequest<RunItem>(`/runs/${id}/cancel`, { method: "POST" }),
  pageImage: (id: string, pageNo: number) => `/v1/runs/${id}/pages/${pageNo}/image`
};
