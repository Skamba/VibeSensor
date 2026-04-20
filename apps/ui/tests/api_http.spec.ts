import { beforeEach, describe, expect, test } from "vitest";
import { apiJson } from "../src/api/http";
import { createDeferred, installTimerHarness, installWindowGlobal } from "./async_test_helpers";
import { HttpResponse, http, uiTestUrl } from "./msw/http";
import { createUiMswTestServer } from "./msw/node";

const mswServer = createUiMswTestServer();

describe("apiJson", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("timeout aborts with and without provided AbortSignal", async () => {
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const externalController = new AbortController();

    mswServer.use(
      http.get(uiTestUrl("/timeout/no-signal"), async () => await new Promise<HttpResponse>(() => undefined)),
      http.get(uiTestUrl("/timeout/with-signal"), async () => await new Promise<HttpResponse>(() => undefined)),
    );
    globalThis.setTimeout = ((handler: TimerHandler) => {
      if (typeof handler === "function") handler();
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout;
    globalThis.clearTimeout = (() => {}) as typeof clearTimeout;

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
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    }
  });

  test("supports custom timeout overrides and clears their timers after a successful response", async () => {
    const timerHarness = installTimerHarness();
    const response = createDeferred<HttpResponse>();
    let requestedPath = "";
    let requestedMethod = "";
    mswServer.use(
      http.post(uiTestUrl("/timeout/custom"), async ({ request }) => {
        requestedPath = new URL(request.url).pathname;
        requestedMethod = request.method;
        return await response.promise;
      }),
    );

    try {
      const request = apiJson<{ ok: boolean }>("/timeout/custom", {
        method: "POST",
        timeoutMs: 20_000,
      });

      expect(timerHarness.pendingDelays()).toEqual([20_000]);

      response.resolve(HttpResponse.json({ ok: true }));
      await expect(request).resolves.toEqual({ ok: true });
      expect(requestedPath).toBe("/timeout/custom");
      expect(requestedMethod).toBe("POST");
      expect(timerHarness.pendingDelays()).toEqual([]);
    } finally {
      timerHarness.restore();
    }
  });

  test("handles 204, text response, invalid JSON and non-2xx JSON detail", async () => {
    mswServer.use(
      http.get(uiTestUrl("/status204"), () => new HttpResponse(null, { status: 204, statusText: "No Content" })),
      http.get(uiTestUrl("/text-ok"), () => new HttpResponse("plain-text", { status: 200, statusText: "OK" })),
      http.get(uiTestUrl("/invalid-json"), () =>
        new HttpResponse("{nope", {
          status: 200,
          statusText: "OK",
          headers: { "content-type": "application/json" },
        }),
      ),
      http.get(uiTestUrl("/error-json"), () =>
        HttpResponse.json({ detail: "bad request detail" }, { status: 400, statusText: "Bad Request" }),
      ),
    );

    const payload204 = await apiJson("/status204");
    const payloadText = await apiJson("/text-ok");
    await expect(apiJson("/invalid-json")).rejects.toThrow(/Invalid JSON response \(200 OK\)/);
    await expect(apiJson("/error-json")).rejects.toThrow("bad request detail");
    expect(payload204).toBeUndefined();
    expect(payloadText).toBe("plain-text");
  });
});
