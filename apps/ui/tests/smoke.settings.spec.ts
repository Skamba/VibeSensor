import { expect, test } from "@playwright/test";

import { createSettingsHandlerFromMap, fulfillJson, gpsStatus, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("gps status uses selected speed unit in settings panel", async ({ page }) => {
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "/api/settings/language": { language: "en" }, "/api/settings/speed-unit": { speedUnit: "mps" }, "/api/settings/speed-source/status": gpsStatus({ last_update_age_s: 0.333, raw_speed_kmh: 36 }) }) });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();
  await expect(page.locator("#gpsStatusRawSpeed")).toHaveText("10.0 m/s");
  await expect(page.locator("#gpsStatusEffectiveSpeed")).toHaveText("5.0 m/s");
});

test("gps status polling does not override websocket speed readout", async ({ page }) => {
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "/api/settings/language": { language: "en" }, "/api/settings/speed-unit": { speedUnit: "kmh" }, "/api/settings/speed-source/status": gpsStatus({}) }) });
  await installFakeWebSocket(page, { payload: { server_time: new Date().toISOString(), speed_mps: 20, clients: [], spectra: { clients: {} } } });
  await page.goto("/");
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
  await page.waitForTimeout(500);
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
});

test("spectrum title updates when switching language", async ({ page }) => {
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "GET /api/settings/language": { language: "en" }, "POST /api/settings/language": { language: "nl" }, "/api/settings/speed-unit": { speedUnit: "kmh" }, "/api/settings/speed-source/status": gpsStatus({ raw_speed_kmh: 72, effective_speed_kmh: 72 }) }) });
  await installFakeWebSocket(page, { payload: { server_time: new Date().toISOString(), speed_mps: 20, clients: [{ id: "c1", name: "Front Left", connected: true, frames_total: 100, dropped_frames: 0 }], spectra: { clients: {} } } });
  await page.goto("/");
  await expect(page.locator("#dashboardView [data-i18n='chart.spectrum_title']")).toHaveText("Multi-Sensor Blended Spectrum");
  await page.locator("#languageSelect").selectOption("nl");
  await expect(page.locator("#dashboardView [data-i18n='chart.spectrum_title']")).toHaveText("Gecombineerd spectrum van meerdere sensoren");
});

test("manual speed save uses settings endpoint only (no speed-override call)", async ({ page }) => {
  let speedSourcePostCalls = 0;
  let speedOverrideCalls = 0;
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "GET /api/settings/speed-source": { speedSource: "gps", manualSpeedKph: null, staleTimeoutS: 5, fallbackMode: "hold" }, "POST /api/settings/speed-source": async (route) => { speedSourcePostCalls += 1; return route.request().postDataJSON(); } }) });
  await page.route("**/api/speed-override", async (route) => {
    speedOverrideCalls += 1;
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "missing" }) });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();
  await page.locator('input[name="speedSourceRadio"][value="manual"]').check();
  await page.locator("#manualSpeedInput").fill("45");
  await page.locator("#saveSpeedSourceBtn").click();
  await expect.poll(() => speedSourcePostCalls).toBe(1);
  await expect.poll(() => speedOverrideCalls).toBe(0);
});

test("analysis bandwidth and uncertainty settings persist through API round-trip", async ({ page }) => {
  let persistedAnalysisSettings: Record<string, number> = {};
  let analysisPostCalls = 0;
  await installCommonRoutes(page, { settingsHandler: async (route) => { if (requestPath(route).startsWith("/api/settings/cars")) { await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], activeCarId: "car-1" }); return; } await fulfillJson(route, {}); } });
  await page.route("**/api/analysis-settings", async (route) => {
    const method = route.request().method();
    if (method === "POST") {
      analysisPostCalls += 1;
      persistedAnalysisSettings = route.request().postDataJSON() as Record<string, number>;
      await fulfillJson(route, persistedAnalysisSettings);
      return;
    }
    await fulfillJson(route, persistedAnalysisSettings);
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();
  await page.locator("#wheelBandwidthInput").fill("7.5");
  await page.locator("#driveshaftBandwidthInput").fill("8.5");
  await page.locator("#engineBandwidthInput").fill("9.5");
  await page.locator("#speedUncertaintyInput").fill("3");
  await page.locator("#tireDiameterUncertaintyInput").fill("4");
  await page.locator("#finalDriveUncertaintyInput").fill("2");
  await page.locator("#gearUncertaintyInput").fill("5");
  await page.locator("#minAbsBandHzInput").fill("0.7");
  await page.locator("#maxBandHalfWidthInput").fill("12");
  await page.locator("#saveAnalysisBtn").click();
  await expect.poll(() => analysisPostCalls).toBe(1);
  await page.reload();
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
});
