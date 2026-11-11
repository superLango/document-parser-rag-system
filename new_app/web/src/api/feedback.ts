import { apiRequest, toQuery } from "./client";
import type { FeedbackDetail, VerificationPackage } from "./types";

export type FeedbackCreateInput = {
  run_id: string;
  category: string;
  target: Record<string, string>;
  description: string;
  expected_value?: string;
  source_quote?: string;
  reporter?: string;
};

export const feedbackApi = {
  list: (params: { document_id?: string; run_id?: string; status?: string } = {}) =>
    apiRequest<FeedbackDetail[]>(`/feedback${toQuery(params)}`),
  create: (payload: FeedbackCreateInput) =>
    apiRequest<FeedbackDetail>("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  process: (id: string) =>
    apiRequest<FeedbackDetail>(`/feedback/${id}/process`, { method: "POST" }),
  verification: (id: string) =>
    apiRequest<VerificationPackage>(`/feedback/${id}/verification`),
  verify: (id: string, decision: "approve" | "reject", reason: string) =>
    apiRequest<FeedbackDetail>(`/feedback/${id}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reason, actor: "local" })
    })
};
