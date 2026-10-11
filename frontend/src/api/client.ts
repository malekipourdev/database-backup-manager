import type { TFunction } from "i18next";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly detail?: string,
    public readonly fields?: Record<string, string>,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body } = options;
  const headers: Record<string, string> = { "X-Requested-With": "mbp" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error");
  }

  if (!response.ok) {
    let data: { code?: string; detail?: string; fields?: Record<string, string> } = {};
    try {
      data = await response.json();
    } catch {
      // Non-JSON error body (e.g. proxy error page).
    }
    throw new ApiError(response.status, data.code ?? "internal_error", data.detail, data.fields);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code);
}

/** Translated, user-facing message for any error thrown by apiFetch. */
export function errorMessage(t: TFunction, error: unknown): string {
  const code = error instanceof ApiError ? error.code : "internal_error";
  const name = error instanceof ApiError ? error.detail : undefined;
  return t(`errors.${code}`, { defaultValue: t("errors.internal_error"), name });
}
