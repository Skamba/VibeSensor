import { expect, test, type Route } from "@playwright/test";

import { createDeferred } from "./deferred_test_helpers";
import {
  bootLiveDashboard,
  confirmPrompt,
  fulfillJson,
  gpsStatus,
  installSettingsRoutes,
  obdStatus,
  openSensorsTab,
  openSettingsTab,
  openSpeedSourceTab,
  speedSourceSettings,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

test("gps status uses selected speed unit in settings panel", async ({
  page,
}) => {
  await installSettingsRoutes(page, {
    "/api/settings/speed-unit": { speed_unit: "mps" },
    "/api/settings/speed-source/status": gpsStatus({
      last_update_age_s: 0.333,
      raw_speed_kmh: 36,
    }),
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openSpeedSourceTab(page);
  await expect(page.locator("#speedUnitSelect")).toHaveValue("mps");
  await expect(page.locator("#gpsStatusState")).toHaveText("Connected");
  await expect(page.locator("#gpsStatusRawSpeed")).toHaveText("10.0 m/s");
  await expect(page.locator("#gpsStatusEffectiveSpeed")).toHaveText("5.0 m/s");
});

test("gps status polling does not override websocket speed readout", async ({
  page,
}) => {
  let gpsStatusCalls = 0;
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source/status": async () => {
      gpsStatusCalls += 1;
      return gpsStatus({});
    },
  });
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: { speedMps: 20 },
  });
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
  await expect
    .poll(() => gpsStatusCalls, { timeout: 5_000 })
    .toBeGreaterThanOrEqual(2);
  await openSpeedSourceTab(page);
  await expect(page.locator("#gpsStatusRawSpeed")).toHaveText("18.0 km/h");
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
});

test("spectrum title updates when switching language", async ({ page }) => {
  let languagePutCalls = 0;
  let lastLanguagePayload: Record<string, unknown> | null = null;
  await installSettingsRoutes(page, {
    "GET /api/settings/language": { language: "en" },
    "PUT /api/settings/language": async (route: Route) => {
      languagePutCalls += 1;
      lastLanguagePayload = route.request().postDataJSON() as Record<
        string,
        unknown
      >;
      return { language: "nl" };
    },
    "/api/settings/speed-source/status": gpsStatus({
      raw_speed_kmh: 72,
      effective_speed_kmh: 72,
    }),
  });
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: {
      speedMps: 20,
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
    },
  });
  const spectrumTitle = page.locator("#spectrumPanelRoot .card__title");
  await expect(spectrumTitle).toHaveText("Multi-Sensor Blended Spectrum");
  await expect(page.locator("#languageSelect")).toHaveValue("en");
  await page.locator("#languageSelect").selectOption("nl");
  await expect(spectrumTitle).toHaveText(
    "Gecombineerd spectrum van meerdere sensoren",
  );
  await expect.poll(() => languagePutCalls).toBe(1);
  expect(lastLanguagePayload).toEqual({ language: "nl" });
  await expect(page.locator("#languageSelect")).toHaveValue("nl");
});

test("manual speed save uses settings endpoint only (no speed-override call)", async ({
  page,
}) => {
  let speedSourcePutCalls = 0;
  let speedOverrideCalls = 0;
  let lastSpeedSourcePayload: Record<string, unknown> | null = null;
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source": speedSourceSettings(),
    "PUT /api/settings/speed-source": async (route: Route) => {
      speedSourcePutCalls += 1;
      lastSpeedSourcePayload = route.request().postDataJSON() as Record<
        string,
        unknown
      >;
      return lastSpeedSourcePayload;
    },
  });
  await page.route("**/api/speed-override", async (route) => {
    speedOverrideCalls += 1;
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "missing" }),
    });
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openSpeedSourceTab(page);
  await expect(page.locator("#speedSourceCurrentSource")).toHaveText("GPS");
  await expect(page.locator("#gpsFallbackPanel")).toBeVisible();
  await expect(page.locator("#manualSpeedConfig")).toBeHidden();
  await page.locator('[data-speed-source-choice="manual"]').click();
  await expect(page.locator("#manualSpeedConfig")).toBeVisible();
  await expect(page.locator("#gpsFallbackPanel")).toBeHidden();
  await page.locator("#manualSpeedInput").fill("45");
  await page.locator("#saveSpeedSourceBtn").click();
  await expect.poll(() => speedSourcePutCalls).toBe(1);
  await expect.poll(() => speedOverrideCalls).toBe(0);
  expect(lastSpeedSourcePayload).toEqual({
    manual_speed_kph: 45,
    speed_source: "manual",
    stale_timeout_s: 5,
  });
  await expect(page.locator("#speedSourceSaveFeedback")).toBeHidden();
});

test("resolved fallback manual state stays coherent across header status, form, and GPS status", async ({
  page,
}) => {
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source": speedSourceSettings({
      speed_source: "gps",
      manual_speed_kph: 80,
    }),
    "GET /api/settings/speed-source/status": gpsStatus({
      gps_enabled: false,
      connection_state: "disabled",
      raw_speed_kmh: null,
      effective_speed_kmh: 80,
      fallback_active: true,
      speed_source: "fallback_manual",
    }),
  });
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: { speedMps: 80 / 3.6 },
  });
  await expect(page.locator("#speed")).toContainText("80.0 km/h");
  await expect(page.locator("#speed")).toContainText("Manual");
  await expect(page.locator(".site-header__status")).toBeHidden();

  await openSettingsTab(page);
  await expect(page.locator(".site-header__status")).toBeVisible();
  await expect(page.locator("#linkState")).toHaveText("Connected");
  await expect(page.locator("#shellLiveStatus")).toHaveText("No live signal");
  await openSpeedSourceTab(page);
  await expect(page.locator("#speedSourceCurrentSource")).toHaveText(
    "Manual fallback",
  );
  await expect(page.locator("#speedSourceEffectiveSpeed")).toHaveText(
    "80.0 km/h",
  );
  await expect(page.locator("#speedSourceFallbackActive")).toHaveText("Yes");
  await expect(page.locator("#speedSourceCurrentSource")).toHaveClass(
    /speed-source-summary__value/,
  );
  await expect(page.locator("#manualSpeedConfig")).toBeVisible();
  await expect(page.locator("#gpsFallbackPanel")).toBeHidden();
  const diagnostics = page.locator("#speedSourceDiagnostics");
  await expect(
    diagnostics.locator(".settings-help-disclosure__body"),
  ).toBeVisible();
  await expect(page.locator("#gpsStatusState")).toHaveText("Disabled");
  await expect(page.locator("#gpsStatusEffectiveSpeed")).toHaveText(
    "80.0 km/h",
  );
  await expect(page.locator("#gpsStatusFallback")).toHaveText("Yes");
  await expect(
    page.locator('input[name="speedSourceRadio"][value="manual"]'),
  ).toBeChecked();
  await expect(
    page.locator('input[name="speedSourceRadio"][value="gps"]'),
  ).not.toBeChecked();
  await expect(page.locator("#manualSpeedInput")).toHaveValue("80");
  await expect(page.locator("#manualSpeedInput")).toHaveAttribute("min", "0");
});

test("resolved OBD2 state stays coherent across header status, form, and device summary", async ({
  page,
}) => {
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source": speedSourceSettings({
      speed_source: "obd2",
      obd_device_mac: "0022d9001bb1",
      obd_device_name: "OBDLink CX",
    }),
    "GET /api/settings/speed-source/status": gpsStatus({
      gps_enabled: false,
      connection_state: "connected",
      device: null,
      raw_speed_kmh: null,
      effective_speed_kmh: 81,
      fallback_active: false,
      speed_source: "obd2",
    }),
    "GET /api/settings/obd/status": obdStatus({
      configured_device_mac: "0022d9001bb1",
      configured_device_name: "OBDLink CX",
      paired: true,
      trusted: true,
      connected: true,
      rfcomm_channel: 1,
      last_rpm: 2200,
      rpm_sample_age_s: 0.1,
      rpm_target_interval_ms: 75,
      rpm_effective_hz: 13.3,
      request_rtt_ms: 61.4,
      timeout_count: 1,
      error_count: 2,
      poll_mode: "rpm_only_backoff",
      backoff_active: true,
      last_raw_response: "41 0C 1B 58",
    }),
  });
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: { speedMps: 81 / 3.6 },
  });
  await expect(page.locator("#speed")).toContainText("81.0 km/h");
  await expect(page.locator("#speed")).toContainText("OBD2");

  await openSpeedSourceTab(page);
  await expect(page.locator("#speedSourceCurrentSource")).toHaveText("OBD2");
  await expect(page.locator("#speedSourceEffectiveSpeed")).toHaveText(
    "81.0 km/h",
  );
  await expect(
    page.locator('input[name="speedSourceRadio"][value="obd2"]'),
  ).toBeChecked();
  await expect(
    page.locator('input[name="speedSourceRadio"][value="gps"]'),
  ).not.toBeChecked();
  await expect(page.locator("#obdConfiguredDevice")).toHaveText(
    "OBDLink CX (0022d9001bb1)",
  );
  await expect(page.locator("#obdStatusTargetCadence")).toHaveText(
    "13.3 Hz (75 ms)",
  );
  await expect(page.locator("#obdStatusEffectiveCadence")).toHaveText(
    "13.3 Hz",
  );
  await expect(page.locator("#obdStatusRequestRtt")).toHaveText("61 ms");
  await expect(page.locator("#obdStatusTimeouts")).toHaveText("1");
  await expect(page.locator("#obdStatusErrors")).toHaveText("2");
  await expect(page.locator("#obdStatusMode")).toHaveText(
    "RPM priority only (backed off)",
  );
  await expect(page.locator("#obdStatusBackoff")).toHaveText("Yes");
  await expect(page.locator("#obdSpeedConfig")).toBeVisible();
  await expect(page.locator("#gpsFallbackPanel")).toBeHidden();
});

test("assigning a sensor location preserves the original sensor name", async ({
  page,
}) => {
  let locationUpdateCalls = 0;

  await installSettingsRoutes(
    page,
    {},
    { locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }] },
  );
  await page.route("**/api/clients/**/location", async (route) => {
    locationUpdateCalls += 1;
    await fulfillJson(route, {});
  });
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: {
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
    },
  });
  await openSensorsTab(page);

  const row = page.locator(
    '#sensorsSettingsBody tr[data-client-id="sensor-1"]',
  );
  const locationSelect = row.locator("select.row-location-select");

  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");
  await expect(row.locator(".settings-sensor-row__meta code")).toHaveText(
    "sensor-1",
  );
  await expect(
    row.locator(".settings-sensor-row__actions .row-identify"),
  ).toBeVisible();
  await locationSelect.selectOption("front_left_wheel");
  await expect.poll(() => locationUpdateCalls).toBe(1);
  await expect(locationSelect).toHaveValue("front_left_wheel");
  await expect(locationSelect).toHaveAttribute("data-client-id", "sensor-1");
  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");
  await expect(row.locator(".settings-sensor-row__meta code")).toHaveText(
    "sensor-1",
  );
});

test("sensor identify and remove actions stay wired through the Sensors panel", async ({
  page,
}) => {
  let identifyCalls = 0;
  let removeCalls = 0;
  let identifyPath: string | null = null;
  let removePath: string | null = null;

  await installSettingsRoutes(
    page,
    {},
    { locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }] },
  );
  await page.route("**/api/clients/**/identify", async (route) => {
    identifyCalls += 1;
    identifyPath = new URL(route.request().url()).pathname;
    await fulfillJson(route, {});
  });
  await page.route("**/api/clients/sensor-1", async (route) => {
    if (route.request().method() !== "DELETE") {
      await route.fallback();
      return;
    }
    removeCalls += 1;
    removePath = new URL(route.request().url()).pathname;
    await fulfillJson(route, {});
  });
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: {
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
    },
  });
  await openSensorsTab(page);

  const row = page.locator(
    '#sensorsSettingsBody tr[data-client-id="sensor-1"]',
  );

  await row.locator(".row-identify").click();
  await expect.poll(() => identifyCalls).toBe(1);
  expect(identifyPath).toBe("/api/clients/sensor-1/identify");

  await row.locator(".row-remove").click();
  await confirmPrompt(page);
  await expect.poll(() => removeCalls).toBe(1);
  expect(removePath).toBe("/api/clients/sensor-1");
  await expect(
    page.locator('#sensorsSettingsBody tr[data-client-id="sensor-1"]'),
  ).toHaveCount(0);
});

test("settings keep inferred sensor names unassigned until an explicit location is saved", async ({
  page,
}) => {
  await installSettingsRoutes(
    page,
    {},
    { locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }] },
  );
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: {
      clients: [
        {
          id: "sensor-1",
          name: "Front Left Wheel",
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
    },
  });
  await openSensorsTab(page);

  const row = page.locator(
    '#sensorsSettingsBody tr[data-client-id="sensor-1"]',
  );
  const locationSelect = row.locator("select.row-location-select");

  await expect(locationSelect).toHaveValue("");
  await expect(row.locator("strong")).toHaveText("Front Left Wheel");
  await expect(row.locator(".settings-sensor-row__meta code")).toHaveText(
    "sensor-1",
  );
});

test("manual OBD scan sorts named devices first and background rescans progressively improve the list", async ({
  page,
}) => {
  let scanCalls = 0;
  const refreshedScanPayload = {
    devices: [
      {
        mac_address: "5340ac571177",
        name: "Pim's iPhone",
        paired: false,
        trusted: false,
        connected: false,
        rfcomm_channel: null,
      },
    ],
  };
  const refreshedScan = createDeferred<typeof refreshedScanPayload>();
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source": speedSourceSettings({
      speed_source: "obd2",
      obd_device_mac: null,
      obd_device_name: null,
    }),
    "GET /api/settings/speed-source/status": gpsStatus({
      speed_source: "obd2",
      connection_state: "disconnected",
    }),
    "GET /api/settings/obd/status": obdStatus(),
    "POST /api/settings/obd/scan": async () => {
      scanCalls += 1;
      if (scanCalls === 1) {
        return {
          devices: [
            {
              mac_address: "5340ac571177",
              name: "53-40-AC-57-11-77",
              paired: false,
              trusted: false,
              connected: false,
              rfcomm_channel: null,
            },
            {
              mac_address: "0022d9001bb1",
              name: "Audioengine HD6",
              paired: false,
              trusted: false,
              connected: false,
              rfcomm_channel: null,
            },
          ],
        };
      }
      return await refreshedScan.promise;
    },
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openSpeedSourceTab(page);
  await page.locator("#scanObdDevicesBtn").click();

  const deviceNames = page.locator(".speed-source-device__name");
  await expect(deviceNames.nth(0)).toHaveText("Audioengine HD6");
  await expect(deviceNames.nth(1)).toHaveText("53-40-AC-57-11-77");
  await expect(page.locator(".speed-source-device__mac").nth(0)).toHaveText(
    "0022d9001bb1",
  );
  await expect(
    page.locator(".speed-source-device__actions .btn").nth(0),
  ).toHaveText("Pair and use");
  await expect(page.locator(".speed-source-device__badge")).toHaveCount(0);

  await expect
    .poll(() => scanCalls, { timeout: 5_000 })
    .toBeGreaterThanOrEqual(2);
  await expect(deviceNames.nth(1)).toHaveText("53-40-AC-57-11-77");

  refreshedScan.resolve(refreshedScanPayload);
  await expect(deviceNames.nth(1)).toHaveText("Pim's iPhone");
  await expect(page.locator(".speed-source-device__mac").nth(1)).toHaveText(
    "5340ac571177",
  );
});

test("background OBD rescans stop when the Speed Source OBD panel is no longer visible", async ({
  page,
}) => {
  let scanCalls = 0;
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source": speedSourceSettings({
      speed_source: "obd2",
      obd_device_mac: null,
      obd_device_name: null,
    }),
    "GET /api/settings/speed-source/status": gpsStatus({
      speed_source: "obd2",
      connection_state: "disconnected",
    }),
    "GET /api/settings/obd/status": obdStatus(),
    "POST /api/settings/obd/scan": async () => {
      scanCalls += 1;
      return {
        devices: [
          {
            mac_address: "0022d9001bb1",
            name: "OBDLink CX",
            paired: false,
            trusted: false,
            connected: false,
            rfcomm_channel: null,
          },
        ],
      };
    },
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openSpeedSourceTab(page);
  await page.locator("#scanObdDevicesBtn").click();

  await expect
    .poll(() => scanCalls, { timeout: 5_000 })
    .toBeGreaterThanOrEqual(2);
  await page.locator('[data-speed-source-choice="gps"]').click();

  const stoppedAt = scanCalls;
  await expect(
    page.locator('input[name="speedSourceRadio"][value="gps"]'),
  ).toBeChecked();
  await expect(page.locator("#obdSpeedConfig")).toBeHidden();
  await expect(page.locator("#gpsFallbackPanel")).toBeVisible();
  expect(scanCalls).toBe(stoppedAt);
});
