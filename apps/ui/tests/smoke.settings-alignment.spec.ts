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

test("settings desktop journey keeps analysis controls and car actions aligned", async ({ page }) => {
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
            { id: "car-1", name: "Active Car", type: "sedan", aspects: readyAspects },
            { id: "car-2", name: "Inactive Car", type: "suv", aspects: readyAspects },
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
  const speedLabel = page.locator('label[for="speedUncertaintyInput"]');
  const tireLabel = page.locator('label[for="tireDiameterUncertaintyInput"]');
  const finalDriveLabel = page.locator('label[for="finalDriveUncertaintyInput"]');
  await expect(speedLabel).toBeVisible();
  await expect(tireLabel).toBeVisible();
  await expect(finalDriveLabel).toBeVisible();

  const [speedLabelBox, tireLabelBox, speedTop, tireTop, finalDriveTop] = await Promise.all([
    speedLabel.boundingBox(),
    tireLabel.boundingBox(),
    page.locator("#speedUncertaintyInput").evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    page.locator("#tireDiameterUncertaintyInput").evaluate((el) =>
      Math.round(el.getBoundingClientRect().top),
    ),
    page.locator("#finalDriveUncertaintyInput").evaluate((el) =>
      Math.round(el.getBoundingClientRect().top),
    ),
  ]);

  if (!speedLabelBox || !tireLabelBox) {
    throw new Error("Expected uncertainty labels to have layout boxes");
  }

  expect(tireLabelBox.height).toBeGreaterThan(speedLabelBox.height);
  expect(Math.abs(speedTop - tireTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(finalDriveTop - tireTop)).toBeLessThanOrEqual(1);

  await page.locator('[data-settings-tab="carTab"]').click();

  const activeRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  const inactiveRow = page.locator('#carListBody tr[data-car-id="car-2"]');
  const activeDeleteButton = activeRow.locator(".car-delete-btn");
  const inactiveDeleteButton = inactiveRow.locator(".car-delete-btn");

  await expect(activeDeleteButton).toBeVisible();
  await expect(inactiveDeleteButton).toBeVisible();
  await expect(activeRow.locator(".car-activate-btn")).toHaveCount(0);
  await expect(inactiveRow.locator(".car-activate-btn")).toHaveCount(1);

  const [activeDeleteRight, inactiveDeleteRight] = await Promise.all([
    activeDeleteButton.evaluate((el) => {
      const { right } = el.getBoundingClientRect();
      return Math.round(right);
    }),
    inactiveDeleteButton.evaluate((el) => {
      const { right } = el.getBoundingClientRect();
      return Math.round(right);
    }),
  ]);

  expect(Math.abs(activeDeleteRight - inactiveDeleteRight)).toBeLessThanOrEqual(1);
});

test("dashboard desktop journey keeps summary stats and sensor cards readable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installCommonRoutes(page, {
    locations: [
      { code: "front_left_wheel", label: "Front Left Wheel" },
      { code: "engine_bay", label: "Engine Bay" },
    ],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "Test Hatch", type: "Simulated setup", aspects: {} }],
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
        sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
        reference: { state: "pass", reasonKey: "reference_ready" },
        speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
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

  const dataFreshnessStat = page.locator("#liveDataFreshness");
  const strongestSignalStat = page.locator("#liveStrongestSignal");
  const dataFreshnessLabel = dataFreshnessStat.locator(".stat__label");
  const strongestSignalLabel = strongestSignalStat.locator(".stat__label");
  const dataFreshnessValue = dataFreshnessStat.locator("[data-value]");
  const strongestSignalValue = strongestSignalStat.locator("[data-value]");
  const speedValue = page.locator("#speed");

  await expect(strongestSignalStat).not.toHaveClass(/stat--spotlight/);
  await expect(strongestSignalLabel).toHaveText("Strongest signal");
  await expect(dataFreshnessValue).toBeVisible();
  await expect(strongestSignalValue).toBeVisible();
  await expect(speedValue).toBeVisible();

  const [
    dataFreshnessLabelTop,
    strongestSignalLabelTop,
    speedLabelTop,
    dataFreshnessValueTop,
    strongestSignalValueTop,
    speedValueTop,
  ] = await Promise.all([
    dataFreshnessLabel.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    strongestSignalLabel.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    speedValue.evaluate((el) =>
      Math.round((el.previousElementSibling as HTMLElement).getBoundingClientRect().top),
    ),
    dataFreshnessValue.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    strongestSignalValue.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    speedValue.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
  ]);

  expect(Math.abs(dataFreshnessLabelTop - strongestSignalLabelTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(speedLabelTop - strongestSignalLabelTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(dataFreshnessValueTop - strongestSignalValueTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(speedValueTop - strongestSignalValueTop)).toBeLessThanOrEqual(1);

  await expect(page.locator(".site-header__status")).toBeHidden();
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#liveSensorRoster .status-pill")).toHaveCount(0);
  await expect(page.locator('#liveSensorRoster .live-sensor-card__status-dot[data-status="online"]')).toHaveCount(3);

  const frontCard = page.locator("#liveSensorRoster article").nth(0);
  const engineCard = page.locator("#liveSensorRoster article").nth(1);
  const unassignedCard = page.locator("#liveSensorRoster article").nth(2);
  await expect(frontCard).toHaveText("Front Left Wheel");
  await expect(engineCard).toHaveText("Engine Bay");
  await expect(unassignedCard).toHaveText("Gamma Probe");

  const [frontOffset, engineOffset, unassignedOffset] = await Promise.all([
    frontCard.locator(".live-sensor-card__header strong").evaluate((el) => {
      const card = el.closest(".live-sensor-card");
      if (!(card instanceof HTMLElement)) {
        throw new Error("Expected live sensor card container");
      }
      return Math.round(el.getBoundingClientRect().left - card.getBoundingClientRect().left);
    }),
    engineCard.locator(".live-sensor-card__header strong").evaluate((el) => {
      const card = el.closest(".live-sensor-card");
      if (!(card instanceof HTMLElement)) {
        throw new Error("Expected live sensor card container");
      }
      return Math.round(el.getBoundingClientRect().left - card.getBoundingClientRect().left);
    }),
    unassignedCard.locator(".live-sensor-card__header strong").evaluate((el) => {
      const card = el.closest(".live-sensor-card");
      if (!(card instanceof HTMLElement)) {
        throw new Error("Expected live sensor card container");
      }
      return Math.round(el.getBoundingClientRect().left - card.getBoundingClientRect().left);
    }),
  ]);

  expect(Math.abs(frontOffset - engineOffset)).toBeLessThanOrEqual(1);
  expect(Math.abs(frontOffset - unassignedOffset)).toBeLessThanOrEqual(1);

  await page.locator("#tab-history").click();
  await expect(page.locator(".site-header__status")).toBeVisible();

  await page.locator("#tab-dashboard").click();
  await expect(page.locator(".site-header__status")).toBeHidden();
});
