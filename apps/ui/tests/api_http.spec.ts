import { beforeEach, describe, expect, test } from "vitest";
import { apiJson } from "../src/api/http";
import { scanSettingsObdDevices } from "../src/api/settings";
import {
  createDeferred,
  installTimerHarness,
  installWindowGlobal,
} from "./async_test_helpers";
import { json, route, stubFetch } from "./fetch_stub";

const server = stubFetch();

describe("apiJson", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("timeout aborts with and without provided AbortSignal", async () => {
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const externalController = new AbortController();

    server.use(
      route(
        "GET /timeout/no-signal",
        async () => await new Promise<Response>(() => undefined),
      ),
      route(
        "GET /timeout/with-signal",
        async () => await new Promise<Response>(() => undefined),
      ),
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
    const response = createDeferred<Response>();
    let requestedPath = "";
    let requestedMethod = "";
    server.use(
      route("POST /timeout/custom", async (request) => {
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

      response.resolve(json({ ok: true }));
      await expect(request).resolves.toEqual({ ok: true });
      expect(requestedPath).toBe("/timeout/custom");
      expect(requestedMethod).toBe("POST");
      expect(timerHarness.pendingDelays()).toEqual([]);
    } finally {
      timerHarness.restore();
    }
  });

  test("settings OBD scan uses the extended scan timeout without wall-clock delay", async () => {
    const timerHarness = installTimerHarness();
    const response = createDeferred<Response>();
    server.use(
      route("POST /api/settings/obd/scan", async () => await response.promise),
    );

    try {
      const request = scanSettingsObdDevices();

      expect(timerHarness.pendingDelays()).toEqual([30_000]);

      response.resolve(json({ devices: [] }));
      await expect(request).resolves.toEqual({ devices: [] });
      expect(timerHarness.pendingDelays()).toEqual([]);
    } finally {
      timerHarness.restore();
    }
  });

  test("keeps timeout active while reading the response body", async () => {
    const originalFetch = globalThis.fetch;
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const bodyText = createDeferred<string>();
    let timeoutHandler: TimerHandler | undefined;
    let clearedTimeout = false;

    globalThis.fetch = (async (_input, _init) => {
      return {
        headers: new Headers({ "content-type": "application/json" }),
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => await bodyText.promise,
      } as Response;
    }) as typeof fetch;
    globalThis.setTimeout = ((handler: TimerHandler) => {
      timeoutHandler = handler;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout;
    globalThis.clearTimeout = (() => {
      clearedTimeout = true;
    }) as typeof clearTimeout;

    try {
      const request = apiJson("/timeout/body", { timeoutMs: 10 });
      await Promise.resolve();
      expect(clearedTimeout).toBe(false);
      if (typeof timeoutHandler === "function") timeoutHandler();
      bodyText.reject(new DOMException("Request timed out.", "AbortError"));
      await expect(request).rejects.toMatchObject({ name: "AbortError" });
      expect(clearedTimeout).toBe(true);
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    }
  });

  test("external abort wins over timeout while reading the response body", async () => {
    const originalFetch = globalThis.fetch;
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const externalController = new AbortController();
    const bodyText = createDeferred<string>();
    let timeoutHandler: TimerHandler | undefined;
    let requestSignal: AbortSignal | undefined;

    globalThis.fetch = (async (_input, init) => {
      requestSignal = init?.signal ?? undefined;
      requestSignal?.addEventListener("abort", () => {
        bodyText.reject(requestSignal?.reason);
      });
      return {
        headers: new Headers({ "content-type": "application/json" }),
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => await bodyText.promise,
      } as Response;
    }) as typeof fetch;
    globalThis.setTimeout = ((handler: TimerHandler) => {
      timeoutHandler = handler;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout;
    globalThis.clearTimeout = (() => {}) as typeof clearTimeout;

    try {
      const request = apiJson("/timeout/external-abort-body", {
        signal: externalController.signal,
        timeoutMs: 10,
      });
      await Promise.resolve();
      externalController.abort(new DOMException("user canceled", "AbortError"));
      await expect(request).rejects.toThrow("user canceled");
      if (typeof timeoutHandler === "function") timeoutHandler();
      expect(requestSignal?.reason).toMatchObject({ message: "user canceled" });
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    }
  });

  test("handles 204, text response, invalid JSON and non-2xx JSON detail", async () => {
    server.use(
      route(
        "GET /status204",
        () => new Response(null, { status: 204, statusText: "No Content" }),
      ),
      route(
        "GET /text-ok",
        () => new Response("plain-text", { status: 200, statusText: "OK" }),
      ),
      route(
        "GET /invalid-json",
        () =>
          new Response("{nope", {
            status: 200,
            statusText: "OK",
            headers: { "content-type": "application/json" },
          }),
      ),
      route("GET /error-json", () =>
        json(
          { detail: "bad request detail" },
          { status: 400, statusText: "Bad Request" },
        ),
      ),
    );

    const payload204 = await apiJson("/status204");
    const payloadText = await apiJson("/text-ok");
    await expect(apiJson("/invalid-json")).rejects.toThrow(
      /Invalid JSON response \(200 OK\)/,
    );
    await expect(apiJson("/error-json")).rejects.toThrow("bad request detail");
    expect(payload204).toBeUndefined();
    expect(payloadText).toBe("plain-text");
  });
});
