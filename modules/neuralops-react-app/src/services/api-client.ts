import { useAuthStore } from "@/store/auth.store";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function apiRequest(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const { serverUrl, supabaseToken } = useAuthStore.getState();
  if (!serverUrl) throw new ApiError(0, "No server selected");

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (supabaseToken) headers.Authorization = `Bearer ${supabaseToken}`;

  return fetch(`${serverUrl}${path}`, { ...options, headers });
}

export async function apiJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await apiRequest(path, options);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    // Try to extract a clean error message from Django Ninja JSON errors
    try {
      const parsed = JSON.parse(text);
      const detail = parsed?.detail ?? parsed?.message ?? text;
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw new ApiError(res.status, text);
    }
  }
  // 204 No Content — nothing to parse
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
