import { expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  launchChromiumBrowser,
  startPreviewServer,
} from "./playwright-preview-helpers.mjs";
import {
  wikiAnalysisSettings,
  wikiClientLocations,
  wikiCarsPayload,
  wikiHistoryInsightsByRunId,
  wikiHistoryRuns,
  wikiShellPayload,
  wikiSpeedSourceSettings,
  wikiSpeedSourceStatus,
} from "./wiki-screenshot-data.mjs";

const EXPECTED_SCHEMA_VERSION = "1";
const OUTPUT_DIR = process.argv[2] || "wiki-screenshots/images";
const SERVER_PORT = 4177;
const SERVER_TIMEOUT_MS = 25_000;
const PAGE_TIMEOUT_MS = 15_000;
const VIEWPORT = { width: 1280, height: 800 };

function screenshotPath(fileName) {
  mkdirSync(OUTPUT_DIR, { recursive: true });
  return join(OUTPUT_DIR, fileName);
}

function withCanonicalClientCadence(payload) {
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

async function installFakeWebSocket(page, payload) {
  await page.addInitScript(
    ({ wsPayload, schemaVersion }) => {
      const mergedPayload = wsPayload
        ? {
            schema_version: schemaVersion,
            server_time: new Date().toISOString(),
            speed_mps: null,
            clients: [],
            selected_client_id: null,
            rotational_speeds: null,
            ...wsPayload,
          }
        : null;

      class FakeWebSocket {
        static OPEN = 1;
        readyState = 1;
        onopen = null;
        onmessage = null;
        onclose = null;
        onerror = null;

        constructor() {
          queueMicrotask(() => this.onopen?.(new Event("open")));
          if (mergedPayload) {
            queueMicrotask(() => {
              this.onmessage?.(
                new MessageEvent("message", {
                  data: JSON.stringify(mergedPayload),
                }),
              );
            });
          }
        }

        send() {}

        close() {
          this.readyState = 3;
          this.onclose?.(new CloseEvent("close"));
        }
      }

      window.WebSocket = FakeWebSocket;
    },
    {
      wsPayload: payload ? withCanonicalClientCadence(payload) : undefined,
      schemaVersion: EXPECTED_SCHEMA_VERSION,
    },
  );
}

function jsonOk(body) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  };
}

function normalizePathname(pathname) {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

function requestPath(route) {
  return normalizePathname(new URL(route.request().url()).pathname);
}

async function fulfillJson(route, body) {
  await route.fulfill(jsonOk(body));
}

function defaultSettingsPayload(path) {
  if (path === "/api/settings/cars" || path === "/api/settings/cars/active") {
    return { cars: [], active_car_id: null };
  }
  return {};
}

function readinessCheck(checkKey, input) {
  return {
    check_key: checkKey,
    state: input.state,
    reason_key: input.reasonKey,
    details: input.details ?? {},
  };
}

function buildCaptureReadiness(input) {
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

function createSettingsHandlerFromMap(settingsMap) {
  return async (route) => {
    const path = requestPath(route);
    const method = route.request().method();
    const key = `${method} ${path}`;
    const value = settingsMap[key] ?? settingsMap[path];
    if (typeof value !== "undefined") {
      await fulfillJson(route, value);
      return;
    }
    await fulfillJson(route, defaultSettingsPayload(path));
  };
}

async function installCommonRoutes(page, options = {}) {
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

async function installWikiRoutes(page) {
  await installCommonRoutes(page, {
    locations: wikiClientLocations,
    settingsHandler: createSettingsHandlerFromMap({
      "GET /api/settings/analysis": wikiAnalysisSettings,
      "GET /api/settings/cars": wikiCarsPayload,
      "GET /api/settings/cars/active": wikiCarsPayload,
      "GET /api/settings/language": { language: "en" },
      "PUT /api/settings/language": { language: "en" },
      "GET /api/settings/speed-source": wikiSpeedSourceSettings,
      "GET /api/settings/speed-source/status": wikiSpeedSourceStatus,
      "GET /api/settings/speed-unit": { speed_unit: "kmh" },
    }),
    historyHandler: async (route) => {
      if (requestPath(route) === "/api/history") {
        await fulfillJson(route, { runs: wikiHistoryRuns });
        return;
      }
      await route.fallback();
    },
    espFlashHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/esp-flash/ports") {
        await fulfillJson(route, { ports: [] });
        return;
      }
      if (path === "/api/esp-flash/status") {
        await fulfillJson(route, {
          state: "idle",
          phase: "idle",
          job_id: null,
          selected_port: null,
          auto_detect: true,
          started_at: null,
          finished_at: null,
          last_success_at: null,
          exit_code: null,
          error: null,
          log_count: 0,
        });
        return;
      }
      if (path === "/api/esp-flash/history") {
        await fulfillJson(route, { attempts: [] });
        return;
      }
      if (path === "/api/esp-flash/logs") {
        await fulfillJson(route, { from_index: 0, next_index: 0, lines: [] });
        return;
      }
      await fulfillJson(route, {});
    },
  });

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
        isReady: true,
        sensors: {
          state: "pass",
          reasonKey: "ready",
          details: { connected: 5, assigned: 5 },
        },
        reference: { state: "pass", reasonKey: "ready" },
        speed: { state: "pass", reasonKey: "ready" },
        overall: { state: "pass", reasonKey: "capture_ready" },
      }),
    });
  });

  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, {
      state: "idle",
      phase: "idle",
      ssid: null,
      started_at: null,
      phase_started_at: null,
      phase_elapsed_s: null,
      finished_at: null,
      last_success_at: null,
      issues: [],
      log_tail: [],
      runtime: {
        version: "1.2.3",
        commit: "abcdef1234567890",
        static_assets_hash: "feedfacecafebeef",
        assets_verified: true,
      },
    });
  });

  await page.route("**/api/health", async (route) => {
    await fulfillJson(route, {
      status: "ok",
      processing_state: "idle",
      processing_failures: 0,
      degradation_reasons: [],
      data_loss: {
        affected_clients: 0,
        tracked_clients: 0,
        frames_dropped: 0,
        queue_overflow_drops: 0,
        server_queue_drops: 0,
        parse_errors: 0,
      },
      persistence: {
        analysis_in_progress: false,
        analysis_queue_depth: 0,
        write_error: null,
        analysis_active_run_id: null,
        analysis_started_at: null,
        analysis_elapsed_s: null,
      },
    });
  });

  await page.route("**/api/history/**/insights**", async (route) => {
    const match = /^\/api\/history\/([^/]+)\/insights$/.exec(
      requestPath(route),
    );
    if (!match) {
      await route.fallback();
      return;
    }
    const runId = decodeURIComponent(match[1] ?? "");
    const payload = wikiHistoryInsightsByRunId[runId];
    if (!payload) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "missing" }),
      });
      return;
    }
    await fulfillJson(route, payload);
  });
}

async function assertSpectrumHasData(page) {
  await expect
    .poll(
      async () =>
        page.evaluate(() => {
          const canvas = document.querySelector("#specChart canvas");
          if (!(canvas instanceof HTMLCanvasElement)) {
            return false;
          }
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            return false;
          }
          const width = canvas.width;
          const height = canvas.height;
          if (!width || !height) {
            return false;
          }
          const margin = Math.floor(Math.min(width, height) * 0.1);
          const imageData = ctx.getImageData(
            margin,
            margin,
            width - margin * 2,
            height - margin * 2,
          );
          const data = imageData.data;
          for (let index = 0; index < data.length; index += 4) {
            const r = data[index];
            const g = data[index + 1];
            const b = data[index + 2];
            const a = data[index + 3];
            if (a < 128) {
              continue;
            }
            if (r < 200 && (Math.abs(r - g) > 15 || Math.abs(g - b) > 15)) {
              return true;
            }
          }
          return false;
        }),
      {
        message: "Spectrum chart must contain visible graph data",
        timeout: 5_000,
      },
    )
    .toBe(true);
}

async function openSettingsTab(page, tabName) {
  await page.locator("#tab-settings").click();
  await page.locator(`[data-settings-tab="${tabName}"]`).click();
}

async function captureScenario(browser, label, fileName, capture) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    colorScheme: "light",
  });
  const page = await context.newPage();
  const filePath = screenshotPath(fileName);

  try {
    await installWikiRoutes(page);
    await installFakeWebSocket(page, wikiShellPayload);
    await page.goto(`http://localhost:${SERVER_PORT}/`, {
      timeout: PAGE_TIMEOUT_MS,
    });
    await capture(page);
    await page.screenshot({
      fullPage: true,
      path: filePath,
      animations: "disabled",
    });
    console.log(`Captured ${label}: ${filePath}`);
  } finally {
    await context.close();
  }
}

const CAPTURES = [
  {
    label: "live dashboard",
    fileName: "live-dashboard.png",
    capture: async (page) => {
      await expect(
        page.locator("#liveConnectedSensors [data-value]"),
      ).toHaveText("5 / 5");
      await expect(page.locator("#liveActiveCar [data-value]")).toHaveText(
        "BMW 330d Touring",
      );
      await expect(page.locator(".site-header__status")).toBeHidden();
      await expect(page.locator("#liveRunHealth")).toBeHidden();
      await expect(page.locator("#loggingStatus")).toBeHidden();
      await expect(page.locator("#liveSensorRoster .status-pill")).toHaveCount(
        0,
      );
      await expect(
        page.locator(
          '#liveSensorRoster .live-sensor-card__status-dot[data-status="online"]',
        ),
      ).toHaveCount(5);
      await expect(page.locator("#liveSensorRoster article")).toHaveCount(5);
      await assertSpectrumHasData(page);
    },
  },
  {
    label: "history overview",
    fileName: "history-overview.png",
    capture: async (page) => {
      await page.locator("#tab-history").click();
      await expect(
        page.locator('#historyTableBody tr[data-run-row="1"]'),
      ).toHaveCount(3);
      await expect(
        page.locator(
          '[data-run-row="1"][data-run="run-bmw-front-right-balance"]',
        ),
      ).toContainText("Front-right wheel imbalance");
      await expect(
        page.locator(
          '[data-run-row="1"][data-run="run-volvo-driveshaft-rumble"]',
        ),
      ).toContainText("Driveshaft rumble");
      await expect(
        page.locator('[data-run-row="1"][data-run="run-mx5-engine-order"]'),
      ).toContainText("Engine harmonic resonance");
    },
  },
  {
    label: "settings cars",
    fileName: "settings-cars.png",
    capture: async (page) => {
      await openSettingsTab(page, "carTab");
      await expect(page.locator("#carListBody tr")).toHaveCount(3);
      await expect(
        page.locator(
          '#carListBody tr[data-car-id="car-bmw-330d"] .car-active-pill',
        ),
      ).toContainText("Active");
    },
  },
  {
    label: "settings analysis",
    fileName: "settings-analysis.png",
    capture: async (page) => {
      await openSettingsTab(page, "analysisTab");
      await expect(page.locator("#wheelBandwidthInput")).toHaveValue("5");
      await expect(page.locator("#analysisGuidanceHelp")).toContainText(
        "Safe starting point",
      );
    },
  },
  {
    label: "settings speed source",
    fileName: "settings-speed-source.png",
    capture: async (page) => {
      await openSettingsTab(page, "speedSourceTab");
      await expect(page.locator("#speedSourceCurrentSource")).toHaveText("GPS");
      await expect(page.locator("#gpsStatusRawSpeed")).toContainText(
        "74.0 km/h",
      );
      await expect(page.locator("#gpsStatusEffectiveSpeed")).toContainText(
        "72.0 km/h",
      );
    },
  },
];

async function main() {
  const cwd = fileURLToPath(new URL(".", import.meta.url));
  let server;
  let browser;

  try {
    server = await startPreviewServer(cwd, {
      port: SERVER_PORT,
      timeoutMs: SERVER_TIMEOUT_MS,
    });
    browser = await launchChromiumBrowser();

    for (const entry of CAPTURES) {
      await captureScenario(
        browser,
        entry.label,
        entry.fileName,
        entry.capture,
      );
    }
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
    if (server) {
      server.kill();
    }
  }
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error("Wiki screenshot update failed:", message);
  process.exit(1);
});
