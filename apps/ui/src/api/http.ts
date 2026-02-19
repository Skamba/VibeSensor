export async function apiJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Ignore parse errors on non-JSON responses.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
