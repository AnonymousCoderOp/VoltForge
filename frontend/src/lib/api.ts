export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

export async function apiGet<T = any>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`${path} returned HTTP ${response.status}${detail ? `: ${detail.slice(0, 160)}` : ""}`);
  }

  return response.json() as Promise<T>;
}

export async function apiPost<T = any>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`${path} returned HTTP ${response.status}${detail ? `: ${detail.slice(0, 160)}` : ""}`);
  }

  return response.json() as Promise<T>;
}

export function getWebSocketUrl(): string {
  return API_BASE_URL.replace(/^https:/, "wss:").replace(/^http:/, "ws:") + "/ws";
}
