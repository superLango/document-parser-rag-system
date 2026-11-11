export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `请求失败（${status}）`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/v1";
const OPERATOR = "local";

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function errorMessage(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
  }
  return "";
}

async function parseBody(response: Response): Promise<unknown> {
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("X-Operator", OPERATOR);
  if (method !== "GET" && method !== "HEAD") {
    headers.set("Idempotency-Key", newIdempotencyKey());
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await parseBody(response).catch(() => null);
    throw new ApiError(response.status, errorMessage(payload) || payload);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await parseBody(response)) as T;
}

export function apiUpload<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<T>(path, { method: "POST", body });
}

export function toQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
