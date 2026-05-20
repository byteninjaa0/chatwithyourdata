const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8001";

export type FastApiJson<T = Record<string, unknown>> = {
  ok: boolean;
  status: number;
  data: T;
};

/** Call FastAPI and always return JSON (never throw on non-JSON error bodies). */
export async function fetchFastApi<T = Record<string, unknown>>(
  path: string,
  init?: RequestInit,
): Promise<FastApiJson<T>> {
  const url = `${FASTAPI_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  try {
    const res = await fetch(url, { cache: "no-store", ...init });
    const text = await res.text();
    let data: T;
    try {
      data = text ? (JSON.parse(text) as T) : ({} as T);
    } catch {
      data = {
        detail: text || res.statusText || "Non-JSON response from FastAPI",
      } as T;
    }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return {
      ok: false,
      status: 502,
      data: {
        detail: `Could not reach FastAPI: ${(err as Error).message}`,
      } as T,
    };
  }
}
