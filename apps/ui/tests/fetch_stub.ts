import { afterEach, beforeEach } from "vitest";

type Handler = (request: Request) => Response | Promise<Response>;

const ORIGIN = "http://vibesensor.test";

/** A route for `stubFetch().use(...)`, keyed like "GET /api/health". */
export function route(key: string, handler: Handler): [string, Handler] {
  return [key, handler];
}

export function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Answers the UI's fetch calls from per-test routes. A request without a route
 * fails loudly, and like a real fetch the call rejects once its signal aborts.
 */
export function stubFetch(): { use(...routes: [string, Handler][]): void } {
  const routes = new Map<string, Handler>();
  let original: typeof fetch;
  beforeEach(() => {
    original = globalThis.fetch;
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(
        input instanceof Request ? input.url : String(input),
        ORIGIN,
      );
      const request = new Request(url, init);
      const key = `${request.method} ${url.pathname}`;
      const handler = routes.get(key);
      if (!handler) {
        return Promise.reject(new Error(`Unhandled request: ${key}`));
      }
      return new Promise<Response>((resolve, reject) => {
        const signal = init?.signal;
        const abort = () =>
          reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
        if (signal?.aborted) {
          abort();
          return;
        }
        signal?.addEventListener("abort", abort, { once: true });
        Promise.resolve(handler(request)).then(resolve, reject);
      });
    }) as typeof fetch;
  });
  afterEach(() => {
    globalThis.fetch = original;
    routes.clear();
  });
  return {
    use(...entries) {
      for (const [key, handler] of entries) {
        routes.set(key, handler);
      }
    },
  };
}
