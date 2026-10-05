import { expect, type Page, type Route, test } from "@playwright/test";

import type {
  CarsPayload,
  HistoryEntry,
  LoggingStatusPayload,
} from "../src/api/types";
import {
  bootLiveDashboard,
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  type LiveClientFixture,
  openHistoryTab,
  openSensorsTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

const SENSOR_ID = "001122334455";

const READY = buildCaptureReadiness({
  isReady: true,
  sensors: {
    state: "pass",
    reasonKey: "sensors_ready",
    details: { live_sensor_count: 1 },
  },
  reference: { state: "pass", reasonKey: "reference_ready" },
  speed: { state: "pass", reasonKey: "speed_stable" },
});

function idleStatus(
  overrides: Partial<LoggingStatusPayload> = {},
): LoggingStatusPayload {
  return {
    enabled: false,
    run_id: null,
    write_error: null,
    analysis_in_progress: false,
    start_time_utc: null,
    samples_written: 0,
    samples_dropped: 0,
    last_completed_run_id: null,
    last_completed_run_error: null,
    capture_readiness: READY,
    ...overrides,
  };
}

async function activeCar(route: Route): Promise<void> {
  if (requestPath(route).startsWith("/api/settings/cars")) {
    await fulfillJson<CarsPayload>(route, {
      cars: [{ id: "car-1", name: "Test Hatch", type: "sedan", aspects: {} }],
      active_car_id: "car-1",
    });
    return;
  }
  await fulfillJson(route, {});
}

function sensor(locationCode: string): LiveClientFixture {
  return {
    id: SENSOR_ID,
    name: SENSOR_ID,
    connected: true,
    sample_rate_hz: 1000,
    last_seen_age_ms: 10,
    dropped_frames: 0,
    frames_total: 100,
    location_code: locationCode,
    mac_address: SENSOR_ID,
    firmware_version: "fw-1.0.0",
    firmware_status: "unknown",
  };
}

function strength(db: number) {
  return {
    vibration_strength_db: db,
    peak_amp_g: 0.2,
    noise_floor_amp_g: 0.01,
    strength_bucket: null,
    top_peaks: [],
  };
}

/** Common routes with an active car, then a recording status the test controls. */
async function bootWithStatus(
  page: Page,
  status: (route: Route) => Promise<void>,
  options: {
    runs?: () => HistoryEntry[];
    locationCode?: string;
  } = {},
): Promise<void> {
  await installCommonRoutes(page, {
    settingsHandler: activeCar,
    locations: [
      { code: "front_left_wheel", label: "Front Left Wheel" },
      { code: "rear_right_wheel", label: "Rear Right Wheel" },
    ],
    historyHandler: async (route) => {
      await fulfillJson(route, { runs: options.runs?.() ?? [] });
    },
  });
  await page.route("**/api/recording/status", status);
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: {
      clients: [sensor(options.locationCode ?? "front_left_wheel")],
    },
  });
}

test("journey: the readiness checklist explains what is missing and links to the fix", async ({
  page,
}) => {
  const readiness = buildCaptureReadiness({
    isReady: false,
    sensors: {
      state: "fail",
      reasonKey: "sensor_locations_missing",
      details: { unassigned_sensor_count: 1 },
    },
    reference: { state: "pass", reasonKey: "reference_ready" },
    speed: {
      state: "warn",
      reasonKey: "speed_too_low",
      details: { minimum_speed_kmh: 30 },
    },
  });
  await bootWithStatus(
    page,
    (route) => fulfillJson(route, idleStatus({ capture_readiness: readiness })),
    { locationCode: "" },
  );

  const summary = page.locator("#loggingSummary");
  await expect(summary).toContainText("Finish setup before recording.");
  await expect(summary).toContainText(
    "1 live sensor(s) still need a location.",
  );
  await expect(page.locator(".realtime-logging-shell")).toHaveAttribute(
    "data-layout",
    "setup",
  );
  // The live spectrum stays visible while setting up.
  await expect(page.locator("#specChart")).toBeVisible();
  const items = page.locator("#loggingChecklist .capture-readiness__item");
  await expect(items).toHaveCount(2);
  await expect(items.nth(1)).toContainText("30");
  await expect(page.locator("#liveRunHealth")).toHaveText("Needs attention");

  await summary.getByRole("button", { name: "Open Sensors" }).click();
  await expect(page.locator("#sensorsTab")).toBeVisible();
  await expect(page.locator("#shellLiveStatus")).toHaveText("Needs attention");
});

test("journey: a parked car can start, and the capability line says what the run can test", async ({
  page,
}) => {
  const parked = buildCaptureReadiness({
    isReady: true,
    sensors: {
      state: "pass",
      reasonKey: "sensors_ready",
      details: { live_sensor_count: 1 },
    },
    reference: { state: "pass", reasonKey: "reference_ready" },
    speed: {
      state: "warn",
      reasonKey: "speed_too_low",
      details: { minimum_speed_kmh: 30 },
    },
    overall: { state: "pass", reasonKey: "ready_with_warnings" },
  });
  parked.capabilities = {
    wheel: "ok",
    driveline: "missing_final_drive",
    engine: "estimated_top_gear",
  };
  await bootWithStatus(page, (route) =>
    fulfillJson(route, idleStatus({ capture_readiness: parked })),
  );

  await expect(page.locator("#startLoggingBtn")).toBeEnabled();
  await expect(page.locator("#startHint")).toBeVisible();
  const speedItem = page.locator(
    '#loggingChecklist [data-readiness-state="warn"]',
  );
  await expect(speedItem).toContainText("Tip");

  const capabilities = page.locator("#captureCapabilities");
  await expect(
    capabilities.locator('[data-capability="wheel"]'),
  ).toHaveAttribute("data-capability-mark", "ok");
  await expect(
    capabilities.locator('[data-capability="engine"]'),
  ).toContainText("assuming top gear");
  await expect(page.locator("#captureLayoutNote")).toContainText("One sensor");
  await capabilities
    .locator('[data-capability="driveline"]')
    .getByRole("button", { name: "Add final drive" })
    .click();
  await expect(page.locator("#carTab")).toBeVisible();
});

test("journey: an unreadable recording status disables recording until it recovers", async ({
  page,
}) => {
  let failing = true;
  await bootWithStatus(page, async (route) => {
    if (failing) {
      await route.fulfill({ status: 503, body: "down" });
      return;
    }
    await fulfillJson(route, idleStatus());
  });

  await expect(page.locator("#loggingStatus")).toHaveText("Unavailable");
  await expect(page.locator("#loggingStatus")).toHaveAttribute(
    "data-variant",
    "bad",
  );
  await expect(page.locator("#startLoggingBtn")).toBeDisabled();
  await expect(page.locator("#loggingSamples [data-value]")).toHaveText("--");

  failing = false;
  await expect(page.locator("#startLoggingBtn")).toBeEnabled();
  await expect(page.locator("#loggingStatus")).toBeHidden();
});

test("journey: a failed start shows the server's reason and a retry records", async ({
  page,
}) => {
  let status = idleStatus();
  let startCalls = 0;
  const posts: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path === "/api/system/browser-clock" ||
      path === "/api/recording/start"
    ) {
      posts.push(path);
    }
  });
  await bootWithStatus(page, (route) => fulfillJson(route, status));
  await page.route("**/api/recording/start", async (route) => {
    startCalls += 1;
    if (startCalls === 1) {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Storage is full" }),
      });
      return;
    }
    status = idleStatus({
      enabled: true,
      run_id: "run-9",
      start_time_utc: new Date(Date.now() - 65_000).toISOString(),
    });
    await fulfillJson(route, status);
  });

  const start = page.locator("#startLoggingBtn");
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.locator("#loggingStatus")).toHaveText("Storage is full");
  await expect(page.locator("#loggingSummary")).toHaveText("Storage is full");

  await start.click();
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Recording",
  );
  await expect(page.locator("#loggingRunId")).toContainText("run-9");
  await expect(page.locator("#loggingElapsed [data-value]")).toHaveText(
    /^1:0\d$/,
  );
  await expect(page.locator("#stopLoggingBtn")).toBeEnabled();
  await expect(start).toBeHidden();
  // Each start sets an unset Pi clock from the browser first.
  expect(posts.slice(-4)).toEqual([
    "/api/system/browser-clock",
    "/api/recording/start",
    "/api/system/browser-clock",
    "/api/recording/start",
  ]);
  expect(startCalls).toBe(2);
});

test("journey: History reloads when analysis finishes, and an auto-stopped run says so", async ({
  page,
}) => {
  let status = idleStatus({
    analysis_in_progress: true,
    last_completed_run_id: "run-002",
  });
  let runs: HistoryEntry[] = [
    {
      run_id: "run-001",
      status: "complete",
      start_time_utc: "2026-01-01T00:00:00Z",
      start_time_unverified: false,
      created_at: "2026-01-01T00:00:00Z",
      raw_sample_count: 12080,
    },
  ];
  await bootWithStatus(page, (route) => fulfillJson(route, status), {
    runs: () => runs,
  });

  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Processing",
  );
  await openHistoryTab(page);
  await expect(page.locator("#historyTableBody")).toContainText("run-001");
  await expect(page.locator("#historyTableBody")).not.toContainText("run-002");

  status = idleStatus({
    last_completed_run_id: "run-002",
    last_stop_reason: "max_duration",
  });
  runs = [
    ...runs,
    {
      run_id: "run-002",
      status: "complete",
      start_time_utc: "2026-01-02T00:00:00Z",
      start_time_unverified: false,
      created_at: "2026-01-02T00:00:00Z",
      raw_sample_count: 12080,
    },
  ];
  await expect(page.locator("#historyTableBody")).toContainText("run-002");

  // The run hit the 30-minute cap, and Live says so.
  await page.locator("#tab-dashboard").click();
  await expect(page.locator("#loggingSummary")).toContainText(
    "Recording stopped automatically at the 30-minute limit.",
  );
});

test("journey: assigning a sensor location re-checks readiness right away", async ({
  page,
}) => {
  let statusCalls = 0;
  await page.clock.install();
  await page.route("**/api/clients/**", (route) => fulfillJson(route, {}));
  await bootWithStatus(page, async (route) => {
    statusCalls += 1;
    await fulfillJson(route, idleStatus());
  });
  await expect(page.locator("#startLoggingBtn")).toBeEnabled();
  await openSensorsTab(page);
  // Freeze timers so only the readiness re-check, not the 2 s poll, can fetch.
  await page.clock.pauseAt(Date.now() + 60_000);
  // Jumping ahead fires the poll that was due; let it land before counting.
  let before = -1;
  await expect
    .poll(async () => {
      const seen = statusCalls;
      await page.waitForTimeout(300);
      before = seen;
      return statusCalls === seen;
    })
    .toBe(true);

  await page
    .locator(`select[data-client-id="${SENSOR_ID}"]`)
    .selectOption("rear_right_wheel");
  await expect.poll(() => statusCalls).toBe(before + 1);
});

test("journey: sensor cards show location labels and the strongest signal", async ({
  page,
}) => {
  await installCommonRoutes(page, {
    settingsHandler: activeCar,
    locations: [
      { code: "front_left_wheel", label: "Front Left Wheel" },
      { code: "rear_right_wheel", label: "Rear Right Wheel" },
    ],
  });
  await page.route("**/api/recording/status", (route) =>
    fulfillJson(route, idleStatus()),
  );
  await installFakeWebSocket(page, {
    payload: {
      clients: [
        sensor("front_left_wheel"),
        { ...sensor(""), id: "b", name: "Rear Right" },
      ],
      spectra: {
        clients: {
          [SENSOR_ID]: {
            freq: [1, 2],
            combined_spectrum_amp_g: [0.1, 0.2],
            strength_metrics: strength(7),
          },
          b: {
            freq: [1, 2],
            combined_spectrum_amp_g: [0.1, 0.2],
            strength_metrics: strength(18),
          },
        },
      },
    },
  });
  await page.goto("/");

  const cards = page.locator("#liveSensorRoster .live-sensor-card");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toContainText("Front Left Wheel");
  // "Rear Right" in the name maps to the rear-right location.
  await expect(cards.nth(1)).toContainText("Rear Right Wheel");
  await expect(cards.nth(1)).toHaveAttribute("data-strongest", "true");
  await expect(page.locator("#liveStrongestSignal [data-value]")).toHaveText(
    "Rear Right Wheel · 18 dB",
  );
  await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText(
    "2 / 2",
  );
});

test("journey: the guided test drive walks sweep, hold and neutral coast-down while recording", async ({
  page,
}) => {
  let status = idleStatus({
    enabled: true,
    run_id: "run-7",
    start_time_utc: new Date(Date.now() - 5_000).toISOString(),
  });
  const marked: Array<string | null> = [];
  await bootWithStatus(page, (route) => fulfillJson(route, status));
  await page.route("**/api/recording/guided-phase", async (route) => {
    const phase = (route.request().postDataJSON() as { phase: string | null })
      .phase as LoggingStatusPayload["guided_phase"];
    marked.push(phase ?? null);
    const finishedStep = status.guided_phase;
    status = {
      ...status,
      guided_phase: phase,
      guided_phases_completed: [
        ...(status.guided_phases_completed ?? []),
        ...(finishedStep ? [finishedStep] : []),
      ],
    };
    await fulfillJson(route, status);
  });

  const panel = page.locator("#guidedTest");
  const button = page.locator("#guidedTestBtn");
  const stepState = (phase: string) =>
    panel.locator(`[data-guided-step="${phase}"]`);
  await expect(panel).toContainText("Guided test drive (optional)");
  await expect(button).toHaveText("Start guided test");

  await button.click();
  await expect(stepState("sweep")).toHaveAttribute(
    "data-step-state",
    "current",
  );
  await expect(panel).toContainText(
    "In top gear (or D), accelerate smoothly from about 50 to 120 km/h",
  );
  await expect(button).toHaveText("Next: Steady hold");

  await button.click();
  await expect(button).toHaveText("Next: Neutral coast-down");

  // A reload mid-run picks the guided test up where the driver left it.
  await page.reload();
  await expect(stepState("sweep")).toHaveAttribute("data-step-state", "done");
  await expect(stepState("hold")).toHaveAttribute("data-step-state", "current");
  await expect(button).toHaveText("Next: Neutral coast-down");

  await button.click();
  await expect(panel).toContainText("shift to neutral");
  await expect(button).toHaveText("Finish guided test");

  await button.click();
  await expect(panel).toContainText("Guided test done.");
  await expect(button).toBeHidden();
  expect(marked).toEqual(["sweep", "hold", "coast_down", null]);

  // ...and still knows the guided test is done after another reload.
  await page.reload();
  await expect(panel).toContainText("Guided test done.");
  for (const phase of ["sweep", "hold", "coast_down"]) {
    await expect(stepState(phase)).toHaveAttribute("data-step-state", "done");
  }
  await expect(button).toBeHidden();

  status = idleStatus();
  await expect(panel).toBeHidden();
});

test("journey: guided step speeds follow the speed unit setting", async ({
  page,
}) => {
  const status = idleStatus({
    enabled: true,
    run_id: "run-8",
    start_time_utc: new Date(Date.now() - 5_000).toISOString(),
    guided_phase: "sweep",
  });
  await bootWithStatus(page, (route) => fulfillJson(route, status));
  const panel = page.locator("#guidedTest");
  await expect(panel).toContainText("from about 50 to 120 km/h");
  // Routes added later win over the common settings route.
  await page.route("**/api/settings/speed-unit", (route) =>
    fulfillJson(route, { speed_unit: "mps" }),
  );
  await page.reload();

  await expect(panel).toContainText(
    "In top gear (or D), accelerate smoothly from about 14 to 33 m/s",
  );
});
