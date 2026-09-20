import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ExtractPlanResponse,
  ExtractSqlResponse,
  HealthResponse,
} from "../types/api";

const API_BASE = "/api";

/** Error carrying the backend's own friendly `detail` text (PRD: backend is the validation authority). */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function extractDetail(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  // FastAPI/Pydantic validation errors: detail is a list of {msg, loc, ...}.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as unknown;
    if (first && typeof first === "object" && "msg" in first) {
      const msg = (first as { msg: unknown }).msg;
      if (typeof msg === "string" && msg.trim()) return msg;
    }
  }
  return null;
}

async function parseJsonOrThrow<T>(res: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // Non-JSON or empty body; `body` stays null and we fall back below.
  }
  if (!res.ok) {
    const detail = extractDetail(body) ?? `伺服器發生錯誤（狀態碼 ${res.status}），請稍後再試一次。`;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`, { signal });
  return parseJsonOrThrow<HealthResponse>(res);
}

/** multipart/form-data upload — never persisted server-side (PRD §6.3 / §40). */
export async function extractSql(file: File, signal?: AbortSignal): Promise<ExtractSqlResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/extract-sql`, {
    method: "POST",
    body: form,
    signal,
  });
  return parseJsonOrThrow<ExtractSqlResponse>(res);
}

export async function extractPlan(file: File, signal?: AbortSignal): Promise<ExtractPlanResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/extract-plan`, {
    method: "POST",
    body: form,
    signal,
  });
  return parseJsonOrThrow<ExtractPlanResponse>(res);
}

export async function analyze(
  body: AnalyzeRequest,
  signal?: AbortSignal,
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return parseJsonOrThrow<AnalyzeResponse>(res);
}
