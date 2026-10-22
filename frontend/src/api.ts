// Обращение к REST API: токен, ошибки на русском, скачивание файлов.

const TOKEN_KEY = "floraplan.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* без localStorage вход живёт до перезагрузки */
  }
}

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(status: number, message: string, data: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(f: () => void) {
  onUnauthorized = f;
}

function message(status: number, data: any): string {
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail)) {
    return data.detail
      .map((e: any) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`)
      .join("; ");
  }
  if (status === 403) return "Недостаточно прав";
  if (status >= 500) return "Ошибка сервера";
  return `Ошибка ${status}`;
}

function qs(params?: Record<string, any>): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, String(x)));
    else u.append(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function request(method: string, url: string, body?: any, params?: Record<string, any>, raw = false) {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData || body instanceof URLSearchParams) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const r = await fetch(url + qs(params), { method, headers, body: payload });
  if (r.status === 401 && !url.endsWith("/auth/token")) onUnauthorized();
  if (!r.ok) {
    let data: any = null;
    try {
      data = await r.json();
    } catch {
      /* ответ без JSON */
    }
    throw new ApiError(r.status, message(r.status, data), data);
  }
  if (raw) return r;
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

export const api = {
  get: <T = any>(url: string, params?: Record<string, any>) => request("GET", url, undefined, params) as Promise<T>,
  post: <T = any>(url: string, body?: any, params?: Record<string, any>) => request("POST", url, body, params) as Promise<T>,
  put: <T = any>(url: string, body?: any) => request("PUT", url, body) as Promise<T>,
  del: <T = any>(url: string) => request("DELETE", url) as Promise<T>,
};

/** Скачать файл (XLSX, резервная копия) с авторизацией. */
export async function download(url: string, params?: Record<string, any>) {
  const r = (await request("GET", url, undefined, params, true)) as Response;
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : "file";
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/** Открыть HTML-ответ (этикетки) в новом окне для печати. */
export async function openHtml(url: string, params?: Record<string, any>) {
  const r = (await request("GET", url, undefined, params, true)) as Response;
  const html = await r.text();
  const w = window.open("", "_blank");
  if (w) {
    w.document.open();
    w.document.write(html);
    w.document.close();
  }
}
