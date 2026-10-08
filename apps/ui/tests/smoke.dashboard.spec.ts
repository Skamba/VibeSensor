import { expect, type Page, type Route, test } from "@playwright/test";

import type {
  BrowserClockPayload,
  CarsPayload,
  HistoryEntry,
  LoggingStatusPayload,
  SpeedSourcePayload,
  SpeedSourceStatusPayload,
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
    raw_samples_written: 0,
    samples_dropped: 0,
    last_completed_run_id: null,
    last_completed_run_error: null,
    guided_brake_stops: 0,
    capture_readiness: READY,
    no_data_timeout_s: 60,
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

test("journey: the setup checklist names the open step and links to the fix", async ({
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

  const setup = page.locator("#liveSetup");
  const steps = setup.locator("[data-setup-step]");
  await expect(steps).toHaveCount(3);
  await expect(steps.nth(0)).toHaveAttribute("data-step-state", "done");
  await expect(steps.nth(1)).toHaveAttribute("data-step-state", "done");
  const sensorsStep = setup.locator('[data-setup-step="sensors"]');
  await expect(sensorsStep).toHaveAttribute("data-step-state", "current");
  await expect(sensorsStep).toContainText(
    "1 live sensor still needs a location.",
  );
  // The live spectrum stays visible while setting up.
  await expect(page.locator("#specChart")).toBeVisible();
  // The card leaves the next step to the setup list; Start stays greyed out.
  await expect(page.locator("#loggingChecklist")).toBeHidden();
  const bar = page.locator("#liveActionBar");
  await expect(bar).toHaveAttribute("data-state", "setup");
  await expect(bar).toContainText("Setup 3 of 3: Sensors");
  await expect(page.locator("#shellLiveStatus")).toHaveText("Needs attention");

  await sensorsStep.getByRole("button", { name: "Place 1 sensor" }).click();
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

test("journey: with a typed-in speed, each family is hedged and the guided steps say they can't be checked", async ({
  page,
}) => {
  const readiness = buildCaptureReadiness({
    isReady: true,
    sensors: {
      state: "pass",
      reasonKey: "sensors_ready",
      details: { live_sensor_count: 1 },
    },
    reference: { state: "pass", reasonKey: "reference_ready" },
    speed: { state: "pass", reasonKey: "speed_stable" },
    overall: { state: "pass", reasonKey: "ready_with_warnings" },
  });
  readiness.capabilities = {
    wheel: "manual_speed",
    driveline: "manual_speed",
    engine: "manual_speed",
  };
  let status = idleStatus({ capture_readiness: readiness });
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/speed-source") {
        await fulfillJson<SpeedSourcePayload>(route, {
          speed_source: "manual",
          manual_speed_kph: 80,
          stale_timeout_s: 10,
        });
        return;
      }
      await activeCar(route);
    },
  });
  await page.route("**/api/recording/status", (route) =>
    fulfillJson(route, status),
  );
  await bootLiveDashboard(page, {
    installRoutes: false,
    liveSensorPayload: { clients: [sensor("front_left_wheel")] },
  });

  // Found only at exactly the typed-in speed, never ruled out: "~", not "✕".
  const capabilities = page.locator("#captureCapabilities");
  for (const family of ["wheel", "driveline", "engine"]) {
    await expect(
      capabilities.locator(`[data-capability="${family}"]`),
    ).toHaveAttribute("data-capability-mark", "caveat");
  }
  await expect(capabilities.locator('[data-capability="wheel"]')).toContainText(
    "Only at exactly the typed-in speed; it can't be ruled out.",
  );

  const preview = page.locator("#guidedPreview");
  await preview.locator("summary").click();
  await expect(page.locator("#guidedTypedInNote")).toContainText(
    "none of these steps can be checked",
  );

  // Recording: the guided test is not offered on a typed-in speed.
  status = idleStatus({ enabled: true, run_id: "run-3" });
  await expect(page.locator("#guidedTest #guidedTypedInNote")).toBeVisible();
  await expect(page.locator("#guidedTestBtn")).toHaveCount(0);
  await page
    .locator("#guidedTypedInNote")
    .getByRole("button", { name: "Change speed source" })
    .click();
  await expect(page.locator("#speedSourceTab")).toBeVisible();
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
    // The Pi clock is months behind and was not set (no RTC, no network): the
    // run's start_time_utc is wrong, its monotonic elapsed_s is not.
    status = idleStatus({
      enabled: true,
      run_id: "run-9",
      start_time_utc: "2026-01-01T00:00:00Z",
      elapsed_s: 65,
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
  const stop = page.locator("#stopLoggingBtn");
  await expect(stop).toBeEnabled();
  await expect(start).toBeHidden();
  // Hovering Stop keeps a danger fill instead of the pale generic hover.
  const dangerFill = await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.background = "var(--danger-700)";
    document.body.append(probe);
    const fill = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return fill;
  });
  await stop.hover();
  await expect
    .poll(() => stop.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe(dangerFill);
  // Each start sets an unset Pi clock from the browser first.
  expect(posts.slice(-4)).toEqual([
    "/api/system/browser-clock",
    "/api/recording/start",
    "/api/system/browser-clock",
    "/api/recording/start",
  ]);
  expect(startCalls).toBe(2);
});

test("journey: a run recorded before the Pi clock was set gets its time once it stops", async ({
  page,
}) => {
  // The browser connected mid-run: the server would not step the clock under a
  // recording, so the run is stored with an unverified start.
  let status = idleStatus({
    enabled: true,
    run_id: "run-9",
    start_time_utc: "2025-01-01T00:00:00Z",
    elapsed_s: 65,
  });
  let runs: HistoryEntry[] = [
    {
      run_id: "run-9",
      status: "complete",
      start_time_utc: "2025-01-01T00:00:00Z",
      start_time_unverified: true,
      interrupted: false,
      created_at: "2025-01-01T00:00:00Z",
      raw_sample_count: 12080,
    },
  ];
  const posts: string[] = [];
  let historyAfterStop: Promise<unknown> = Promise.resolve();
  await bootWithStatus(page, (route) => fulfillJson(route, status), {
    runs: () => runs,
  });
  await page.route("**/api/system/browser-clock", async (route) => {
    posts.push("browser-clock");
    if (status.enabled) {
      await fulfillJson<BrowserClockPayload>(route, {
        action: "recording",
        offset_s: 3.2e7,
        time_zone: null,
        runs_corrected: 0,
      });
      return;
    }
    // Idle now: the clock is stepped and this boot's unverified run re-dated,
    // after the History reload that Stop itself triggers, so only the
    // report's runs_corrected can bring the new time in.
    await historyAfterStop;
    runs = [
      {
        ...runs[0],
        start_time_utc: "2026-01-01T09:30:00Z",
        start_time_unverified: false,
      },
    ];
    await fulfillJson<BrowserClockPayload>(route, {
      action: "stepped",
      offset_s: 3.2e7,
      time_zone: null,
      runs_corrected: 1,
    });
  });
  await page.route("**/api/recording/stop", async (route) => {
    posts.push("stop");
    historyAfterStop = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/history",
    );
    status = idleStatus({ last_completed_run_id: "run-9" });
    await fulfillJson(route, status);
  });

  await openHistoryTab(page);
  await expect(page.locator("#historyTableBody")).toContainText("Date unknown");
  await page.locator("#tab-dashboard").click();
  await page.locator("#stopLoggingBtn").click();
  await expect(page.locator("#startLoggingBtn")).toBeVisible();

  // The clock is reported again once the run has stopped.
  await expect.poll(() => posts.slice(-2)).toEqual(["stop", "browser-clock"]);
  await openHistoryTab(page);
  await expect(page.locator("#historyTableBody")).not.toContainText(
    "Date unknown",
  );
  await expect(page.locator("#historyTableBody")).toContainText("1 Jan");
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
      interrupted: false,
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
  await expect(
    page.locator('#historyTableBody [data-run-row="1"][data-run="run-001"]'),
  ).toHaveCount(1);
  await expect(
    page.locator('#historyTableBody [data-run-row="1"][data-run="run-002"]'),
  ).toHaveCount(0);

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
      interrupted: false,
      created_at: "2026-01-02T00:00:00Z",
      raw_sample_count: 12080,
    },
  ];
  await expect(
    page.locator('#historyTableBody [data-run-row="1"][data-run="run-002"]'),
  ).not.toHaveCount(0);

  // The run hit the 30-minute cap, and Live says so.
  await page.locator("#tab-dashboard").click();
  await expect(page.locator("#autoStopNotice")).toContainText(
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

  // Select the placed sensor on the car, then move it to another spot.
  await page.locator('.car-spot[data-code="front_left_wheel"]').click();
  await page.locator('.car-spot[data-code="rear_right_wheel"]').click();
  await expect.poll(() => statusCalls).toBe(before + 1);
});

test("journey: sensor cards show the location, or the name of an unplaced sensor", async ({
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
  // A name that looks like a location is not one until the sensor is placed.
  await expect(cards.nth(1)).toContainText("Rear Right · unplaced");
  await expect(cards.nth(1)).toHaveAttribute("data-strongest", "true");
  await expect(page.locator("#liveStrongestSignal [data-value]")).toHaveText(
    "Rear Right · unplaced · 18 dB above floor",
  );
  await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText(
    "2 / 2",
  );
});

test("journey: the guided test drive walks sweep, hold, neutral coast-down and firm stops while recording", async ({
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
  const start = page.locator("#guidedTestBtn");
  // The step in progress and its Next button sit at the top of Live.
  const card = page.locator("#guidedStepCard");
  const button = page.locator("#guidedNextBtn");
  const stepState = (phase: string) =>
    panel.locator(`[data-guided-step="${phase}"]`);
  await expect(panel).toContainText("Guided test drive (optional)");
  await expect(start).toHaveText("Start guided test");
  await expect(card).toBeHidden();

  await start.click();
  await expect(stepState("sweep")).toHaveAttribute(
    "data-step-state",
    "current",
  );
  await expect(panel).toContainText(
    "In top gear (or D), accelerate smoothly from about 50 to 120 km/h",
  );
  await expect(card).toContainText("Step 1 of 4 · Speed sweep");
  await expect(card).toContainText(
    "Top gear (or D): speed up smoothly from 50 to 120 km/h.",
  );
  await expect(start).toBeHidden();
  await expect(button).toHaveText("Next: Steady hold");

  await button.click();
  await expect(card).toContainText("Step 2 of 4 · Steady hold");
  await expect(button).toHaveText("Next: Neutral coast-down");

  // A reload mid-run picks the guided test up where the driver left it.
  await page.reload();
  await expect(stepState("sweep")).toHaveAttribute("data-step-state", "done");
  await expect(stepState("hold")).toHaveAttribute("data-step-state", "current");
  await expect(button).toHaveText("Next: Neutral coast-down");

  await button.click();
  await expect(panel).toContainText("shift to neutral");
  await expect(button).toHaveText("Next: Firm stops");

  await button.click();
  await expect(panel).toContainText("brake firmly from about 80 to 20 km/h");
  await expect(panel).toContainText("no traffic behind you");
  await expect(card).toContainText(
    "Where safe: brake firmly from 80 to 20 km/h, 3 times.",
  );
  await expect(card).toContainText("0 of 3 firm stops counted");
  // The server counts each firm stop as it happens.
  status = { ...status, guided_brake_stops: 3 };
  await expect(card).toContainText(
    "3 of 3 firm stops counted. You can finish the guided test.",
  );
  await expect(button).toHaveText("Finish guided test");

  await button.click();
  await expect(panel).toContainText("Guided test done.");
  await expect(card).toBeHidden();
  await expect(start).toBeHidden();
  expect(marked).toEqual(["sweep", "hold", "coast_down", "brake", null]);

  // ...and still knows the guided test is done after another reload.
  await page.reload();
  await expect(panel).toContainText("Guided test done.");
  for (const phase of ["sweep", "hold", "coast_down", "brake"]) {
    await expect(stepState(phase)).toHaveAttribute("data-step-state", "done");
  }
  await expect(card).toBeHidden();
  await expect(start).toBeHidden();

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

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("journey: a blank first open shows only the setup steps and a pinned next step", async ({
    page,
  }) => {
    const blank = buildCaptureReadiness({
      isReady: false,
      sensors: { state: "fail", reasonKey: "no_live_sensors" },
      reference: { state: "fail", reasonKey: "active_car_missing" },
      speed: { state: "warn", reasonKey: "speed_sample_missing" },
    });
    await installCommonRoutes(page, {
      settingsHandler: async (route) => {
        if (requestPath(route).startsWith("/api/settings/cars")) {
          await fulfillJson<CarsPayload>(route, {
            cars: [],
            active_car_id: null,
          });
          return;
        }
        await fulfillJson(route, {});
      },
    });
    await page.route("**/api/recording/status", (route) =>
      fulfillJson(route, idleStatus({ capture_readiness: blank })),
    );
    await bootLiveDashboard(page, {
      installRoutes: false,
      fakeWebSocket: { payload: { clients: [], spectra: { clients: {} } } },
    });

    const steps = page.locator("#liveSetup [data-setup-step]");
    await expect(steps).toHaveCount(3);
    await expect(steps.nth(0)).toHaveAttribute("data-step-state", "current");
    await expect(steps.nth(1)).toContainText("Checked once a car is selected.");
    // No signal yet: no empty overview tiles or spectrum placeholder.
    await expect(page.locator(".dashboard-grid__overview")).toBeHidden();
    await expect(page.locator(".dashboard-grid__main")).toBeHidden();
    // The next step is pinned to the bottom of the screen; the header keeps the pills.
    const bar = page.locator("#liveActionBar");
    await expect(bar).toContainText("Setup 1 of 3: Car");
    await expect(bar).toBeInViewport();
    const box = await bar.boundingBox();
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeCloseTo(844, 0);
    await expect(page.locator("#shellLiveStatus")).toBeVisible();
    await expect(page.locator("#speedUnitSelect")).toBeHidden();

    await bar.getByRole("button", { name: "Add a car" }).tap();
    await expect(page.locator("#addCarWizard")).toBeVisible();
  });

  test("journey: freshness and speed each fit one line of half a 360 px row, in Dutch", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await installCommonRoutes(page, {
      settingsHandler: async (route) => {
        if (requestPath(route) === "/api/settings/language") {
          await fulfillJson(route, { language: "nl" });
          return;
        }
        await activeCar(route);
      },
    });
    await page.route("**/api/recording/status", (route) =>
      fulfillJson(route, idleStatus()),
    );
    await bootLiveDashboard(page, {
      installRoutes: false,
      liveSensorPayload: {
        // The longest Dutch state, a four-digit age, a three-digit speed.
        clients: [{ ...sensor("front_left_wheel"), last_seen_age_ms: 1250 }],
        speedMps: 52.3,
      },
    });

    const freshness = page.locator("#liveDataFreshness");
    await expect(freshness.locator(".stat__value")).toHaveText("Verouderd");
    await expect(freshness.locator(".stat__detail")).toHaveText(
      "1.250 ms geleden",
    );
    const speed = page.locator("#speed");
    await expect(speed.locator(".stat__value")).toHaveText("188,3 km/u");
    await expect(speed.locator(".stat__detail")).toHaveText("GPS");
    for (const value of [
      freshness.locator(".stat__value"),
      speed.locator(".stat__value"),
    ]) {
      const lines = await value.evaluate(
        (element) =>
          element.getBoundingClientRect().height /
          Number.parseFloat(getComputedStyle(element).lineHeight),
      );
      expect(lines).toBeCloseTo(1, 0);
    }
    // Both labels fit one line too, so the two values sit side by side.
    const freshnessTop = (await freshness.locator(".stat__value").boundingBox())
      ?.y;
    const speedTop = (await speed.locator(".stat__value").boundingBox())?.y;
    expect(Math.abs((freshnessTop ?? 0) - (speedTop ?? 99))).toBeLessThan(4);
  });

  test("journey: after a run, a greyed-out Start says GPS is still waiting for a fix", async ({
    page,
  }) => {
    const waitingForGps = {
      ...buildCaptureReadiness({
        isReady: false,
        sensors: {
          state: "warn",
          reasonKey: "limited_sensor_coverage",
          details: { live_sensor_count: 1 },
        },
        reference: {
          state: "fail",
          reasonKey: "speed_source_fallback_active",
        },
        speed: { state: "warn", reasonKey: "speed_sample_missing" },
      }),
      capabilities: {
        wheel: "manual_speed",
        driveline: "manual_speed",
        engine: "manual_speed",
      },
    } satisfies LoggingStatusPayload["capture_readiness"];
    await installCommonRoutes(page, {
      settingsHandler: async (route) => {
        const path = requestPath(route);
        if (path === "/api/settings/speed-source/status") {
          await fulfillJson<SpeedSourceStatusPayload>(route, {
            connection_state: "connected",
            device: "/dev/ttyACM0",
            fix_wait_s: 42.4,
            effective_speed_kmh: 50,
            epv_m: null,
            epx_m: null,
            epy_m: null,
            fallback_active: true,
            fix_dimension: "none",
            fix_mode: 1,
            gps_enabled: true,
            last_error: null,
            last_update_age_s: null,
            raw_speed_kmh: null,
            reconnect_delay_s: null,
            speed_confidence: "low",
            speed_source: "fallback_manual",
            stale_timeout_s: 10,
          });
          return;
        }
        if (path === "/api/settings/speed-source") {
          await fulfillJson<SpeedSourcePayload>(route, {
            speed_source: "gps",
            manual_speed_kph: 50,
            stale_timeout_s: 10,
          });
          return;
        }
        await activeCar(route);
      },
    });
    await page.route("**/api/recording/status", (route) =>
      fulfillJson(
        route,
        idleStatus({
          last_completed_run_id: "run-1",
          capture_readiness: waitingForGps,
        }),
      ),
    );
    await bootLiveDashboard(page, {
      installRoutes: false,
      liveSensorPayload: { clients: [sensor("front_left_wheel")] },
    });

    await expect(page.locator("#loggingSummary")).toContainText(
      "Your run is ready in History.",
    );
    await expect(page.locator("#startLoggingBtn")).toBeDisabled();
    const reason = page.locator("#startBlockedReason");
    await expect(reason).toContainText("Start is not available yet.");
    await expect(reason).toContainText(
      "GPS receiver found, waiting for a fix (42 s).",
    );
    await expect(page.locator("#captureManualSpeedNote")).toContainText(
      "Start waits for live speed",
    );
  });

  test("journey: a solo drive keeps the screen on, flags a quiet sensor, and says why the run stopped", async ({
    page,
  }) => {
    let status = idleStatus();
    await bootWithStatus(page, (route) => fulfillJson(route, status));
    await page.route("**/api/recording/start", async (route) => {
      status = idleStatus({ enabled: true, run_id: "run-7", elapsed_s: 3 });
      await fulfillJson(route, status);
    });
    const keepAwakeVideo = page.locator("#keepAwakeVideo");
    const isPlaying = () =>
      keepAwakeVideo.evaluate((video: HTMLVideoElement) => !video.paused);

    await expect(page.locator("#keepAwakeHint")).toBeHidden();
    await page.locator("#startLoggingBtn").tap();
    await expect(page.locator("#stopLoggingBtn")).toBeInViewport();
    await expect(page.locator("#liveActionBar")).toHaveAttribute(
      "data-state",
      "recording",
    );
    // Recording is plain at the top too, in the header pill.
    await expect(page.locator("#shellRecordingPill")).toContainText(
      "Recording",
    );
    // The Start tap starts the muted keep-awake video, and Live says to keep
    // the screen on in one line; "How?" says to set auto-lock to Never.
    await expect.poll(isPlaying).toBe(true);
    await expect(keepAwakeVideo).toHaveJSProperty("muted", true);
    const hint = page.locator("#keepAwakeHint");
    const summary = hint.locator("summary");
    await expect(summary).toHaveText(
      "Keep the screen on while you drive. How?",
    );
    await expect(hint).toBeInViewport();
    const line = await summary.evaluate(
      (element) =>
        Number.parseFloat(getComputedStyle(element).lineHeight) * 1.5,
    );
    expect((await summary.boundingBox())?.height ?? 0).toBeLessThan(line);
    await expect(hint.getByText("Auto-Lock")).toBeHidden();
    await summary.tap();
    await expect(hint.getByText("Auto-Lock")).toBeVisible();
    await expect(page.locator("#stopLoggingBtn")).toBeInViewport();

    // The overview pairs its short stats on a phone; the car takes a full row.
    const box = async (selector: string) =>
      (await page.locator(selector).boundingBox()) ?? {
        x: 0,
        y: -1,
        width: 0,
        height: 0,
      };
    const sensors = await box("#liveConnectedSensors");
    const runState = await box("#liveRecordingState");
    const car = await box("#liveActiveCar");
    expect(runState.y).toBe(sensors.y);
    expect(runState.x).toBeGreaterThan(sensors.x + sensors.width);
    expect(car.y).toBeGreaterThan(sensors.y);
    expect(car.width).toBeGreaterThan(sensors.width * 1.8);

    // The sensor goes quiet: a warning at the top, with the time left before the stop.
    status = idleStatus({
      enabled: true,
      run_id: "run-7",
      elapsed_s: 40,
      no_data_s: 20.2,
    });
    const silent = page.locator("#sensorSilentNotice");
    await expect(silent).toContainText("No data from the sensor");
    await expect(silent).toContainText("within 40 s");
    await expect(silent).toBeInViewport();

    // It never came back: the run stopped by itself, and Live says why.
    status = idleStatus({
      last_stop_reason: "no_data_timeout",
      last_run_id: "run-7",
      analysis_in_progress: true,
    });
    const stopped = page.locator("#autoStopNotice");
    await expect(stopped).toContainText("Recording stopped: sensor lost");
    await expect(stopped).toContainText("battery");
    await expect(stopped).toBeInViewport();
    await expect(silent).toBeHidden();
    await expect(hint).toBeHidden();
    await expect.poll(isPlaying).toBe(false);
  });

  test("journey: a solo driver reads the guided steps while parked, follows the current step at the top, and Stop asks first", async ({
    page,
  }) => {
    let status = idleStatus();
    await bootWithStatus(page, (route) => fulfillJson(route, status));
    await page.route("**/api/recording/start", async (route) => {
      status = idleStatus({ enabled: true, run_id: "run-9", elapsed_s: 2 });
      await fulfillJson(route, status);
    });
    await page.route("**/api/recording/guided-phase", async (route) => {
      const phase = (route.request().postDataJSON() as { phase: string })
        .phase as LoggingStatusPayload["guided_phase"];
      status = { ...status, guided_phase: phase };
      await fulfillJson(route, status);
    });
    let stops = 0;
    await page.route("**/api/recording/stop", async (route) => {
      stops += 1;
      status = idleStatus({ last_run_id: "run-9" });
      await fulfillJson(route, status);
    });

    // Parked: the steps can be read before setting off.
    const preview = page.locator("#guidedPreview");
    await preview.locator("summary").tap();
    await expect(preview).toContainText("Read them now, while parked.");
    await expect(preview).toContainText(
      "brake firmly from about 80 to 20 km/h",
    );

    await page.locator("#startLoggingBtn").tap();
    await expect(preview).toBeHidden();
    await page.locator("#guidedTestBtn").tap();

    // The current step stays at the top, however far down the page is scrolled.
    const card = page.locator("#guidedStepCard");
    await expect(card).toContainText("Step 1 of 4 · Speed sweep");
    const stop = page.locator("#stopLoggingBtn");
    await stop.scrollIntoViewIfNeeded();
    await expect(card).toBeInViewport();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(card).toBeInViewport();
    // Next and Stop are well apart.
    const next = await page.locator("#guidedNextBtn").boundingBox();
    const stopBox = await stop.boundingBox();
    expect(next && stopBox).toBeTruthy();
    if (next && stopBox) {
      const gap = Math.max(
        stopBox.y - (next.y + next.height),
        next.y - (stopBox.y + stopBox.height),
      );
      expect(gap).toBeGreaterThanOrEqual(48);
    }

    // A Stop tap mid-step asks first; Cancel keeps recording.
    const dialog = page.getByRole("alertdialog");
    await stop.tap();
    await expect(dialog).toContainText(
      "The guided test is on Step 1 of 4: Speed sweep.",
    );
    await dialog.getByRole("button", { name: "Cancel" }).tap();
    await expect(dialog).toBeHidden();
    await expect(stop).toBeVisible();
    expect(stops).toBe(0);

    await stop.tap();
    await dialog.getByRole("button", { name: "Confirm" }).tap();
    await expect(page.locator("#startLoggingBtn")).toBeVisible();
    await expect(card).toBeHidden();
    expect(stops).toBe(1);
  });
});
