import { type Page, type Route } from "@playwright/test";

export type FakeWebSocketOptions = {
  payload?: Record<string, unknown>;
  confirmResult?: boolean;
};

export async function installFakeWebSocket(page: Page, options: FakeWebSocketOptions = {}): Promise<void> {
  await page.addInitScript(({ payload, confirmResult }) => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor() {
        queueMicrotask(() => this.onopen?.(new Event("open")));
        if (payload) {
          queueMicrotask(() =>
            this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) })),
          );
        }
      }
      send() {}
      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
    }
    window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    if (typeof confirmResult === "boolean") {
      window.confirm = () => confirmResult;
    }
  }, options);
}

export type CommonRouteOptions = {
  runs?: Array<Record<string, unknown>>;
  locations?: Array<Record<string, unknown>>;
  historyHandler?: (route: Route) => Promise<void>;
  settingsHandler?: (route: Route) => Promise<void>;
  espFlashHandler?: (route: Route) => Promise<void>;
};

export type SettingsRouteValue = unknown | ((route: Route, path: string, method: string) => Promise<unknown | void>);

function jsonOk(body: unknown) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

export function normalizePathname(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

export function requestPath(route: Route): string {
  return normalizePathname(new URL(route.request().url()).pathname);
}

export async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill(jsonOk(body));
}

export async function installCommonRoutes(page: Page, options: CommonRouteOptions = {}): Promise<void> {
  await page.route("**/api/logging/status", async (route) => {
    await fulfillJson(route, { enabled: false, current_file: null });
  });
  await page.route("**/api/history**", async (route) => {
    if (!requestPath(route).startsWith("/api/history")) {
      await route.fallback();
      return;
    }
    if (options.historyHandler) {
      await options.historyHandler(route);
      return;
    }
    await fulfillJson(route, { runs: options.runs ?? [] });
  });
  await page.route("**/api/client-locations", async (route) => {
    await fulfillJson(route, { locations: options.locations ?? [] });
  });
  await page.route("**/api/car-library/**", async (route) => {
    await fulfillJson(route, { brands: [], types: [], models: [] });
  });
  await page.route("**/api/settings/**", async (route) => {
    if (!requestPath(route).startsWith("/api/settings")) {
      await route.fallback();
      return;
    }
    if (options.settingsHandler) {
      await options.settingsHandler(route);
      return;
    }
    await fulfillJson(route, {});
  });
  await page.route("**/api/esp-flash/**", async (route) => {
    if (!requestPath(route).startsWith("/api/esp-flash")) {
      await route.fallback();
      return;
    }
    if (options.espFlashHandler) {
      await options.espFlashHandler(route);
      return;
    }
    await fulfillJson(route, {});
  });
}

export function createSettingsHandlerFromMap(settingsMap: Record<string, SettingsRouteValue>) {
  return async (route: Route): Promise<void> => {
    const path = requestPath(route);
    const method = route.request().method();
    const key = `${method} ${path}`;
    const value = settingsMap[key] ?? settingsMap[path];
    if (typeof value === "function") {
      const result = await value(route, path, method);
      if (typeof result !== "undefined") {
        await fulfillJson(route, result);
      }
      return;
    }
    if (typeof value !== "undefined") {
      await fulfillJson(route, value);
      return;
    }
    await fulfillJson(route, {});
  };
}

export function gpsStatus(overrides: Partial<Record<string, unknown>>) {
  return {
    gps_enabled: true,
    connection_state: "connected",
    device: "gps0",
    last_update_age_s: 0.1,
    raw_speed_kmh: 18,
    effective_speed_kmh: 18,
    last_error: null,
    reconnect_delay_s: 1,
    fallback_active: false,
    stale_timeout_s: 5,
    fallback_mode: "hold",
    ...overrides,
  };
}