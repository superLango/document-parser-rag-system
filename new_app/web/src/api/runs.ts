import { apiRequest, toQuery } from "./client";
import type {
  CrossStandardPayload,
  OcrPayload,
  RecordsPayload,
  ReviewReport,
  RunIntelligence,
  RunItem,
  RunResult,
  RunTimeline
} from "./types";

const EVENT_TYPES = [
  "run.created",
  "run.stage.started",
  "run.stage.completed",
  "run.stage.failed",
  "run.completed",
  "run.cancelled",
  "run.human_review_required",
  "run.human_approved",
  "run.human_rejected",
  "run.repair.started",
  "run.repair.reparsing",
  "run.route.needs_human",
  "artifact.created",
  "promotion.completed"
];

export const runsApi = {
  list: (documentId?: string) =>
    apiRequest<RunItem[]>(`/runs${toQuery({ document_id: documentId })}`),
  get: (id: string) => apiRequest<RunItem>(`/runs/${id}`),
  result: (id: string) => apiRequest<RunResult>(`/runs/${id}/result`),
  records: (id: string) => apiRequest<RecordsPayload>(`/runs/${id}/records`),
  intelligence: (id: string) =>
    apiRequest<RunIntelligence>(`/runs/${id}/intelligence`),
  review: (id: string) => apiRequest<ReviewReport>(`/runs/${id}/review`),
  ocr: (id: string) => apiRequest<OcrPayload>(`/runs/${id}/ocr`),
  crossStandard: (id: string) =>
    apiRequest<CrossStandardPayload>(`/runs/${id}/cross-standard`),
  timeline: (id: string) => apiRequest<RunTimeline>(`/runs/${id}/timeline`),
  cancel: (id: string) => apiRequest<RunItem>(`/runs/${id}/cancel`, { method: "POST" }),
  approve: (id: string) =>
    apiRequest<Record<string, unknown>>(
      `/runs/${id}/accept?actor=local&note=ui`,
      { method: "POST" }
    ),
  reject: (id: string) =>
    apiRequest<Record<string, unknown>>(
      `/runs/${id}/reject?actor=local&reason=ui`,
      { method: "POST" }
    ),
  subscribeEvents: (
    id: string,
    after: number,
    onEvent: (event: unknown) => void
  ): (() => void) => {
    const source = new EventSource(`/v1/runs/${id}/events${toQuery({ after })}`);
    const handle = (message: MessageEvent<string>) => {
      try {
        onEvent(JSON.parse(message.data));
      } catch {
        onEvent(null);
      }
    };
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, handle as EventListener);
    }
    source.addEventListener("done", () => source.close());
    return () => source.close();
  }
};
