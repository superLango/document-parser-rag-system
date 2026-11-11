const API_BASE = "/v1";

export type Health = {
  status: string;
  service: string;
  version: string;
};

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API ${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}
