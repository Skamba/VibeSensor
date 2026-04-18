import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import {
  buildCaptureReadiness,
  createSettingsHandlerFromMap,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
} from "./smoke.helpers";
import {
  wikiAnalysisSettings,
  wikiClientLocations,
  wikiCarsPayload,
  wikiHistoryInsightsByRunId,
  wikiHistoryRuns,
  wikiShellPayload,
  wikiSpeedSourceSettings,
  wikiSpeedSourceStatus,
} from "./wiki_screenshot_data";

const SCREENSHOT_DIR = process.env.WIKI_SCREENSHOT_DIR ?? join(process.cwd(), "wiki-screenshots");

function screenshotPath(fileName: string): string {
  mkdirSync(SCREENSHOT_DIR, { recursive: true });
  return join(SCREENSHOT_DIR, fileName);
}

async function assertSpectrumHasData(page: Page): Promise<void> {
  await expect.poll(async () => page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>("#specChart canvas");
    if (!canvas) return false;
    const ctx = canvas.getContext("2d");
    if (!ctx) return false;
    const width = canvas.width;
    const height = canvas.height;
    if (!width || !height) return false;
    const margin = Math.floor(Math.min(width, height) * 0.1);
    const imageData = ctx.getImageData(margin, margin, width - margin * 2, height - margin * 2);
    const data = imageData.data;
    for (let index = 0; index < data.length; index += 4) {
      const r = data[index];
      const g = data[index + 1];
      const b = data[index + 2];
      const a = data[index + 3];
      if (a < 128) continue;
      if (r < 200 && (Math.abs(r - g) > 15 || Math.abs(g - b) > 15)) {
        return true;
      }
    }
    return false;
  }), {
    message: "Spectrum chart must contain visible graph data",
    timeout: 5_000,
  }).toBe(true);
}

async function installWikiRoutes(page: Page): Promise<void> {
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
      const pathname = requestPath(route);
      if (pathname === "/api/history") {
        await fulfillJson(route, { runs: wikiHistoryRuns });
        return;
      }
      await route.fallback();
    },
    espFlashHandler: async (route) => {
      const pathname = requestPath(route);
      if (pathname === "/api/esp-flash/ports") {
        await fulfillJson(route, { ports: [] });
        return;
      }
      if (pathname === "/api/esp-flash/status") {
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
      if (pathname === "/api/esp-flash/history") {
        await fulfillJson(route, { attempts: [] });
        return;
      }
      if (pathname === "/api/esp-flash/logs") {
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
        sensors: { state: "pass", reasonKey: "ready", details: { connected: 5, assigned: 5 } },
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
    const match = /^\/api\/history\/([^/]+)\/insights$/.exec(requestPath(route));
    if (!match) {
      await route.fallback();
      return;
    }
    const runId = decodeURIComponent(match[1] ?? "");
    const payload = wikiHistoryInsightsByRunId[runId];
    if (!payload) {
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "missing" }) });
      return;
    }
    await fulfillJson(route, payload);
  });
}

async function openSettingsTab(page: Page, tabName: string): Promise<void> {
  await page.locator("#tab-settings").click();
  await page.locator(`[data-settings-tab="${tabName}"]`).click();
}

test.describe("wiki screenshots", () => {
  test("captures live dashboard with real graph data", async ({ page }) => {
    await installWikiRoutes(page);
    await installFakeWebSocket(page, { payload: wikiShellPayload });
    await page.goto("/");
    await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText("5 / 5");
    await expect(page.locator("#liveActiveCar [data-value]")).toHaveText("BMW 330d Touring");
    await expect(page.locator(".site-header__status")).toBeHidden();
    await expect(page.locator("#liveRunHealth")).toBeHidden();
    await expect(page.locator("#loggingStatus")).toBeHidden();
    await expect(page.locator("#liveSensorRoster .status-pill")).toHaveCount(0);
    await expect(page.locator("#liveSensorRoster .live-sensor-card__status-dot--online")).toHaveCount(5);
    await expect(page.locator("#liveSensorRoster article")).toHaveCount(5);
    await assertSpectrumHasData(page);
    await page.screenshot({ fullPage: true, path: screenshotPath("live-dashboard.png") });
  });

  test("captures history view with multiple analyzed runs", async ({ page }) => {
    await installWikiRoutes(page);
    await installFakeWebSocket(page, { payload: wikiShellPayload });
    await page.goto("/");
    await page.locator("#tab-history").click();
    await expect(page.locator('#historyTableBody tr[data-run-row="1"]')).toHaveCount(3);
    await expect(page.locator('[data-run-row="1"][data-run="run-bmw-front-right-balance"]')).toContainText("Front-right wheel imbalance");
    await expect(page.locator('[data-run-row="1"][data-run="run-volvo-driveshaft-rumble"]')).toContainText("Driveshaft rumble");
    await expect(page.locator('[data-run-row="1"][data-run="run-mx5-engine-order"]')).toContainText("Engine harmonic resonance");
    await page.screenshot({ fullPage: true, path: screenshotPath("history-overview.png") });
  });

  test("captures cars tab with multiple configured vehicles", async ({ page }) => {
    await installWikiRoutes(page);
    await installFakeWebSocket(page, { payload: wikiShellPayload });
    await page.goto("/");
    await openSettingsTab(page, "carTab");
    await expect(page.locator("#carListBody tr")).toHaveCount(3);
    await expect(page.locator('#carListBody tr[data-car-id="car-bmw-330d"] .car-active-pill')).toContainText("Active");
    await page.screenshot({ fullPage: true, path: screenshotPath("settings-cars.png") });
  });

  test("captures analysis settings with an active car", async ({ page }) => {
    await installWikiRoutes(page);
    await installFakeWebSocket(page, { payload: wikiShellPayload });
    await page.goto("/");
    await openSettingsTab(page, "analysisTab");
    await expect(page.locator("#wheelBandwidthInput")).toHaveValue("5");
    await expect(page.locator("#analysisGuidanceHelp")).toContainText("Safe starting point");
    await page.screenshot({ fullPage: true, path: screenshotPath("settings-analysis.png") });
  });

  test("captures speed source configuration with live GPS status", async ({ page }) => {
    await installWikiRoutes(page);
    await installFakeWebSocket(page, { payload: wikiShellPayload });
    await page.goto("/");
    await openSettingsTab(page, "speedSourceTab");
    await expect(page.locator("#speedSourceCurrentSource")).toHaveText("GPS");
    await expect(page.locator("#gpsStatusRawSpeed")).toContainText("74.0 km/h");
    await expect(page.locator("#gpsStatusEffectiveSpeed")).toContainText("72.0 km/h");
    await page.screenshot({ fullPage: true, path: screenshotPath("settings-speed-source.png") });
  });
});
