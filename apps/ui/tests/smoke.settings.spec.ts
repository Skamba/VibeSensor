import { expect, test } from "@playwright/test";

import { createSettingsHandlerFromMap, fulfillJson, gpsStatus, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("gps status uses selected speed unit in settings panel", async ({ page }) => {
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "/api/settings/language": { language: "en" }, "/api/settings/speed-unit": { speed_unit: "mps" }, "/api/settings/speed-source/status": gpsStatus({ last_update_age_s: 0.333, raw_speed_kmh: 36 }) }) });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();
  await expect(page.locator("#gpsStatusRawSpeed")).toHaveText("10.0 m/s");
  await expect(page.locator("#gpsStatusEffectiveSpeed")).toHaveText("5.0 m/s");
});

test("gps status polling does not override websocket speed readout", async ({ page }) => {
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "/api/settings/language": { language: "en" }, "/api/settings/speed-unit": { speed_unit: "kmh" }, "/api/settings/speed-source/status": gpsStatus({}) }) });
  await installFakeWebSocket(page, { payload: { server_time: new Date().toISOString(), speed_mps: 20, clients: [], spectra: { clients: {} } } });
  await page.goto("/");
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
  await page.waitForTimeout(500);
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
});

test("spectrum title updates when switching language", async ({ page }) => {
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "GET /api/settings/language": { language: "en" }, "PUT /api/settings/language": { language: "nl" }, "/api/settings/speed-unit": { speed_unit: "kmh" }, "/api/settings/speed-source/status": gpsStatus({ raw_speed_kmh: 72, effective_speed_kmh: 72 }) }) });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      speed_mps: 20,
      clients: [
        {
          id: "c1",
          name: "Front Left",
          connected: true,
          frames_total: 100,
          dropped_frames: 0,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          location_code: "",
          mac_address: "c1",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });
  await page.goto("/");
  await expect(page.locator("#dashboardView [data-i18n='chart.spectrum_title']")).toHaveText("Multi-Sensor Blended Spectrum");
  await page.locator("#languageSelect").selectOption("nl");
  await expect(page.locator("#dashboardView [data-i18n='chart.spectrum_title']")).toHaveText("Gecombineerd spectrum van meerdere sensoren");
});

test("manual speed save uses settings endpoint only (no speed-override call)", async ({ page }) => {
  let speedSourcePutCalls = 0;
  let speedOverrideCalls = 0;
  await installCommonRoutes(page, { settingsHandler: createSettingsHandlerFromMap({ "GET /api/settings/speed-source": { speed_source: "gps", manual_speed_kph: null, stale_timeout_s: 5 }, "PUT /api/settings/speed-source": async (route) => { speedSourcePutCalls += 1; return route.request().postDataJSON(); } }) });
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
  await expect.poll(() => speedSourcePutCalls).toBe(1);
  await expect.poll(() => speedOverrideCalls).toBe(0);
});

test("resolved fallback manual state stays coherent across header status, form, and GPS status", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: createSettingsHandlerFromMap({
      "GET /api/settings/speed-source": {
        speed_source: "gps",
        manual_speed_kph: 80,
        stale_timeout_s: 5,
      },
      "GET /api/settings/speed-source/status": gpsStatus({
        gps_enabled: false,
        connection_state: "disabled",
        raw_speed_kmh: null,
        effective_speed_kmh: 80,
        fallback_active: true,
        speed_source: "fallback_manual",
      }),
    }),
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      speed_mps: 80 / 3.6,
      clients: [],
      spectra: { clients: {} },
    },
  });
  await page.goto("/");
  await expect(page.locator("#speed")).toContainText("80.0 km/h");
  await expect(page.locator("#speed")).toContainText("Manual");
  await expect(page.locator("#linkState")).toHaveText("Connected");
  await expect(page.locator("#shellLiveStatus")).toHaveText("No live signal");

  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();
  await expect(page.locator("#gpsStatusState")).toHaveText("Disabled");
  await expect(page.locator("#gpsStatusEffectiveSpeed")).toHaveText("80.0 km/h");
  await expect(page.locator("#gpsStatusFallback")).toHaveText("Yes");
  await expect(page.locator('input[name="speedSourceRadio"][value="manual"]')).toBeChecked();
  await expect(page.locator('input[name="speedSourceRadio"][value="gps"]')).not.toBeChecked();
  await expect(page.locator("#manualSpeedInput")).toHaveValue("80");
});

test("analysis bandwidth and uncertainty settings persist through API round-trip", async ({ page }) => {
  let persistedAnalysisSettings: Record<string, number> = {};
  let analysisPutCalls = 0;
  await installCommonRoutes(page, { settingsHandler: async (route) => { if (requestPath(route).startsWith("/api/settings/cars")) { await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], active_car_id: "car-1" }); return; } await fulfillJson(route, {}); } });
  await page.route("**/api/settings/analysis", async (route) => {
    const method = route.request().method();
    if (method === "PUT") {
      analysisPutCalls += 1;
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
  await expect.poll(() => analysisPutCalls).toBe(1);
  await page.reload();
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
});

test("assigning a sensor location preserves the original sensor name", async ({ page }) => {
  let locationUpdateCalls = 0;

  await installCommonRoutes(page, {
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
  });
  await page.route("**/api/clients/**/location", async (route) => {
    locationUpdateCalls += 1;
    await fulfillJson(route, {});
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "sensor-1",
          name: "Chassis Sensor A",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "",
          mac_address: "sensor-1",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="sensorsTab"]').click();

  const row = page.locator('#sensorsSettingsBody tr[data-client-id="sensor-1"]');
  const locationSelect = row.locator("select.row-location-select");

  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");
  await locationSelect.selectOption("front_left_wheel");
  await expect.poll(() => locationUpdateCalls).toBe(1);
  await expect(locationSelect).toHaveValue("front_left_wheel");
  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");
});

test("failed speed-source save reverts the UI and shows an error", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: createSettingsHandlerFromMap({
      "GET /api/settings/language": { language: "en" },
      "GET /api/settings/speed-unit": { speed_unit: "kmh" },
      "GET /api/settings/speed-source": { speed_source: "gps", manual_speed_kph: null, stale_timeout_s: 5 },
      "PUT /api/settings/speed-source": async (route) => {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Speed source save failed" }),
        });
      },
    }),
  });
  await installFakeWebSocket(page);

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();
  await page.locator('input[name="speedSourceRadio"][value="manual"]').check();
  await page.locator("#manualSpeedInput").fill("45");
  await page.locator("#saveSpeedSourceBtn").click();

  await expect(page.locator("#appErrorBanner")).toBeVisible();
  await expect(page.locator("#appErrorBanner")).toContainText("Speed source save failed");
  await expect(page.locator('input[name="speedSourceRadio"][value="gps"]')).toBeChecked();
  await expect(page.locator('input[name="speedSourceRadio"][value="manual"]')).not.toBeChecked();
  await expect(page.locator("#manualSpeedInput")).toHaveValue("");
});

test("failed language save reverts the selector and shows an error", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: createSettingsHandlerFromMap({
      "GET /api/settings/language": { language: "en" },
      "PUT /api/settings/language": async (route) => {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Language save failed" }),
        });
      },
      "GET /api/settings/speed-unit": { speed_unit: "kmh" },
    }),
  });
  await installFakeWebSocket(page);

  await page.goto("/");
  await page.locator("#languageSelect").selectOption("nl");

  await expect(page.locator("#appErrorBanner")).toBeVisible();
  await expect(page.locator("#appErrorBanner")).toContainText("Language save failed");
  await expect(page.locator("#languageSelect")).toHaveValue("en");
  await expect(page.locator("#tab-settings")).toContainText("Settings");
});
