import { expect, test } from "@playwright/test";
import { apiJson } from "../src/api/http";

test.describe("apiJson", () => {
  test.beforeEach(() => {
    (globalThis as { window?: Window & typeof globalThis }).window = globalThis as unknown as Window &
      typeof globalThis;
  });

  test("timeout aborts with and without provided AbortSignal", async () => {
    const originalFetch = globalThis.fetch;
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const externalController = new AbortController();

    globalThis.setTimeout = ((handler: TimerHandler) => {
      if (typeof handler === "function") handler();
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout;
    globalThis.clearTimeout = (() => {}) as typeof clearTimeout;
    globalThis.fetch = ((_: string | URL | Request, init?: RequestInit) =>
      new Promise((_, reject) => {
        if (init?.signal?.aborted) {
          reject(new DOMException("Aborted", "AbortError"));
          return;
        }
        init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      })) as typeof fetch;

    try {
      const outcomes = await Promise.all([
        apiJson("/timeout/no-signal")
          .then(() => "resolved")
          .catch((err) => err.name || String(err)),
        apiJson("/timeout/with-signal", { signal: externalController.signal })
          .then(() => "resolved")
          .catch((err) => err.name || String(err)),
      ]);
      expect(outcomes).toEqual(["AbortError", "AbortError"]);
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    }
  });

  test("handles 204, text response, invalid JSON and non-2xx JSON detail", async () => {
    const originalFetch = globalThis.fetch;
    const mkResponse = (
      body: string | null,
      status: number,
      statusText: string,
      contentType: string,
    ) => new Response(body, { status, statusText, headers: { "content-type": contentType } });
    globalThis.fetch = (async (path: string | URL | RequestInfo) => {
      const value = String(path);
      if (value.includes("status204")) return mkResponse(null, 204, "No Content", "application/json");
      if (value.includes("text-ok")) return mkResponse("plain-text", 200, "OK", "text/plain");
      if (value.includes("invalid-json")) return mkResponse("{nope", 200, "OK", "application/json");
      if (value.includes("error-json")) {
        return mkResponse(JSON.stringify({ detail: "bad request detail" }), 400, "Bad Request", "application/json");
      }
      return mkResponse("unknown", 500, "Unknown", "text/plain");
    }) as typeof fetch;

    try {
      const payload204 = await apiJson("/status204");
      const payloadText = await apiJson("/text-ok");
      await expect(apiJson("/invalid-json")).rejects.toThrow(/Invalid JSON response \(200 OK\)/);
      await expect(apiJson("/error-json")).rejects.toThrow("bad request detail");
      expect(payload204).toBeUndefined();
      expect(payloadText).toBe("plain-text");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
