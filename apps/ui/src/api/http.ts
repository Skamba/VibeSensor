const DEFAULT_TIMEOUT_MS = 10000;

function composeSignal(
  timeoutSignal: AbortSignal,
  externalSignal?: AbortSignal,
): { signal: AbortSignal; cleanup: () => void } {
  if (!externalSignal) return { signal: timeoutSignal, cleanup: () => {} };
  if ("any" in AbortSignal) {
    return { signal: AbortSignal.any([timeoutSignal, externalSignal]), cleanup: () => {} };
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
  const compact = text.trim().replace(/\s+/g, " ");
  return compact.slice(0, 160);
}

export async function apiJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const timeoutMs = DEFAULT_TIMEOUT_MS;
  const timeoutController = new AbortController();
  const timeoutId = window.setTimeout(() => timeoutController.abort(), timeoutMs);
  const { signal, cleanup } = composeSignal(timeoutController.signal, init?.signal);
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
  if (response.status === 204 || !bodyText.trim()) return undefined as T;

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) return bodyText as T;

  try {
    return JSON.parse(bodyText) as T;
  } catch {
    const status = `${response.status} ${response.statusText}`;
    throw new Error(`Invalid JSON response (${status}): ${formatBodySnippet(bodyText)}`);
  }
}
