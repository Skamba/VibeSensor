import type { Page, Route } from "@playwright/test";
import type { LoggingStatusPayload } from "../src/api/types";
import { EXPECTED_SCHEMA_VERSION } from "../src/contracts/ws_payload_types";

export type FakeWebSocketOptions = {
  payload?: Record<string, unknown>;
  repeatPayloadCount?: number;
  repeatPayloadIntervalMs?: number;
  trackerKey?: string;
};

export type LiveSensorPayloadOptions = Omit<FakeWebSocketOptions, "payload"> & {
  clients?: Array<Record<string, unknown>>;
  extraPayload?: Record<string, unknown>;
  speedMps?: number | null;
};

function withCanonicalClientCadence(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const rawClients = payload.clients;
  if (!Array.isArray(rawClients)) {
    return payload;
  }
  return {
    ...payload,
    clients: rawClients.map((client) => {
      if (
        typeof client !== "object" ||
        client === null ||
        Array.isArray(client)
      ) {
        return client;
      }
      if ("frame_samples" in client) {
        return client;
      }
      return {
        frame_samples: 200,
        ...client,
      };
    }),
  };
}

export async function installFakeWebSocket(
  page: Page,
  options: FakeWebSocketOptions = {},
): Promise<void> {
  await page.addInitScript(
    ({
      payload,
      schemaVersion,
      repeatPayloadCount,
      repeatPayloadIntervalMs,
      trackerKey,
    }) => {
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
      const globalState = window as Window &
        typeof globalThis &
        Record<string, unknown>;
      const tracker = trackerKey
        ? {
            deliveredCount: 0,
            repeatTimerActive: false,
          }
        : null;
      if (trackerKey && tracker) {
        globalState[trackerKey] = tracker;
      }
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
            const emitPayload = () => {
              if (tracker) {
                tracker.deliveredCount += 1;
              }
              this.onmessage?.(
                new MessageEvent("message", {
                  data: JSON.stringify(mergedPayload),
                }),
              );
            };
            queueMicrotask(emitPayload);
            if ((repeatPayloadCount ?? 0) > 0) {
              if (tracker) {
                tracker.repeatTimerActive = true;
              }
              let remainingRepeats = repeatPayloadCount ?? 0;
              this.repeatTimer = window.setInterval(() => {
                if (this.readyState !== FakeWebSocket.OPEN) {
                  window.clearInterval(this.repeatTimer);
                  this.repeatTimer = 0;
                  if (tracker) {
                    tracker.repeatTimerActive = false;
                  }
                  return;
                }
                emitPayload();
                remainingRepeats -= 1;
                if (remainingRepeats <= 0) {
                  window.clearInterval(this.repeatTimer);
                  this.repeatTimer = 0;
                  if (tracker) {
                    tracker.repeatTimerActive = false;
                  }
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
            if (tracker) {
              tracker.repeatTimerActive = false;
            }
          }
          this.readyState = 3;
          this.onclose?.(new CloseEvent("close"));
        }
      }
      window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    },
    {
      ...options,
      payload: options.payload
        ? withCanonicalClientCadence(options.payload)
        : undefined,
      schemaVersion: EXPECTED_SCHEMA_VERSION,
    },
  );
}

async function installLiveSensorPayload(
  page: Page,
  options: LiveSensorPayloadOptions = {},
): Promise<void> {
  const {
    clients = [],
    extraPayload = {},
    speedMps = null,
    ...webSocketOptions
  } = options;
  await installFakeWebSocket(page, {
    ...webSocketOptions,
    payload: {
      server_time: new Date().toISOString(),
      speed_mps: speedMps,
      clients,
      spectra: { clients: {} },
      ...extraPayload,
    },
  });
}

export type CommonRouteOptions = {
  runs?: Array<Record<string, unknown>>;
  locations?: Array<Record<string, unknown>>;
  historyHandler?: (route: Route) => Promise<void>;
  settingsHandler?: (route: Route) => Promise<void>;
  espFlashHandler?: (route: Route) => Promise<void>;
};

export type BootLiveDashboardOptions = CommonRouteOptions & {
  fakeWebSocket?: FakeWebSocketOptions;
  installRoutes?: boolean;
  liveSensorPayload?: LiveSensorPayloadOptions;
};

function jsonOk(body: unknown) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  };
}

function normalizePathname(pathname: string): string {
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

type CaptureReadinessState = "pass" | "warn" | "fail";

type CaptureReadinessCheckInput = {
  state: CaptureReadinessState;
  reasonKey: string;
  details?: Record<string, string | number>;
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
): NonNullable<LoggingStatusPayload["capture_readiness"]>["checks"][number] {
  return {
    check_key: checkKey,
    state: input.state,
    reason_key: input.reasonKey,
    details: input.details ?? {},
  };
}

export function buildCaptureReadiness(
  input: CaptureReadinessInput,
): NonNullable<LoggingStatusPayload["capture_readiness"]> {
  const overall =
    input.overall ??
    (input.isReady
      ? { state: "pass", reasonKey: "capture_ready", details: {} }
      : {
          state: "fail",
          reasonKey: "capture_blocked",
          details: { blocking_check: "reference_ready" },
        });
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

export async function installCommonRoutes(
  page: Page,
  options: CommonRouteOptions = {},
): Promise<void> {
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

export async function bootLiveDashboard(
  page: Page,
  options: BootLiveDashboardOptions = {},
): Promise<void> {
  const {
    fakeWebSocket,
    installRoutes = true,
    liveSensorPayload,
    ...routeOptions
  } = options;
  if (installRoutes) {
    await installCommonRoutes(page, routeOptions);
  }
  if (liveSensorPayload) {
    await installLiveSensorPayload(page, liveSensorPayload);
  } else {
    await installFakeWebSocket(page, fakeWebSocket);
  }
  await page.goto("/");
}

async function openSettingsTab(
  page: Page,
  settingsTabId?: string,
): Promise<void> {
  await page.locator("#tab-settings").click();
  if (settingsTabId) {
    await page.locator(`[data-settings-tab="${settingsTabId}"]`).click();
  }
}

export async function openCarsTab(page: Page): Promise<void> {
  await openSettingsTab(page, "carTab");
}

export async function openAnalysisTab(page: Page): Promise<void> {
  await openSettingsTab(page, "analysisTab");
}

export async function openInternetTab(page: Page): Promise<void> {
  await openSettingsTab(page, "internetTab");
}

export async function openUpdateTab(page: Page): Promise<void> {
  await openSettingsTab(page, "updateTab");
}

export async function openSensorsTab(page: Page): Promise<void> {
  await openSettingsTab(page, "sensorsTab");
}

export async function openSpeedSourceTab(page: Page): Promise<void> {
  await openSettingsTab(page, "speedSourceTab");
}

export async function openEspFlashTab(page: Page): Promise<void> {
  await openSettingsTab(page, "espFlashTab");
}

export async function openHistoryTab(page: Page): Promise<void> {
  await page.locator("#tab-history").click();
}
