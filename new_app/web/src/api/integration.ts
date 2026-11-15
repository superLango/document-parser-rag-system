export type IntegrationEnvelope<T> = {
  code: number;
  message: string;
  data: T;
  trace_id: string;
};

export type IntegrationTaskView = {
  task_id: string;
  kb_id: string | null;
  document_id: string;
  prompt_id: string;
  schema_template_id: string;
  filename: string;
  ocr_status: "pending" | "processing" | "completed" | "failed";
  ocr_progress: number;
  extract_status: "pending" | "running" | "completed" | "failed";
  extract_progress: number;
  error: string;
  result_version: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type IntegrationResult = {
  schema_template_id: string;
  schema_name: string;
  status: "running" | "completed" | "failed";
  progress: number;
  categories: {
    feature: string;
    records: Record<string, string>[];
    rejected: unknown[];
    missing_fields: string[];
    hit_count: number;
  }[];
  summary: { total_records?: number; kept_categories?: number };
  timing: { total_sec?: number };
  version: number | null;
  error: string | null;
  updated_at: string | null;
};

const BASE = "/api/v1/integration";

async function unwrap<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as IntegrationEnvelope<T>;
  if (!response.ok || payload.code !== 0) {
    throw new Error(payload.message || `请求失败（${response.status}）`);
  }
  return payload.data;
}

export const integrationApi = {
  status: async (taskId: string) =>
    unwrap<IntegrationTaskView>(await fetch(`${BASE}/tasks/${taskId}/status`)),
  result: async (taskId: string) =>
    unwrap<IntegrationResult>(await fetch(`${BASE}/tasks/${taskId}/result`)),
  retrigger: async (taskId: string) =>
    unwrap<IntegrationTaskView>(
      await fetch(`${BASE}/tasks/${taskId}/retrigger`, { method: "POST" })
    ),
  sessionToken: async (taskId: string) =>
    unwrap<{
      task_id: string;
      token: string;
      document_id: string;
      kb_id: string | null;
      expires_at: string;
      path: string;
    }>(await fetch(`${BASE}/tasks/${taskId}/session-token`))
};
