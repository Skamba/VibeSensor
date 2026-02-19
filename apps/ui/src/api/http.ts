const DEFAULT_TIMEOUT_MS = 10000;

export async function apiJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const timeoutMs = DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const response = await fetch(path, { ...init, signal: init?.signal ?? controller.signal }).finally(() =>
    window.clearTimeout(timeoutId),
  );
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail !== "undefined") {
        detail = String(payload.detail);
      }
    } catch {
      // Ignore parse errors on non-JSON responses.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
