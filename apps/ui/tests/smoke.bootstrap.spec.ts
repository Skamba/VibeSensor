import { expect, test } from "@playwright/test";

import {
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
} from "./smoke.helpers";

const strengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [],
};

function parseElapsedSeconds(value: string): number {
  const [minutes, seconds] = value.trim().split(":").map((part) => Number(part));
  return (minutes * 60) + seconds;
}

test("ui bootstrap smoke: tabs, ws state, recording, history", async ({ page }) => {
  let startCalls = 0;
  let stopCalls = 0;
  const startedAt = new Date(Date.now() - 65_000).toISOString();
  let recordingStatus = {
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
  };

  await installCommonRoutes(page, {
    runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }],
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history") || pathname.includes("/report.pdf")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, {
        runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }],
      });
    },
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Test Hatch",
              type: "Simulated setup",
              variant: null,
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
  await page.route("**/api/recording/start", async (route) => {
    startCalls += 1;
    recordingStatus = {
      ...recordingStatus,
      enabled: true,
      run_id: "run-001",
      analysis_in_progress: false,
      start_time_utc: startedAt,
      samples_written: 24,
      last_completed_run_id: null,
      last_completed_run_error: null,
    };
    await fulfillJson(route, recordingStatus);
  });
  await page.route("**/api/recording/stop", async (route) => {
    stopCalls += 1;
    recordingStatus = {
      ...recordingStatus,
      enabled: false,
      run_id: null,
      analysis_in_progress: true,
      start_time_utc: null,
      last_completed_run_id: "run-001",
      last_completed_run_error: null,
    };
    await fulfillJson(route, recordingStatus);
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
          location_code: "",
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
  await expect(page.getByRole("heading", { name: "VibeSensor" })).toBeVisible();
  await expect(page.locator(".site-header__status")).toBeHidden();
  await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText("1 / 1");
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText("Test Hatch");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Ready");
  await expect(page.locator("#liveDataFreshness [data-value]")).toHaveText("Fresh - 10 ms ago");
  await expect(page.locator("#liveRunHealth")).toBeHidden();
  await expect(page.locator("#liveStrongestSignal")).not.toHaveClass(/stat--spotlight/);
  await expect(page.locator("#liveStrongestSignal .stat__label")).toHaveText("Strongest sensor level");
  await expect(page.locator("#liveStrongestSignal [data-value]")).toContainText("Front Left");
  await expect(page.locator("#liveSensorRoster .live-sensor-card--strongest")).toHaveText("Front Left Wheel");
  await expect(page.locator("#liveSensorRoster .status-pill")).toHaveCount(0);
  await expect(page.locator("#liveSensorRoster .live-sensor-card__status-dot--online")).toHaveCount(1);
  await expect(page.locator("#liveSensorRoster article")).toHaveText("Front Left Wheel");
  await expect(page.locator(".spectrum-controls-panel")).toContainText("Use the trace chips to isolate one sensor at a time.");
  await expect(page.locator(".spectrum-controls-panel #spectrumInspector")).toBeVisible();
  await expect(page.locator(".spectrum-controls-panel #legend")).toContainText("Front Left");
  await expect(page.locator("#loggingSummary")).toBeHidden();
  await expect(page.locator("#loggingChecklist")).toBeVisible();
  await expect(page.locator("#loggingChecklist")).toContainText("Capture readiness checklist");
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#loggingPhase")).toBeHidden();
  await expect(page.locator("#loggingElapsed [data-value]")).toHaveText("--");
  await expect(page.locator("#loggingSamples [data-value]")).toHaveText("0");
  await expect(page.locator("#startLoggingBtn")).toBeVisible();
  await expect(page.locator("#stopLoggingBtn")).toBeHidden();
  const dashboardTab = page.locator("#tab-dashboard");
  const historyTab = page.locator("#tab-history");
  const settingsTab = page.locator("#tab-settings");

  await dashboardTab.focus();
  await dashboardTab.press("ArrowRight");
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
  await expect(page.locator(".site-header__status")).toBeVisible();
  await historyTab.press("ArrowLeft");
  await expect(page.locator("#dashboardView")).toHaveJSProperty("hidden", false);
  await expect(page.locator(".site-header__status")).toBeHidden();
  await dashboardTab.press("End");
  await expect(page.locator("#settingsView")).toHaveJSProperty("hidden", false);
  await expect(page.locator(".site-header__status")).toBeVisible();
  await settingsTab.press("Home");
  await expect(page.locator("#dashboardView")).toHaveJSProperty("hidden", false);
  await expect(page.locator(".site-header__status")).toBeHidden();
  await historyTab.click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
  await expect(page.locator(".site-header__status")).toBeVisible();
  await expect(page.locator("#historyTableBody")).toContainText("run-001");
  await dashboardTab.click();
  await expect(page.locator(".site-header__status")).toBeHidden();
  await page.locator("#startLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#loggingRunId")).toHaveText("Run ID: run-001");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Recording");
  await expect(page.locator("#loggingPhase")).toBeHidden();
  await expect(page.locator("#loggingElapsed [data-value]")).toHaveText(/^\d+:\d{2}$/);
  const activeElapsed = await page.locator("#loggingElapsed [data-value]").innerText();
  await expect(page.locator("#loggingSamples [data-value]")).toHaveText("24");
  await expect(page.locator("#startLoggingBtn")).toBeHidden();
  await expect(page.locator("#stopLoggingBtn")).toBeVisible();
  await expect(page.locator("#stopLoggingBtn")).toHaveClass(/btn--danger-quiet/);
  await expect.poll(() => startCalls).toBe(1);
  await page.locator("#stopLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#loggingRunId")).toHaveText("Last run: run-001");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Processing");
  await expect(page.locator("#loggingPhase")).toBeHidden();
  await expect(page.locator("#loggingElapsed [data-value]")).toHaveText(/^\d+:\d{2}$/);
  const processingElapsed = await page.locator("#loggingElapsed [data-value]").innerText();
  expect(parseElapsedSeconds(processingElapsed)).toBeGreaterThanOrEqual(parseElapsedSeconds(activeElapsed));
  await expect(page.locator("#loggingSamples [data-value]")).toHaveText("24");
  await expect(page.locator("#startLoggingBtn")).toBeVisible();
  await expect(page.locator("#stopLoggingBtn")).toBeHidden();
  const processingSummary = page.locator("#loggingSummary");
  await expect(processingSummary).toContainText("Run run-001 is being analyzed.");
  await expect(processingSummary).toContainText("Results will appear in History");
  await processingSummary.getByRole("button", { name: "Open History" }).click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
  await expect.poll(() => stopCalls).toBe(1);
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
      sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
      reference: { state: "pass", reasonKey: "reference_ready" },
      speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
    }),
  };

  await installCommonRoutes(page, {
    runs: [{ run_id: "run-002", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 24 }],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "Test Hatch", type: "Simulated setup", variant: null, aspects: {} }],
          active_car_id: "car-1",
        });
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
  await expect(savedSummary).toContainText("Open History to review the diagnosis");
  await savedSummary.getByRole("button", { name: "Open History" }).click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
});
