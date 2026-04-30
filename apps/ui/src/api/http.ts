const DEFAULT_TIMEOUT_MS = 10000;
const WHITESPACE_RE = /\s+/g;
const DEFAULT_TIMEOUT_MESSAGE = "Request timed out.";

function composeSignal(
  timeoutSignal: AbortSignal,
  externalSignal?: AbortSignal,
): AbortSignal {
  if (!externalSignal) return timeoutSignal;
  return AbortSignal.any([timeoutSignal, externalSignal]);
}

function formatBodySnippet(text: string): string {
  const compact = text.trim().replace(WHITESPACE_RE, " ");
  return compact.slice(0, 160);
}

export interface ApiJsonResponse<T> {
  status: number;
  body: T | undefined;
}

export interface ApiJsonInit extends RequestInit {
  timeoutMs?: number;
}

export async function apiJsonResponse<T = unknown>(
  path: string,
  init?: ApiJsonInit,
): Promise<ApiJsonResponse<T>> {
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal: externalSignal,
    ...requestInit
  } = init ?? {};
  const timeoutController = new AbortController();
  const timeoutId = globalThis.setTimeout(
    () =>
      timeoutController.abort(
        new DOMException(DEFAULT_TIMEOUT_MESSAGE, "AbortError"),
      ),
    timeoutMs,
  );
  const signal = composeSignal(
    timeoutController.signal,
    externalSignal ?? undefined,
  );
  try {
    const response = await fetch(path, { ...requestInit, signal });
    const bodyText = await response.text();
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = bodyText ? JSON.parse(bodyText) : null;
        if (
          payload &&
          typeof payload === "object" &&
          typeof payload.detail !== "undefined"
        ) {
          detail = String(payload.detail);
        }
      } catch {
        if (bodyText.trim())
          detail = `${detail}: ${formatBodySnippet(bodyText)}`;
      }
      throw new Error(detail);
    }
    if (response.status === 204 || !bodyText.trim()) {
      return { status: response.status, body: undefined };
    }

    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      return { status: response.status, body: bodyText as T };
    }

    try {
      return { status: response.status, body: JSON.parse(bodyText) as T };
    } catch {
      const status = `${response.status} ${response.statusText}`;
      throw new Error(
        `Invalid JSON response (${status}): ${formatBodySnippet(bodyText)}`,
      );
    }
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

export async function apiJson<T = unknown>(
  path: string,
  init?: ApiJsonInit,
): Promise<T> {
  const response = await apiJsonResponse<T>(path, init);
  return response.body as T;
}
