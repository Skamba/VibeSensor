import { expect, test } from "@playwright/test";

import {
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
  waitForFakeWebSocketSettled,
} from "./smoke.helpers";

test.describe.configure({ timeout: 12_000 });

const strengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [
    { hz: 1, amp: 0.3, vibration_strength_db: 12, strength_bucket: "l2" },
  ],
};

test("spectrum controls simplify the chart and update the inspector", async ({
  page,
}) => {
  await page.goto("/?demo=1");

  const inspector = page.locator("#spectrumInspector");
  const bandToggle = page.locator("#spectrumBandToggle");
  const bandLegend = page.locator("#bandLegend");
  const allTracesChip = page.getByRole("button", {
    name: /All sensor traces/i,
  });
  const adjacentChip = page.getByRole("button", { name: /Front Left Wheel/i });
  const sensorChip = page.getByRole("button", { name: /Front Right Wheel/i });

  await expect(bandToggle).toBeVisible();
  await expect(bandToggle).toHaveAttribute("aria-controls", "bandLegend");
  await expect(bandToggle).toHaveAttribute("aria-pressed", "false");
  await expect(bandToggle).toHaveAttribute("aria-expanded", "false");
  await expect(bandLegend).toBeHidden();
  await expect(inspector).toContainText("Strongest:");
  await expect(page.locator("#specChart canvas")).toBeVisible();
  await expect(sensorChip).not.toHaveAttribute("data-legend-state", "active");
  await expect(sensorChip).not.toHaveAttribute("data-legend-state", "muted");
  await sensorChip.click();
  await expect(sensorChip).toHaveAttribute("aria-pressed", "true");
  await expect(sensorChip).toHaveAttribute("data-legend-state", "active");
  await expect(adjacentChip).toHaveAttribute("data-legend-state", "muted");
  await expect(inspector).toContainText("Focused:");
  await expect(inspector).toContainText("Front Right Wheel");

  await bandToggle.click();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "true");
  await expect(bandToggle).toHaveAttribute("aria-expanded", "true");
  await expect(bandToggle).toHaveText("Hide reference bands");
  await expect(page.locator(".spectrum-toolbar__bands")).toContainText(
    "Hide reference bands",
  );
  await expect(page.locator(".spectrum-toolbar__bands")).toContainText(
    "Wheel 1x",
  );
  await expect(bandLegend).toBeVisible();
  await expect(bandLegend).toContainText("Wheel 1x");
  await expect(bandLegend.locator(".legend-item")).toHaveCount(4);
  const headerBottom = await page
    .locator(".site-header")
    .evaluate((el) => el.getBoundingClientRect().bottom);
  const controlsTop = await page
    .locator(".spectrum-controls-panel")
    .evaluate((el) => el.getBoundingClientRect().top);
  expect(controlsTop).toBeGreaterThanOrEqual(headerBottom - 1);

  await allTracesChip.click();
  await expect(allTracesChip).toHaveAttribute("aria-pressed", "true");
  await expect(sensorChip).toHaveAttribute("aria-pressed", "false");
  await expect(sensorChip).not.toHaveAttribute("data-legend-state", "active");
  await expect(sensorChip).not.toHaveAttribute("data-legend-state", "muted");
  await expect(inspector).toContainText("Strongest:");
});

test("spectrum controls stay interactive while repeated websocket updates arrive", async ({
  page,
}) => {
  const trackerKey = "__spectrumRepeatTracker";
  await installCommonRoutes(page, {
    locations: [
      { code: "front_left_wheel", label: "Front Left Wheel" },
      { code: "front_right_wheel", label: "Front Right Wheel" },
    ],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Selected",
              type: "sedan",
              aspects: {
                tire_width_mm: 245,
                tire_aspect_pct: 40,
                rim_in: 18,
                final_drive_ratio: 3.91,
                current_gear_ratio: 0.82,
              },
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
          details: { live_sensor_count: 2 },
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
      speed_mps: 22.2,
      clients: [
        {
          id: "front-right",
          name: "Front Right Wheel",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_right_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
        {
          id: "front-left",
          name: "Front Left Wheel",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "66778899aabb",
          firmware_version: "fw-1.0.0",
        },
      ],
      rotational_speeds: {
        basis_speed_source: "gps",
        wheel: { rpm: 738, mode: "calculated", reason: null },
        driveshaft: { rpm: 1476, mode: "calculated", reason: null },
        engine: { rpm: 2208, mode: "calculated", reason: null },
        order_bands: [
          { key: "wheel_1x", center_hz: 12.3, tolerance: 0.08 },
          { key: "wheel_2x", center_hz: 24.6, tolerance: 0.08 },
          { key: "driveshaft_1x", center_hz: 24.6, tolerance: 0.08 },
          { key: "engine_1x", center_hz: 36.8, tolerance: 0.08 },
        ],
      },
      spectra: {
        clients: {
          "front-right": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.3, 0.2, 0.1],
            strength_metrics: strengthMetrics,
          },
          "front-left": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.2, 0.1, 0.05],
            strength_metrics: {
              ...strengthMetrics,
              vibration_strength_db: 9,
            },
          },
        },
      },
    },
    repeatPayloadCount: 6,
    repeatPayloadIntervalMs: 50,
    trackerKey,
  });

  await page.goto("/");

  const inspector = page.locator("#spectrumInspector");
  const bandToggle = page.locator("#spectrumBandToggle");
  const bandLegend = page.locator("#bandLegend");
  const sensorChip = page.getByRole("button", { name: /Front Right Wheel/i });
  const allTracesChip = page.getByRole("button", {
    name: /All sensor traces/i,
  });

  await expect(sensorChip).toBeVisible();
  await expect(bandToggle).toBeVisible();

  await sensorChip.click();
  await expect(sensorChip).toHaveAttribute("aria-pressed", "true");
  await expect(sensorChip).toHaveAttribute("data-legend-state", "active");
  await expect(sensorChip).toContainText("12.0 dB");
  await expect(allTracesChip).toHaveAttribute("aria-pressed", "false");
  await expect(inspector).toContainText("Focused:");
  await expect(inspector).toContainText("Front Right Wheel");

  await bandToggle.click();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "true");
  await expect(bandToggle).toHaveAttribute("aria-expanded", "true");
  await expect(bandLegend).toBeVisible();

  await waitForFakeWebSocketSettled(page, trackerKey, 7);

  await expect(sensorChip).toHaveAttribute("aria-pressed", "true");
  await expect(sensorChip).toHaveAttribute("data-legend-state", "active");
  await expect(allTracesChip).toHaveAttribute("aria-pressed", "false");
  await expect(bandToggle).toHaveAttribute("aria-pressed", "true");
  await expect(bandLegend).toBeVisible();
  await expect(inspector).toContainText("Focused:");
  await expect(inspector).toContainText("Front Right Wheel");
});

test("spectrum band toggle stays hidden when no spectrum data is available", async ({
  page,
}) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }],
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
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 50,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {},
      },
    },
  });

  await page.goto("/");

  await expect(page.locator("#spectrumOverlay")).toBeVisible();
  await expect(page.locator("#spectrumOverlay")).toContainText(
    "Waiting for spectrum data",
  );
  await expect(page.locator("#spectrumBandToggle")).toBeHidden();
  await expect(page.locator("#bandLegend")).toBeHidden();
});
