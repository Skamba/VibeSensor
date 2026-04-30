import { expect, test } from "@playwright/test";

import {
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  readSemanticSurfaceStyles,
  readSemanticToneStyles,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 15_000 });

const strengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [],
};

function parseElapsedSeconds(value: string): number {
  const [minutes, seconds] = value
    .trim()
    .split(":")
    .map((part) => Number(part));
  return minutes * 60 + seconds;
}

test("dark mode theme smoke keeps shared readiness and warning surfaces wired", async ({
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
  const passStyles = await readSemanticSurfaceStyles(
    page
      .locator('.capture-readiness__item[data-readiness-state="pass"]')
      .first(),
    "--capture-readiness-pass-surface",
    "--capture-readiness-pass-border",
  );
  expect(passStyles.backgroundColor).toBe(passStyles.expectedBackgroundColor);
  expect(passStyles.borderColor).toBe(passStyles.expectedBorderColor);

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

  const expectations = [
    {
      locator: page
        .locator('.capture-readiness__item[data-readiness-state="warn"]')
        .first(),
      surfaceVar: "--capture-readiness-warn-surface",
      borderVar: "--capture-readiness-warn-border",
    },
    {
      locator: page
        .locator('.capture-readiness__item[data-readiness-state="fail"]')
        .first(),
      surfaceVar: "--capture-readiness-fail-surface",
      borderVar: "--capture-readiness-fail-border",
    },
  ] as const;

  for (const expectation of expectations) {
    const styles = await readSemanticSurfaceStyles(
      expectation.locator,
      expectation.surfaceVar,
      expectation.borderVar,
    );
    expect(styles.backgroundColor).toBe(styles.expectedBackgroundColor);
    expect(styles.borderColor).toBe(styles.expectedBorderColor);
  }
  const banner = page.locator(".app-error-banner");
  await banner.evaluate((element) => {
    if (!(element instanceof HTMLElement)) {
      throw new Error("expected app error banner element");
    }
    element.hidden = false;
    element.dataset.variant = "warn";
    element.textContent = "Attention needed";
  });

  const bannerStyles = await readSemanticToneStyles(banner, {
    surfaceVar: "--warning-surface",
    borderVar: "--warning-border",
    textVar: "--warning-text",
  });
  const bannerBorderColor = await banner.evaluate((element) => {
    const probe = document.createElement("div");
    probe.style.borderBottom = "1px solid var(--warning-border)";
    probe.style.position = "absolute";
    probe.style.visibility = "hidden";
    probe.style.pointerEvents = "none";
    document.body.appendChild(probe);
    const result = {
      actual: getComputedStyle(element).borderBottomColor,
      expected: getComputedStyle(probe).borderBottomColor,
    };
    probe.remove();
    return result;
  });
  expect(bannerStyles.backgroundColor).toBe(
    bannerStyles.expectedBackgroundColor,
  );
  expect(bannerBorderColor.actual).toBe(bannerBorderColor.expected);
  expect(bannerStyles.color).toBe(bannerStyles.expectedColor);
});

test("ui bootstrap smoke: tabs, ws state, recording, history", async ({
  page,
}) => {
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
        run_id: "run-001",
        start_time_utc: "2026-01-01T00:00:00Z",
        sample_count: 42,
      },
    ],
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (
        !pathname.startsWith("/api/history") ||
        pathname.includes("/report.pdf")
      ) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, {
        runs: [
          {
            run_id: "run-001",
            start_time_utc: "2026-01-01T00:00:00Z",
            sample_count: 42,
          },
        ],
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
  await expect(page.locator("#appShellChromeRoot > .wrap")).toHaveCount(1);
  await expect(
    page.locator(
      "body > #dashboardView, body > #historyView, body > #settingsView",
    ),
  ).toHaveCount(0);
  await expect(page.locator("#appShellChromeRoot #dashboardView")).toHaveCount(
    1,
  );
  await expect(page.locator("#appShellChromeRoot #historyView")).toHaveCount(1);
  await expect(page.locator("#appShellChromeRoot #settingsView")).toHaveCount(
    1,
  );
  await expect(page.getByRole("heading", { name: "VibeSensor" })).toBeVisible();
  await expect(page.locator(".site-header__status")).toBeHidden();
  await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText(
    "1 / 1",
  );
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText(
    "Test Hatch",
  );
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Ready",
  );
  await expect(page.locator("#liveDataFreshness [data-value]")).toHaveText(
    "Fresh - 10 ms ago",
  );
  await expect(page.locator("#liveRunHealth")).toBeHidden();
  await expect(page.locator("#liveStrongestSignal")).not.toHaveClass(
    /stat--spotlight/,
  );
  await expect(page.locator("#liveStrongestSignal .stat__label")).toHaveText(
    "Strongest signal",
  );
  await expect(page.locator("#liveStrongestSignal [data-value]")).toContainText(
    "Front Left",
  );
  await expect(
    page.locator("#liveSensorRoster [data-strongest='true']"),
  ).toHaveText("Front Left Wheel");
  await expect(page.locator("#liveSensorRoster .status-pill")).toHaveCount(0);
  await expect(
    page.locator(
      '#liveSensorRoster .live-sensor-card__status-dot[data-status="online"]',
    ),
  ).toHaveCount(1);
  await expect(page.locator("#liveSensorRoster article")).toHaveText(
    "Front Left Wheel",
  );
  await expect(page.locator(".spectrum-controls-panel")).toContainText(
    "Select a trace to isolate it.",
  );
  await expect(
    page.locator(".spectrum-controls-panel #spectrumInspector"),
  ).toBeVisible();
  await expect(page.locator(".spectrum-controls-panel #legend")).toContainText(
    "Front Left",
  );
  await expect(page.locator("#loggingSummary")).toBeHidden();
  await expect(page.locator("#loggingChecklist")).toBeVisible();
  await expect(page.locator("#loggingChecklist")).toContainText(
    "Capture readiness checklist",
  );
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
  await expect(page.locator("#dashboardView")).toHaveJSProperty(
    "hidden",
    false,
  );
  await expect(page.locator(".site-header__status")).toBeHidden();
  await dashboardTab.press("End");
  await expect(page.locator("#settingsView")).toHaveJSProperty("hidden", false);
  await expect(page.locator(".site-header__status")).toBeVisible();
  await settingsTab.press("Home");
  await expect(page.locator("#dashboardView")).toHaveJSProperty(
    "hidden",
    false,
  );
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
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Recording",
  );
  await expect(page.locator("#loggingPhase")).toBeHidden();
  await expect(page.locator("#loggingElapsed [data-value]")).toHaveText(
    /^\d+:\d{2}$/,
  );
  const activeElapsed = await page
    .locator("#loggingElapsed [data-value]")
    .innerText();
  await expect(page.locator("#loggingSamples [data-value]")).toHaveText("24");
  await expect(page.locator("#startLoggingBtn")).toBeHidden();
  await expect(page.locator("#stopLoggingBtn")).toBeVisible();
  await expect(page.locator("#stopLoggingBtn")).toHaveClass(
    /btn--danger-quiet/,
  );
  await expect.poll(() => startCalls).toBe(1);
  await page.locator("#stopLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#loggingRunId")).toHaveText("Last run: run-001");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Processing",
  );
  await expect(page.locator("#loggingPhase")).toBeHidden();
  await expect(page.locator("#loggingElapsed [data-value]")).toHaveText(
    /^\d+:\d{2}$/,
  );
  const processingElapsed = await page
    .locator("#loggingElapsed [data-value]")
    .innerText();
  expect(parseElapsedSeconds(processingElapsed)).toBeGreaterThanOrEqual(
    parseElapsedSeconds(activeElapsed),
  );
  await expect(page.locator("#loggingSamples [data-value]")).toHaveText("24");
  await expect(page.locator("#startLoggingBtn")).toBeVisible();
  await expect(page.locator("#stopLoggingBtn")).toBeHidden();
  const processingSummary = page.locator("#loggingSummary");
  await expect(processingSummary).toContainText(
    "Run run-001 is being analyzed.",
  );
  await expect(processingSummary).toContainText(
    "Results will appear in History",
  );
  await processingSummary.getByRole("button", { name: "Open History" }).click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
  await expect.poll(() => stopCalls).toBe(1);
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
      if (path === "/api/settings/speed-source") {
        await fulfillJson(route, {
          speed_source: "gps",
          manual_speed_kph: null,
          stale_timeout_s: 5,
        });
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
  await savedSummary.getByRole("button", { name: "Open History" }).click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
});
