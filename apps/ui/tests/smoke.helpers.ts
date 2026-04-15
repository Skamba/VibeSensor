import type { Locator, Page, Route } from "@playwright/test";
import { EXPECTED_SCHEMA_VERSION } from "../src/contracts/ws_payload_types";

export type FakeWebSocketOptions = {
  payload?: Record<string, unknown>;
  confirmResult?: boolean;
  repeatPayloadCount?: number;
  repeatPayloadIntervalMs?: number;
};

export async function installFakeWebSocket(page: Page, options: FakeWebSocketOptions = {}): Promise<void> {
  await page.addInitScript(({ payload, confirmResult, schemaVersion, repeatPayloadCount, repeatPayloadIntervalMs }) => {
    const mergedPayload = payload
      ? {
          schema_version: schemaVersion,
          server_time: new Date().toISOString(),
          speed_mps: null,
          clients: [],
          selected_client_id: null,
          rotational_speeds: null,
          ...payload,
        }
      : null;
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      repeatTimer = 0;
      constructor() {
        queueMicrotask(() => this.onopen?.(new Event("open")));
        if (mergedPayload) {
          const emitPayload = () =>
            this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(mergedPayload) }));
          queueMicrotask(emitPayload);
          if ((repeatPayloadCount ?? 0) > 0) {
            let remainingRepeats = repeatPayloadCount ?? 0;
            this.repeatTimer = window.setInterval(() => {
              if (this.readyState !== FakeWebSocket.OPEN) {
                window.clearInterval(this.repeatTimer);
                this.repeatTimer = 0;
                return;
              }
              emitPayload();
              remainingRepeats -= 1;
              if (remainingRepeats <= 0) {
                window.clearInterval(this.repeatTimer);
                this.repeatTimer = 0;
              }
            }, repeatPayloadIntervalMs ?? 50);
          }
        }
      }
      send() {}
      close() {
        if (this.repeatTimer) {
          window.clearInterval(this.repeatTimer);
          this.repeatTimer = 0;
        }
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
    }
    window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    if (typeof confirmResult === "boolean") {
      window.confirm = () => confirmResult;
    }
  }, { ...options, schemaVersion: EXPECTED_SCHEMA_VERSION });
}

export type CommonRouteOptions = {
  runs?: Array<Record<string, unknown>>;
  locations?: Array<Record<string, unknown>>;
  historyHandler?: (route: Route) => Promise<void>;
  settingsHandler?: (route: Route) => Promise<void>;
  espFlashHandler?: (route: Route) => Promise<void>;
};

export type SettingsRouteValue = unknown | ((route: Route, path: string, method: string) => Promise<unknown | undefined>);

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

function defaultSettingsPayload(path: string): Record<string, unknown> {
  if (path === "/api/settings/cars" || path === "/api/settings/cars/active") {
    return { cars: [], active_car_id: null };
  }
  return {};
}

export type SemanticSurfaceStyles = {
  backgroundColor: string;
  borderColor: string;
  expectedBackgroundColor: string;
  expectedBorderColor: string;
};

export type SemanticToneStyles = {
  backgroundColor: string;
  borderColor: string;
  color: string;
  expectedBackgroundColor: string;
  expectedBorderColor: string;
  expectedColor: string;
};

export async function readSemanticToneStyles(
  locator: Locator,
  vars: {
    surfaceVar: string;
    borderVar?: string;
    textVar?: string;
  },
): Promise<SemanticToneStyles> {
  return locator.evaluate(
    (element, vars) => {
      const probe = document.createElement("div");
      probe.style.background = `var(${vars.surfaceVar})`;
      probe.style.border = vars.borderVar
        ? `1px solid var(${vars.borderVar})`
        : "1px solid transparent";
      probe.style.color = vars.textVar ? `var(${vars.textVar})` : "inherit";
      probe.style.position = "absolute";
      probe.style.visibility = "hidden";
      probe.style.pointerEvents = "none";
      document.body.appendChild(probe);
      const elementStyles = getComputedStyle(element);
      const probeStyles = getComputedStyle(probe);
      const result = {
        backgroundColor: elementStyles.backgroundColor,
        borderColor: elementStyles.borderTopColor,
        color: elementStyles.color,
        expectedBackgroundColor: probeStyles.backgroundColor,
        expectedBorderColor: probeStyles.borderTopColor,
        expectedColor: probeStyles.color,
      };
      probe.remove();
      return result;
    },
    vars,
  );
}

export async function readSemanticSurfaceStyles(
  locator: Locator,
  surfaceVar: string,
  borderVar: string,
): Promise<SemanticSurfaceStyles> {
  const styles = await readSemanticToneStyles(locator, { surfaceVar, borderVar });
  return {
    backgroundColor: styles.backgroundColor,
    borderColor: styles.borderColor,
    expectedBackgroundColor: styles.expectedBackgroundColor,
    expectedBorderColor: styles.expectedBorderColor,
  };
}

export async function activateWizardCloseButton(page: Page): Promise<void> {
  await page.locator("#wizardCloseBtn").evaluate((button) => {
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("wizardCloseBtn must be a button");
    }
    button.click();
  });
}

type CaptureReadinessState = "pass" | "warn" | "fail";

type CaptureReadinessCheckInput = {
  state: CaptureReadinessState;
  reasonKey: string;
  details?: Record<string, unknown>;
};

type CaptureReadinessInput = {
  isReady: boolean;
  sensors: CaptureReadinessCheckInput;
  reference: CaptureReadinessCheckInput;
  speed: CaptureReadinessCheckInput;
  overall?: CaptureReadinessCheckInput;
};

function readinessCheck(
  checkKey: string,
  input: CaptureReadinessCheckInput,
): Record<string, unknown> {
  return {
    check_key: checkKey,
    state: input.state,
    reason_key: input.reasonKey,
    details: input.details ?? {},
  };
}

export function buildCaptureReadiness(input: CaptureReadinessInput): Record<string, unknown> {
  const overall = input.overall ?? (
    input.isReady
      ? { state: "pass", reasonKey: "capture_ready", details: {} }
      : {
        state: "fail",
        reasonKey: "capture_blocked",
        details: { blocking_check: "reference_ready" },
      }
  );
  return {
    is_ready: input.isReady,
    checks: [
      readinessCheck("sensors_ready", input.sensors),
      readinessCheck("reference_ready", input.reference),
      readinessCheck("speed_stable", input.speed),
      readinessCheck("capture_ready", overall),
    ],
  };
}

export async function installCommonRoutes(page: Page, options: CommonRouteOptions = {}): Promise<void> {
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: buildCaptureReadiness({
        isReady: false,
        sensors: { state: "fail", reasonKey: "no_live_sensors" },
        reference: { state: "fail", reasonKey: "active_car_missing" },
        speed: { state: "fail", reasonKey: "speed_sample_missing" },
        overall: {
          state: "fail",
          reasonKey: "capture_blocked",
          details: { blocking_check: "sensors_ready" },
        },
      }),
    });
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
    const path = requestPath(route);
    if (!path.startsWith("/api/settings")) {
      await route.fallback();
      return;
    }
    if (options.settingsHandler) {
      await options.settingsHandler(route);
      return;
    }
    await fulfillJson(route, defaultSettingsPayload(path));
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
  await page.route("**/api/update/internet-status", async (route) => {
    await fulfillJson(route, {
      detected: false,
      usable: false,
      interface_name: null,
      connection_name: null,
      driver: null,
      ipv4_addresses: [],
      gateway: null,
      has_default_route: false,
      diagnostic: "No USB network interface is currently detected.",
    });
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
    await fulfillJson(route, defaultSettingsPayload(path));
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
    speed_source: "gps",
    stale_timeout_s: 5,

    ...overrides,
  };
}
