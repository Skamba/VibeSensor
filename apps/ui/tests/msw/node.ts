import type { test as playwrightTest } from "@playwright/test";
import { setupServer } from "msw/node";

import { UI_MSW_ORIGIN } from "./http";

type PlaywrightTestHooks = Pick<
  typeof playwrightTest,
  "afterAll" | "afterEach" | "beforeAll"
>;

function installUiMswInterception(server: ReturnType<typeof setupServer>): () => void {
  const originalFetch = globalThis.fetch;
  if (!originalFetch) {
    throw new Error("MSW test server requires global fetch");
  }
  server.listen({
    onUnhandledRequest({ method, url }) {
      throw new Error(`Unhandled MSW request: ${method} ${url}`);
    },
  });
  const interceptedFetch = globalThis.fetch;
  if (!interceptedFetch) {
    throw new Error("MSW test server failed to install fetch interception");
  }
  globalThis.fetch = ((input: URL | RequestInfo, init?: RequestInit) =>
    interceptedFetch(resolveFetchInput(input), init)) as typeof fetch;
  return () => {
    server.close();
    globalThis.fetch = originalFetch;
  };
}

function resolveFetchInput(input: URL | RequestInfo): URL | Request {
  if (typeof input === "string") {
    return new URL(input, UI_MSW_ORIGIN);
  }
  if (input instanceof URL) {
    return new URL(input.toString(), UI_MSW_ORIGIN);
  }
  return new Request(new URL(input.url, UI_MSW_ORIGIN), input);
}

export function createUiMswTestServer(testHooks: PlaywrightTestHooks) {
  const server = setupServer();
  let restoreInterception = () => undefined;

  // Use this shared lifecycle only for tests that cross the real HTTP/fetch
  // boundary. Transport-injected or pure view/state tests should stay below it.
  testHooks.beforeAll(() => {
    restoreInterception = installUiMswInterception(server);
  });

  testHooks.afterEach(() => {
    server.resetHandlers();
  });

  testHooks.afterAll(() => {
    restoreInterception();
  });

  return server;
}

export function createUiMswTestScope() {
  const server = setupServer();
  const restoreInterception = installUiMswInterception(server);

  return {
    server,
    close(): void {
      server.resetHandlers();
      restoreInterception();
    },
  };
}
