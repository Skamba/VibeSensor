const DEFAULT_TIMEOUT_MS = 10000;
const NOOP = () => {};
const WHITESPACE_RE = /\s+/g;

function composeSignal(
  timeoutSignal: AbortSignal,
  externalSignal?: AbortSignal,
): { signal: AbortSignal; cleanup: () => void } {
  if (!externalSignal) return { signal: timeoutSignal, cleanup: NOOP };
  if ("any" in AbortSignal) {
    return { signal: AbortSignal.any([timeoutSignal, externalSignal]), cleanup: NOOP };
  }

  const controller = new AbortController();
  const abortFromExternal = () => controller.abort(externalSignal.reason);
  const abortFromTimeout = () => controller.abort(timeoutSignal.reason);
  externalSignal.addEventListener("abort", abortFromExternal, { once: true });
  timeoutSignal.addEventListener("abort", abortFromTimeout, { once: true });
  if (externalSignal.aborted) abortFromExternal();
  if (timeoutSignal.aborted) abortFromTimeout();
  return {
    signal: controller.signal,
    cleanup: () => {
      externalSignal.removeEventListener("abort", abortFromExternal);
      timeoutSignal.removeEventListener("abort", abortFromTimeout);
    },
  };
}

function formatBodySnippet(text: string): string {
  const compact = text.trim().replace(WHITESPACE_RE, " ");
  return compact.slice(0, 160);
}

export interface ApiJsonResponse<T> {
  status: number;
  body: T | undefined;
}

export async function apiJsonResponse<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<ApiJsonResponse<T>> {
  const timeoutController = new AbortController();
  const timeoutId = window.setTimeout(() => timeoutController.abort(), DEFAULT_TIMEOUT_MS);
  const { signal, cleanup } = composeSignal(timeoutController.signal, init?.signal ?? undefined);
  const response = await fetch(path, { ...init, signal }).finally(() => {
    window.clearTimeout(timeoutId);
    cleanup();
  });
  const bodyText = await response.text();
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = bodyText ? JSON.parse(bodyText) : null;
      if (payload && typeof payload === "object" && typeof payload.detail !== "undefined") {
        detail = String(payload.detail);
      }
    } catch {
      if (bodyText.trim()) detail = `${detail}: ${formatBodySnippet(bodyText)}`;
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
    throw new Error(`Invalid JSON response (${status}): ${formatBodySnippet(bodyText)}`);
  }
}

export async function apiJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiJsonResponse<T>(path, init);
  return response.body as T;
}
