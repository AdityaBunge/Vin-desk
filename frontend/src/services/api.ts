/** HTTP client for the backend API.
 *
 * The access token lives only in memory. The refresh token is an httpOnly cookie the browser
 * sends to /api/auth/refresh, so a page reload restores the session without any token in
 * localStorage.
 */
import type { TokenResponse } from "@/types";

const BASE = "/api";
let accessToken: string | null = null;
let refreshing: Promise<TokenResponse | null> | null = null;
let onSessionLost: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function setSessionLostHandler(handler: (() => void) | null) {
  onSessionLost = handler;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  data?: Record<string, unknown>;
  constructor(status: number, message: string, code?: string, data?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

/** Turn FastAPI's `detail` (string | object | validation list) into one readable message. */
export function parseError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(status, detail);
  if (Array.isArray(detail)) {
    const text = detail
      .map((d: { loc?: (string | number)[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((p) => p !== "body").join(".");
        return field ? `${field}: ${d.msg}` : String(d.msg);
      })
      .join("; ");
    return new ApiError(status, text || "The submitted data is not valid");
  }
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    return new ApiError(status, String(d.message ?? "Request failed"), d.code as string | undefined, d);
  }
  return new ApiError(status, status >= 500 ? "The server could not process the request" : "Request failed");
}

type Params = Record<string, string | number | boolean | null | undefined>;
export interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Params;
  formData?: FormData;
  signal?: AbortSignal;
}

function buildUrl(path: string, params?: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const qs = query.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function send(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (opts.formData) body = opts.formData;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  return fetch(buildUrl(path, opts.params), {
    method: opts.method ?? "GET",
    headers,
    body,
    credentials: "same-origin",
    signal: opts.signal,
  });
}

export function refreshSession(): Promise<TokenResponse | null> {
  // Single-flight: concurrent 401s share one refresh (refresh tokens are single-use).
  refreshing ??= fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" })
    .then(async (r) => {
      if (!r.ok) return null;
      const data = (await r.json()) as TokenResponse;
      accessToken = data.access_token;
      return data;
    })
    .catch(() => null)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function request(path: string, opts: RequestOptions): Promise<Response> {
  let response = await send(path, opts);
  if (response.status === 401 && !path.startsWith("/auth/") && !path.startsWith("/public/")) {
    const renewed = await refreshSession();
    if (renewed) response = await send(path, opts);
    else onSessionLost?.();
  }
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* non-JSON error body */
    }
    throw parseError(response.status, body);
  }
  return response;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const response = await request(path, opts);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T>(path: string, params?: Params) => api<T>(path, { params });
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body });
export const patch = <T>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

export async function getBlob(path: string, params?: Params): Promise<Blob> {
  return (await request(path, { params })).blob();
}

/** Open an authenticated file (PDF) in a new tab, or download it when `filename` is given. */
export async function openFile(path: string, params?: Params, filename?: string): Promise<void> {
  const blob = await getBlob(path, params);
  const url = URL.createObjectURL(blob);
  if (filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  } else {
    window.open(url, "_blank", "noopener");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
