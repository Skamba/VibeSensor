import { expect, test } from "@playwright/test";

import {
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 12_000 });

const analysisSettingsPayload = {
  wheel_bandwidth_pct: 5,
  driveshaft_bandwidth_pct: 5,
  engine_bandwidth_pct: 5,
  min_abs_band_hz: 0.5,
  max_band_half_width_pct: 6,
  speed_uncertainty_pct: 3,
  tire_diameter_uncertainty_pct: 4,
  final_drive_uncertainty_pct: 1,
  gear_uncertainty_pct: 2,
};

const readyStrengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [],
};

test("settings desktop journey keeps analysis controls and car actions reachable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const readyAspects = {
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 19,
    final_drive_ratio: 3.3,
    current_gear_ratio: 0.84,
  };
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Active Car",
              type: "sedan",
              aspects: readyAspects,
            },
            {
              id: "car-2",
              name: "Inactive Car",
              type: "suv",
              aspects: readyAspects,
            },
          ],
          active_car_id: "car-1",
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/settings/analysis", async (route) => {
    await fulfillJson(route, analysisSettingsPayload);
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();

  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(
    page.locator('label[for="speedUncertaintyInput"]'),
  ).toBeVisible();
  await expect(
    page.locator('label[for="tireDiameterUncertaintyInput"]'),
  ).toBeVisible();
  await expect(
    page.locator('label[for="finalDriveUncertaintyInput"]'),
  ).toBeVisible();
  await expect(page.locator("#saveAnalysisBtn")).toBeVisible();

  await page.locator('[data-settings-tab="carTab"]').click();

  const activeRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  const inactiveRow = page.locator('#carListBody tr[data-car-id="car-2"]');
  const activeDeleteButton = activeRow.locator(".car-delete-btn");
  const inactiveDeleteButton = inactiveRow.locator(".car-delete-btn");

  await expect(activeDeleteButton).toBeVisible();
  await expect(inactiveDeleteButton).toBeVisible();
  await expect(activeRow.locator(".car-activate-btn")).toHaveCount(0);
  await expect(inactiveRow.locator(".car-activate-btn")).toHaveCount(1);

  await expect(activeRow).toContainText("Active");
  await expect(inactiveRow.locator(".car-activate-btn")).toBeEnabled();
});

test("dashboard desktop journey keeps summary stats and sensor cards readable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installCommonRoutes(page, {
    locations: [
      { code: "front_left_wheel", label: "Front Left Wheel" },
      { code: "engine_bay", label: "Engine Bay" },
    ],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Test Hatch",
              type: "Simulated setup",
              aspects: {},
            },
          ],
          active_car_id: "car-1",
        });
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
          reasonKey: "sensors_ready",
          details: { live_sensor_count: 1 },
        },
        reference: { state: "pass", reasonKey: "reference_ready" },
        speed: {
          state: "pass",
          reasonKey: "speed_stable",
          details: { dwell_elapsed_s: 8 },
        },
      }),
    });
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "sensor-alpha",
          name: "Alpha Probe",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
        {
          id: "sensor-bay",
          name: "Bay Module",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "engine_bay",
          mac_address: "66778899aabb",
          firmware_version: "fw-1.0.0",
        },
        {
          id: "sensor-gamma",
          name: "Gamma Probe",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "",
          mac_address: "ccddeeff0011",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {
          "sensor-alpha": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.1, 0.2, 0.15],
            strength_metrics: readyStrengthMetrics,
          },
        },
      },
    },
  });
  await page.goto("/");

  const strongestSignalStat = page.locator("#liveStrongestSignal");
  const dataFreshnessValue = page.locator("#liveDataFreshness [data-value]");
  const strongestSignalValue = strongestSignalStat.locator("[data-value]");
  const speedValue = page.locator("#speed");

  await expect(strongestSignalStat).not.toHaveClass(/stat--spotlight/);
  await expect(strongestSignalStat.locator(".stat__label")).toHaveText(
    "Strongest signal",
  );
  await expect(dataFreshnessValue).toBeVisible();
  await expect(strongestSignalValue).toBeVisible();
  await expect(speedValue).toBeVisible();

  await expect(page.locator(".site-header__status")).toBeHidden();
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#liveSensorRoster .status-pill")).toHaveCount(0);
  await expect(
    page.locator(
      '#liveSensorRoster .live-sensor-card__status-dot[data-status="online"]',
    ),
  ).toHaveCount(3);

  const frontCard = page.locator("#liveSensorRoster article").nth(0);
  const engineCard = page.locator("#liveSensorRoster article").nth(1);
  const unassignedCard = page.locator("#liveSensorRoster article").nth(2);
  await expect(frontCard).toHaveText("Front Left Wheel");
  await expect(engineCard).toHaveText("Engine Bay");
  await expect(unassignedCard).toHaveText("Gamma Probe");

  await page.locator("#tab-history").click();
  await expect(page.locator(".site-header__status")).toBeVisible();

  await page.locator("#tab-dashboard").click();
  await expect(page.locator(".site-header__status")).toBeHidden();
});
