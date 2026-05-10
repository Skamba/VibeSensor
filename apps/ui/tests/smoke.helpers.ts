import { expect, type Locator, type Page, type Route } from "@playwright/test";
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

export async function waitForFakeWebSocketSettled(
  page: Page,
  trackerKey: string,
  minimumDeliveredCount: number,
): Promise<void> {
  await expect
    .poll(async () => {
      const tracker = await page.evaluate((key) => {
        const tracker = (
          window as Window & typeof globalThis & Record<string, unknown>
        )[key];
        if (
          typeof tracker !== "object" ||
          tracker === null ||
          !("deliveredCount" in tracker) ||
          !("repeatTimerActive" in tracker) ||
          typeof tracker.deliveredCount !== "number" ||
          typeof tracker.repeatTimerActive !== "boolean"
        ) {
          throw new Error(`Missing fake WebSocket tracker: ${key}`);
        }
        return {
          deliveredCount: tracker.deliveredCount,
          repeatTimerActive: tracker.repeatTimerActive,
        };
      }, trackerKey);
      return (
        tracker.repeatTimerActive === false &&
        tracker.deliveredCount >= minimumDeliveredCount
      );
    })
    .toBe(true);
}

export async function confirmPrompt(page: Page): Promise<void> {
  const dialog = page.locator(".confirmation-dialog");
  await expect(dialog).toBeVisible();
  const confirmButton = dialog.locator(".btn--danger");
  await expect(confirmButton).toBeFocused();
  await confirmButton.click();
  await expect(dialog).toHaveCount(0);
}

export async function cancelPrompt(page: Page): Promise<void> {
  const dialog = page.locator(".confirmation-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(".btn--danger")).toBeFocused();
  await dialog.locator("button:not(.btn--danger)").click();
  await expect(dialog).toHaveCount(0);
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

export type SettingsRouteValue =
  | unknown
  | ((
      route: Route,
      path: string,
      method: string,
    ) => Promise<unknown | undefined>);

function jsonOk(body: unknown) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  };
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
  return locator.evaluate((element, vars) => {
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
  }, vars);
}

export async function readSemanticSurfaceStyles(
  locator: Locator,
  surfaceVar: string,
  borderVar: string,
): Promise<SemanticSurfaceStyles> {
  const styles = await readSemanticToneStyles(locator, {
    surfaceVar,
    borderVar,
  });
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

export async function openSettingsTab(
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

export async function openSpeedSourceTab(page: Page): Promise<void> {
  await openSettingsTab(page, "speedSourceTab");
}

export async function openAnalysisTab(page: Page): Promise<void> {
  await openSettingsTab(page, "analysisTab");
}

export async function openSensorsTab(page: Page): Promise<void> {
  await openSettingsTab(page, "sensorsTab");
}

export async function openInternetTab(page: Page): Promise<void> {
  await openSettingsTab(page, "internetTab");
}

export async function openUpdateTab(page: Page): Promise<void> {
  await openSettingsTab(page, "updateTab");
}

export async function openHistoryTab(page: Page): Promise<void> {
  await page.locator("#tab-history").click();
}

export function createSettingsHandlerFromMap(
  settingsMap: Record<string, SettingsRouteValue>,
) {
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
