// API client: bearer token in memory, httpOnly refresh cookie, workspace header, RFC 7807 errors.

export class ApiError extends Error {
  status: number;
  detail?: string;
  errors?: { loc: (string | number)[]; msg: string }[] | string[];
  body: Record<string, unknown>;
  constructor(status: number, body: Record<string, unknown>) {
    super((body.detail as string) || (body.title as string) || `Request failed (${status})`);
    this.status = status;
    this.detail = body.detail as string | undefined;
    this.errors = body.errors as ApiError["errors"];
    this.body = body;
  }
}

let accessToken: string | null = null;
let workspaceId: string | null = typeof window !== "undefined" ? localStorage.getItem("bep.workspace") : null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

export const session = {
  get token() {
    return accessToken;
  },
  set token(t: string | null) {
    accessToken = t;
    listeners.forEach((l) => l());
  },
  get workspace() {
    return workspaceId;
  },
  set workspace(id: string | null) {
    workspaceId = id;
    if (typeof window !== "undefined") {
      if (id) localStorage.setItem("bep.workspace", id);
      else localStorage.removeItem("bep.workspace");
    }
    listeners.forEach((l) => l());
  },
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

export async function refreshToken(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) return false;
        session.token = (await r.json()).access_token;
        return true;
      })
      .catch(() => false)
      .finally(() => {
        setTimeout(() => (refreshing = null), 0);
      });
  }
  return refreshing;
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function qs(params?: Query): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function request<T = unknown>(
  method: string,
  path: string,
  opts: { body?: unknown; query?: Query; form?: FormData; raw?: boolean; retry?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`/api/v1${path}${qs(opts.query)}`, { method, headers, body, credentials: "same-origin" });
  if (res.status === 401 && opts.retry !== false && !path.startsWith("/auth/")) {
    if (await refreshToken()) return request<T>(method, path, { ...opts, retry: false });
    session.token = null;
  }
  if (!res.ok) {
    let data: Record<string, unknown> = {};
    try {
      data = await res.json();
    } catch {
      data = { detail: res.statusText };
    }
    throw new ApiError(res.status, data);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T = unknown>(p: string, query?: Query) => request<T>("GET", p, { query }),
  post: <T = unknown>(p: string, body?: unknown, query?: Query) => request<T>("POST", p, { body, query }),
  patch: <T = unknown>(p: string, body?: unknown) => request<T>("PATCH", p, { body }),
  put: <T = unknown>(p: string, body?: unknown) => request<T>("PUT", p, { body }),
  del: <T = unknown>(p: string, body?: unknown) => request<T>("DELETE", p, { body }),
  upload: <T = unknown>(p: string, form: FormData) => request<T>("POST", p, { form }),
};

export async function download(path: string, query?: Query) {
  const res = await request<Response>("GET", path, { query, raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] || "download";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (Array.isArray(e.errors) && e.errors.length) {
      return e.errors
        .map((x) => (typeof x === "string" ? x : `${x.loc.slice(1).join(".")}: ${x.msg}`))
        .join("\n");
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}
