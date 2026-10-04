import { describe, expect, test } from "vitest";

import type { LoggingStatusPayload } from "../src/api/types";
import {
  classifyFreshness,
  formatElapsed,
  freshnessText,
  guidedTestModel,
  IDLE_STATUS,
  isIdle,
  type LiveHealth,
  liveHealth,
  type RecordingInputs,
  recordingModel,
  runsAffected,
  speedText,
  strongestSensor,
  withLoggingError,
} from "../src/pages/dashboard/dashboard_model";
import {
  checklist,
  checkDetail,
  type Readiness,
} from "../src/pages/dashboard/readiness";
import { setLanguage, t as activeT } from "../src/i18n";
import type { AdaptedClient } from "../src/transport/live_models";

const t = (key: string, vars?: Record<string, unknown>) =>
  vars && Object.keys(vars).length ? `${key}:${JSON.stringify(vars)}` : key;
const formatInt = (value: number) => String(value);

function client(overrides: Partial<AdaptedClient> = {}): AdaptedClient {
  return {
    id: "a",
    name: "Front Left",
    connected: true,
    mac_address: "a",
    location_code: "front_left_wheel",
    last_seen_age_ms: 10,
    dropped_frames: 0,
    frame_loss_recent: false,
    frames_total: 1,
    frame_samples: 200,
    sample_rate_hz: 400,
    firmware_version: null,
    ...overrides,
  } as AdaptedClient;
}

function status(
  overrides: Partial<LoggingStatusPayload> = {},
): LoggingStatusPayload {
  return { ...IDLE_STATUS, ...overrides };
}

function readiness(
  isReady: boolean,
  checks: Array<
    [string, "pass" | "warn" | "fail", string, Record<string, number>?]
  >,
): Readiness {
  return {
    is_ready: isReady,
    checks: checks.map(([check_key, state, reason_key, details]) => ({
      check_key,
      state,
      reason_key,
      details: details ?? {},
    })),
  };
}

const NOT_READY = readiness(false, [
  ["sensors_ready", "pass", "ready", { live_sensor_count: 4 }],
  ["reference_ready", "fail", "speed_source_missing"],
  ["speed_stable", "fail", "speed_sample_missing"],
  ["capture_ready", "fail", "capture_blocked"],
]);

const OK_HEALTH: LiveHealth = {
  variant: "ok",
  text: "ok",
  summary: "",
  showOverviewPill: false,
};

function recording(overrides: Partial<RecordingInputs> = {}) {
  return recordingModel(
    {
      status: status(),
      pending: null,
      carBlock: null,
      health: OK_HEALTH,
      speedUnit: "kmh",
      connectedText: "1",
      assignedText: "1",
      elapsedText: "0:30",
      lastRunElapsedText: "1:05",
      ...overrides,
    },
    t,
    formatInt,
  );
}

describe("recording card", () => {
  test("without cars the setup layout offers to add one", () => {
    const model = recording({
      carBlock: "no_cars",
      status: status({ capture_readiness: NOT_READY }),
    });
    expect(model.setupMode).toBe(true);
    expect(model.phaseText).toBe("dashboard.recording_phase.blocked");
    expect(model.summaryPanel?.action).toEqual({
      action: "open-add-car",
      label: "dashboard.logging.blocked.no_cars.action",
      variant: "success",
    });
    expect(model.startDisabled).toBe(true);
  });

  test("an inactive car points at the car list", () => {
    expect(
      recording({ carBlock: "no_active" }).summaryPanel?.action?.action,
    ).toBe("open-cars");
  });

  test("failing readiness shows the first failing check with its fix and a checklist of open items", () => {
    const model = recording({
      status: status({ capture_readiness: NOT_READY }),
    });
    expect(model.setupMode).toBe(true);
    expect(model.phaseText).toBe("dashboard.recording_phase.preparing");
    expect(model.summaryPanel).toEqual({
      title: "dashboard.logging.blocked.setup.title",
      body: "dashboard.capture_readiness.reference_ready.speed_source_missing",
      detail: null,
      action: {
        action: "open-speed-source",
        label: "dashboard.logging.blocked.setup.action.speed_source",
        variant: "primary",
      },
    });
    expect(model.checklist?.map((item) => item.checkKey)).toEqual([
      "reference_ready",
      "speed_stable",
    ]);
    expect(model.startDisabled).toBe(true);
  });

  test("a missing active car points at the car settings", () => {
    const model = recording({
      status: status({
        capture_readiness: readiness(false, [
          ["sensors_ready", "pass", "ready"],
          ["reference_ready", "fail", "active_car_missing"],
        ]),
      }),
    });
    expect(model.summaryPanel?.action?.action).toBe("open-cars");
  });

  test("ready to record enables Start and lists every check", () => {
    const ready = readiness(true, [
      [
        "sensors_ready",
        "warn",
        "limited_sensor_coverage",
        { live_sensor_count: 1 },
      ],
      ["reference_ready", "pass", "ready"],
      ["speed_stable", "pass", "ready"],
      ["capture_ready", "pass", "ready_with_warnings"],
    ]);
    const model = recording({ status: status({ capture_readiness: ready }) });
    expect(model.startDisabled).toBe(false);
    expect(model.setupMode).toBe(false);
    expect(model.summaryText).toBe(
      'dashboard.capture_readiness.sensors_ready.limited_sensor_coverage:{"count":"1"}',
    );
    expect(model.checklist).toHaveLength(3);
  });

  test("recording shows elapsed time, the run id and an enabled Stop", () => {
    const model = recording({
      status: status({ enabled: true, run_id: "run-1", samples_written: 24 }),
    });
    expect(model).toMatchObject({
      phaseText: "dashboard.recording_phase.recording",
      elapsedText: "0:30",
      samplesText: "24",
      runIdText: 'dashboard.logging.run_id:{"runId":"run-1"}',
      showStop: true,
      stopDisabled: false,
      showPill: false,
    });
  });

  test("a write error during recording shows in the pill", () => {
    const model = recording({
      status: status({ enabled: true, write_error: "disk full" }),
    });
    expect(model).toMatchObject({
      pillVariant: "bad",
      pillText: "disk full",
      showPill: true,
    });
  });

  test("processing and saved runs keep the finished run's elapsed time and link to History", () => {
    const processing = recording({
      status: status({
        analysis_in_progress: true,
        last_completed_run_id: "run-1",
      }),
    });
    expect(processing.phaseText).toBe("dashboard.recording_phase.processing");
    expect(processing.elapsedText).toBe("1:05");
    expect(processing.summaryPanel?.action?.action).toBe("open-history");
    const saved = recording({
      status: status({ last_completed_run_id: "run-1" }),
    });
    expect(saved.phaseText).toBe("dashboard.recording_phase.saved");
    expect(saved.elapsedText).toBe("1:05");
  });

  test("a run that hit the 30-minute limit says it stopped automatically", () => {
    const detail = (reason: LoggingStatusPayload["last_stop_reason"]) =>
      recording({
        status: status({
          last_completed_run_id: "run-1",
          last_stop_reason: reason,
        }),
      }).summaryPanel?.detail;
    expect(detail("max_duration")).toBe(
      "dashboard.logging.auto_stopped_max_duration",
    );
    expect(detail("manual")).toBe("dashboard.logging.saved.detail");
  });

  test("pending start and stop disable both buttons", () => {
    expect(recording({ pending: "starting" })).toMatchObject({
      phaseText: "dashboard.recording_phase.starting",
      startDisabled: true,
      showStop: false,
    });
    expect(
      recording({ pending: "stopping", status: status({ enabled: true }) }),
    ).toMatchObject({
      phaseText: "dashboard.recording_phase.stopping",
      showStop: true,
      stopDisabled: true,
    });
  });

  test("errors replace the summary; an unreadable status blanks the card", () => {
    const base = recording({
      status: status({ last_completed_run_id: "run-1" }),
    });
    expect(
      withLoggingError(base, { kind: "error", message: "boom" }, t),
    ).toMatchObject({
      pillText: "boom",
      summaryText: "boom",
      summaryPanel: null,
      phaseText: "dashboard.recording_phase.saved",
    });
    expect(
      withLoggingError(base, { kind: "unavailable", message: "" }, t),
    ).toMatchObject({
      phaseText: "status.unavailable",
      samplesText: "--",
      startDisabled: true,
      showStop: false,
    });
  });
});

describe("run health", () => {
  const locationOf = (c: AdaptedClient) => c.location_code ?? "";
  const health = (
    clients: AdaptedClient[],
    overrides: Partial<LoggingStatusPayload> = {},
    carActive = true,
  ) =>
    liveHealth(
      {
        clients,
        locationOf,
        status: status(overrides),
        carActive,
        speedUnit: "kmh",
      },
      t,
      formatInt,
    );

  test("reports the most important problem first", () => {
    expect(health([client()], { write_error: "disk" }).variant).toBe("bad");
    expect(health([]).text).toBe("dashboard.health.no_signal");
    expect(health([client()], {}, false).summary).toBe(
      "dashboard.logging.active_car_required",
    );
    expect(health([client({ frame_loss_recent: true })]).summary).toBe(
      'dashboard.logging.frame_loss:{"count":"1"}',
    );
    // Old loss (the never-resetting total) alone no longer needs attention.
    expect(health([client({ dropped_frames: 2 })]).summary).not.toContain(
      "frame_loss",
    );
    expect(health([client({ location_code: "" })]).summary).toBe(
      'dashboard.logging.unassigned:{"count":"1"}',
    );
    expect(
      health([client(), client({ id: "b", connected: false })]).summary,
    ).toBe('dashboard.logging.offline:{"count":"1"}');
  });

  test("is ok while recording or ready, and hides the overview pill then", () => {
    expect(health([client()], { enabled: true })).toMatchObject({
      text: "dashboard.health.recording",
      showOverviewPill: false,
    });
    expect(health([client()])).toMatchObject({
      text: "dashboard.health.ready",
      showOverviewPill: false,
    });
    expect(health([client()], { capture_readiness: NOT_READY }).summary).toBe(
      "dashboard.capture_readiness.reference_ready.speed_source_missing",
    );
  });
});

describe("live overview helpers", () => {
  test("freshness is relative to the slowest sensor's frame cadence", () => {
    const clients = [{ sample_rate_hz: 400, frame_samples: 200 }];
    expect(classifyFreshness(503, clients)).toBe("fresh");
    expect(classifyFreshness(625, clients)).toBe("fresh");
    expect(classifyFreshness(900, clients)).toBe("delayed");
    expect(classifyFreshness(1300, clients)).toBe("stale");
  });

  test("freshness says when only sensors stream without a speed reference", () => {
    expect(freshnessText([], null, t, formatInt)).toBe(
      "dashboard.data_freshness_none",
    );
    expect(freshnessText([client()], NOT_READY, t, formatInt)).toBe(
      "dashboard.data_freshness_sensors_only",
    );
    expect(
      freshnessText([client({ last_seen_age_ms: 20 })], null, t, formatInt),
    ).toBe(
      'dashboard.data_freshness_fresh:{"age":"status.age_ms_ago:{\\"value\\":\\"20\\"}"}',
    );
  });

  test("the strongest sensor is the loudest connected one", () => {
    const spectra = {
      clients: {
        a: { strength_metrics: { vibration_strength_db: 10 } },
        b: { strength_metrics: { vibration_strength_db: 20 } },
        c: { strength_metrics: { vibration_strength_db: 30 } },
      },
    } as never;
    const result = strongestSensor(
      [client(), client({ id: "b" }), client({ id: "c", connected: false })],
      spectra,
    );
    expect(result?.client.id).toBe("b");
    expect(strongestSensor([client()], { clients: {} })).toBeNull();
  });

  test("elapsed time formats minutes and hours", () => {
    const start = "2026-01-01T00:00:00Z";
    const at = (seconds: number) => Date.parse(start) + seconds * 1000;
    expect(formatElapsed(start, at(65))).toBe("1:05");
    expect(formatElapsed(start, at(3725))).toBe("1:02:05");
    expect(formatElapsed(null, at(1))).toBe("--");
  });

  test("speed shows in the chosen unit, or a placeholder without a reading", () => {
    const fmt = (value: number, digits: number) => value.toFixed(digits);
    expect(speedText(10, "kmh", "speed.label", t, fmt)).toBe(
      'speed.label:{"unit":"speed.unit.kmh","value":"36.0"}',
    );
    expect(speedText(10, "mps", "speed.label", t, fmt)).toBe(
      'speed.label:{"unit":"speed.unit.mps","value":"10.0"}',
    );
    expect(speedText(null, "kmh", "speed.label", t, fmt)).toBe(
      'speed.none:{"unit":"speed.unit.kmh"}',
    );
  });

  test("History reloads only when a run starts, stops, or finishes", () => {
    expect(runsAffected(status(), status({ samples_written: 9 }))).toBe(false);
    expect(runsAffected(status(), status({ enabled: true }))).toBe(true);
    expect(runsAffected(status(), status({ last_completed_run_id: "r" }))).toBe(
      true,
    );
    expect(isIdle(status({ last_completed_run_id: "r" }))).toBe(false);
  });
});

describe("readiness text", () => {
  test("fills in counts and unknown reasons read as ready", () => {
    const [stabilizing, unknown, other] = readiness(false, [
      ["speed_stable", "fail", "speed_stabilizing", { dwell_remaining_s: 2.2 }],
      ["sensors_ready", "fail", "something_new", { live_sensor_count: 3 }],
      ["new_check", "fail", "capture_blocked"],
    ]).checks;
    expect(checkDetail(stabilizing, t, formatInt, "kmh")).toBe(
      'dashboard.capture_readiness.speed_stable.speed_stabilizing:{"seconds":"3"}',
    );
    expect(checkDetail(unknown, t, formatInt, "kmh")).toBe(
      'dashboard.capture_readiness.sensors_ready.ready:{"count":"3"}',
    );
    expect(checkDetail(other, t, formatInt, "kmh")).toBe(
      "dashboard.capture_readiness.capture_ready.capture_blocked",
    );
  });

  test("names the minimum cruise speed in the speed unit", () => {
    const [tooLow] = readiness(false, [
      ["speed_stable", "fail", "speed_too_low", { minimum_speed_kmh: 30 }],
    ]).checks;
    expect(checkDetail(tooLow, t, formatInt, "kmh")).toBe(
      'dashboard.capture_readiness.speed_stable.speed_too_low:{"minimumSpeed":"30 speed.unit.kmh"}',
    );
    expect(checkDetail(tooLow, t, formatInt, "mps")).toBe(
      'dashboard.capture_readiness.speed_stable.speed_too_low:{"minimumSpeed":"8 speed.unit.mps"}',
    );
  });

  test("the setup checklist lists only checks that are not passing", () => {
    expect(
      checklist(NOT_READY, true, t, formatInt, "kmh").map(
        (item) => item.checkKey,
      ),
    ).toEqual(["reference_ready", "speed_stable"]);
    expect(checklist(null, false, t, formatInt, "kmh")).toEqual([]);
  });
});

describe("guidedTestModel", () => {
  const recordingRun: LoggingStatusPayload = {
    ...IDLE_STATUS,
    enabled: true,
    run_id: "run-1",
  };
  const states = (model: ReturnType<typeof guidedTestModel>) =>
    model.steps.map((step) => step.state);

  test("only shows while a run records", () => {
    expect(guidedTestModel(IDLE_STATUS, "kmh", false, t).visible).toBe(false);
    expect(guidedTestModel(recordingRun, "kmh", false, t).visible).toBe(true);
  });

  test("offers to start with the sweep before any step", () => {
    const model = guidedTestModel(recordingRun, "kmh", false, t);

    expect(states(model)).toEqual(["todo", "todo", "todo"]);
    expect(model.action).toEqual({
      label: "dashboard.guided.start",
      phase: "sweep",
    });
    expect(model.finished).toBe(false);
  });

  test("walks sweep, hold, then the neutral coast-down, then finishes", () => {
    const hold = guidedTestModel(
      {
        ...recordingRun,
        guided_phase: "hold",
        guided_phases_completed: ["sweep"],
      },
      "kmh",
      false,
      t,
    );
    expect(states(hold)).toEqual(["done", "current", "todo"]);
    expect(hold.action).toEqual({
      label:
        'dashboard.guided.next:{"step":"dashboard.guided.coast_down.title"}',
      phase: "coast_down",
    });

    const coast = guidedTestModel(
      {
        ...recordingRun,
        guided_phase: "coast_down",
        guided_phases_completed: ["sweep", "hold"],
      },
      "kmh",
      false,
      t,
    );
    expect(states(coast)).toEqual(["done", "done", "current"]);
    expect(coast.action).toEqual({
      label: "dashboard.guided.finish",
      phase: null,
    });
  });

  test("restores a finished guided test from the server's completed steps", () => {
    const model = guidedTestModel(
      {
        ...recordingRun,
        guided_phases_completed: ["sweep", "hold", "coast_down"],
      },
      "kmh",
      false,
      t,
    );

    expect(model.finished).toBe(true);
    expect(states(model)).toEqual(["done", "done", "done"]);
    expect(model.action).toBeNull();
  });

  test("a new run without completed steps starts over", () => {
    const model = guidedTestModel(
      { ...recordingRun, run_id: "run-2", guided_phases_completed: [] },
      "kmh",
      false,
      t,
    );

    expect(model.finished).toBe(false);
    expect(model.action?.phase).toBe("sweep");
  });

  test("disables the button while a request is in flight", () => {
    expect(guidedTestModel(recordingRun, "kmh", true, t).disabled).toBe(true);
  });

  test.each([
    {
      language: "en",
      unit: "kmh",
      sweep: "from about 50 to 120 km/h,",
      coast: "about 30 km/h slower",
    },
    {
      language: "en",
      unit: "mps",
      sweep: "from about 14 to 33 m/s,",
      coast: "about 8 m/s slower",
    },
    {
      language: "nl",
      unit: "kmh",
      sweep: "van ongeveer 50 naar 120 km/u,",
      coast: "ongeveer 30 km/u langzamer",
    },
    {
      language: "nl",
      unit: "mps",
      sweep: "van ongeveer 14 naar 33 m/s,",
      coast: "ongeveer 8 m/s langzamer",
    },
  ] as const)(
    "names step speeds in the speed unit ($language, $unit)",
    async ({ language, unit, sweep, coast }) => {
      await setLanguage(language);
      try {
        const model = guidedTestModel(recordingRun, unit, false, activeT);
        const [sweepStep, holdStep, coastStep] = model.steps;
        expect(sweepStep.instruction).toContain(sweep);
        expect(coastStep.instruction).toContain(coast);
        for (const step of model.steps) {
          expect(step.instruction).not.toMatch(/\{\w+\}/);
        }
        expect(holdStep.instruction).not.toMatch(/km\/h|km\/u|m\/s/);
      } finally {
        await setLanguage("en");
      }
    },
  );
});
