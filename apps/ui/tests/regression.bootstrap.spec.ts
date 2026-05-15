import { expect, test } from "@playwright/test";

import {
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
  selectedCarSettings,
  speedSourceSettings,
} from "./smoke.helpers";

test.describe.configure({ timeout: 15_000 });

const strengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [],
};

test("dark mode theme regression keeps shared readiness and warning surfaces wired", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  let captureReadiness = buildCaptureReadiness({
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
  });
  await installCommonRoutes(page, {
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, selectedCarSettings({ name: "Test Hatch" }));
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
      capture_readiness: captureReadiness,
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
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {
          "001122334455": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.1, 0.2, 0.15],
            strength_metrics: strengthMetrics,
          },
        },
      },
    },
  });

  await page.goto("/");
  await expect(page.locator("#loggingChecklist")).toBeVisible();
  await expect(
    page
      .locator('.capture-readiness__item[data-readiness-state="pass"]')
      .first(),
  ).toContainText(/live sensor.*streaming cleanly/i);
  await expect(
    page.locator('.capture-readiness__item[data-readiness-state="pass"]'),
  ).toHaveCount(4);

  captureReadiness = buildCaptureReadiness({
    isReady: false,
    sensors: {
      state: "pass",
      reasonKey: "sensors_ready",
      details: { live_sensor_count: 1 },
    },
    reference: { state: "warn", reasonKey: "speed_sample_stale" },
    speed: { state: "fail", reasonKey: "speed_sample_missing" },
    overall: {
      state: "fail",
      reasonKey: "capture_blocked",
      details: { blocking_check: "speed_stable" },
    },
  });
  await page.reload();
  await expect(page.locator("#loggingChecklist")).toBeVisible();

  await expect(
    page
      .locator('.capture-readiness__item[data-readiness-state="warn"]')
      .first(),
  ).toContainText(/fresh live speed update/i);
  await expect(
    page
      .locator('.capture-readiness__item[data-readiness-state="fail"]')
      .first(),
  ).toContainText(/live speed sample/i);
  await expect(
    page.locator('.capture-readiness__item[data-readiness-state="warn"]'),
  ).toHaveCount(1);
  await expect(
    page.locator('.capture-readiness__item[data-readiness-state="fail"]'),
  ).toHaveCount(2);
  const banner = page.locator(".app-error-banner");
  await banner.evaluate((element) => {
    if (!(element instanceof HTMLElement)) {
      throw new Error("expected app error banner element");
    }
    element.hidden = false;
    element.dataset.variant = "warn";
    element.textContent = "Attention needed";
  });

  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("data-variant", "warn");
  await expect(banner).toContainText("Attention needed");
});

test("dashboard bootstrap defers secondary bundle until a dependent view opens", async ({
  page,
}) => {
  const secondaryBundleRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("app_feature_secondary_bundle")) {
      secondaryBundleRequests.push(request.url());
    }
  });

  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/cars") {
        await fulfillJson(route, selectedCarSettings({ name: "Test Hatch" }));
        return;
      }
      if (path === "/api/settings/speed-source") {
        await fulfillJson(route, speedSourceSettings());
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);

  await page.goto("/");
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText(
    "Test Hatch",
  );
  expect(secondaryBundleRequests).toEqual([]);

  await page.locator("#tab-settings").click();
  await expect.poll(() => secondaryBundleRequests.length).toBeGreaterThan(0);
  expect(new Set(secondaryBundleRequests).size).toBe(1);
  await expect(page.locator("#settingsView")).toHaveJSProperty("hidden", false);
});

test("saved run state points directly to History", async ({ page }) => {
  const recordingStatus = {
    enabled: false,
    run_id: null,
    write_error: null,
    analysis_in_progress: false,
    start_time_utc: null,
    samples_written: 24,
    samples_dropped: 0,
    last_completed_run_id: "run-002",
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
  };

  await installCommonRoutes(page, {
    runs: [
      {
        run_id: "run-002",
        start_time_utc: "2026-01-01T00:00:00Z",
        sample_count: 24,
      },
    ],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, selectedCarSettings({ name: "Test Hatch" }));
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, recordingStatus);
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
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {
          "001122334455": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.1, 0.2, 0.15],
            strength_metrics: strengthMetrics,
          },
        },
      },
    },
  });

  await page.goto("/");
  const savedSummary = page.locator("#loggingSummary");
  await expect(page.locator("#loggingRunId")).toHaveText("Last run: run-002");
  await expect(savedSummary).toContainText("Run run-002 is ready in History.");
  await expect(savedSummary).toContainText(
    "Open History to review the diagnosis",
  );
  await expect(
    savedSummary.locator('[data-inline-state-action="open-history"]'),
  ).toHaveText("Open History");
  await savedSummary.getByRole("button", { name: "Open History" }).click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
  await expect(
    page.locator('[data-run-row="1"][data-run="run-002"]'),
  ).toBeVisible();
});
