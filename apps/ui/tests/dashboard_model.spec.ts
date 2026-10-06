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
  capabilityModel,
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
    firmware_status: "unknown",
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
  ["speed_stable", "warn", "speed_sample_missing"],
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
      gpsReceiverMissing: false,
      gpsFixWaitS: null,
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
    expect(
      model.checklist?.map((item) => [item.checkKey, item.stateText]),
    ).toEqual([
      ["reference_ready", "dashboard.capture_readiness.state.fail"],
      ["speed_stable", "dashboard.capture_readiness.state.advice"],
    ]);
    expect(model.startDisabled).toBe(true);
  });

  test("a missing live speed with GPS but no receiver names the receiver", () => {
    const detail = (gpsReceiverMissing: boolean) =>
      recording({
        status: status({ capture_readiness: NOT_READY }),
        gpsReceiverMissing,
      }).summaryPanel?.detail;
    expect(detail(true)).toBe(
      "speed.gps_no_receiver.title: speed.gps_no_receiver.body",
    );
    expect(detail(false)).toBeNull();
  });

  test("a receiver still waiting for a fix says how long and where to put it", () => {
    const model = recording({
      status: status({ capture_readiness: NOT_READY }),
      gpsFixWaitS: 47.6,
    });
    expect(model.summaryPanel?.detail).toBe(
      'speed.gps_waiting_fix:{"seconds":"47"}',
    );
  });

  test("after a finished run a greyed-out Start still says why", () => {
    const saved = recording({
      status: status({
        last_completed_run_id: "run-1",
        capture_readiness: NOT_READY,
      }),
      gpsFixWaitS: 12,
    });
    expect(saved.summaryPanel?.title).toBe("dashboard.logging.saved.title");
    expect(saved.startDisabled).toBe(true);
    expect(saved.blockedReason).toBe(
      `dashboard.logging.start_blocked:${JSON.stringify({
        reason:
          "dashboard.capture_readiness.reference_ready.speed_source_missing " +
          'speed.gps_waiting_fix:{"seconds":"12"}',
      })}`,
    );
    const ready = recording({
      status: status({
        last_completed_run_id: "run-1",
        capture_readiness: readiness(true, [
          ["sensors_ready", "pass", "ready"],
        ]),
      }),
    });
    expect(ready.blockedReason).toBeNull();
    expect(ready.startDisabled).toBe(false);
  });

  test("a parked car can start: unsteady speed is only advice", () => {
    const parked = readiness(true, [
      ["sensors_ready", "pass", "ready", { live_sensor_count: 4 }],
      ["reference_ready", "pass", "ready"],
      ["speed_stable", "warn", "speed_too_low", { minimum_speed_kmh: 30 }],
      ["capture_ready", "pass", "ready_with_warnings"],
    ]);
    const model = recording({ status: status({ capture_readiness: parked }) });
    expect(model.startDisabled).toBe(false);
    expect(model.setupMode).toBe(false);
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
      'dashboard.capture_readiness.sensors_ready.limited_sensor_coverage:{"count":1}',
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

  test("the first run after a server restart keeps its name and samples while analysed", () => {
    // The stop response clears run_id and nothing has completed yet.
    const stopped = recording({
      status: status({
        analysis_in_progress: true,
        last_run_id: "run-7",
        samples_written: 4800,
      }),
    });
    expect(stopped.summaryPanel?.title).toBe(
      "dashboard.logging.processing.title",
    );
    expect(stopped.runIdText).toBe(
      'dashboard.logging.last_run_id:{"runId":"run-7"}',
    );
    expect(stopped.samplesText).toBe("4800");
    // An analysis the server resumed after a restart: no counts describe that run.
    const resumed = recording({
      status: status({ analysis_in_progress: true, samples_written: 0 }),
    });
    expect(resumed.samplesText).toBe("--");
    expect(resumed.runIdText).toBe("");
    expect(JSON.stringify(resumed)).not.toContain("status.unavailable");
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
      'dashboard.logging.frame_loss:{"count":1}',
    );
    // Old loss (the never-resetting total) alone no longer needs attention.
    expect(health([client({ dropped_frames: 2 })]).summary).not.toContain(
      "frame_loss",
    );
    expect(health([client({ location_code: "" })]).summary).toBe(
      'dashboard.logging.unassigned:{"count":1}',
    );
    expect(
      health([client(), client({ id: "b", connected: false })]).summary,
    ).toBe('dashboard.logging.offline:{"count":1}');
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

  test("elapsed time counts on from the server's monotonic elapsed time", () => {
    const receivedAt = 1_000_000;
    const at = (seconds: number) => receivedAt + seconds * 1000;
    expect(formatElapsed(60, receivedAt, at(5))).toBe("1:05");
    expect(formatElapsed(3720, receivedAt, at(5.9))).toBe("1:02:05");
    // A browser clock that steps back never counts down.
    expect(formatElapsed(10, receivedAt, at(-30))).toBe("0:10");
    expect(formatElapsed(null, receivedAt, at(1))).toBe("--");
  });

  test("speed shows in the chosen unit, or a placeholder without a reading", () => {
    const fmt = (value: number, digits: number) => value.toFixed(digits);
    expect(speedText(10, "kmh", "speed.label", t, fmt)).toBe(
      'speed.label:{"unit":"speed.unit.kmh","value":"36.0"}',
    );
    expect(
      speedText(10, "kmh", "speed.fallback", t, fmt, "No GPS receiver found"),
    ).toBe(
      'speed.fallback:{"unit":"speed.unit.kmh","value":"36.0","reason":"No GPS receiver found"}',
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
      'dashboard.capture_readiness.sensors_ready.ready:{"count":3}',
    );
    expect(checkDetail(other, t, formatInt, "kmh")).toBe(
      "dashboard.capture_readiness.capture_ready.capture_blocked",
    );
  });

  test("frame loss names the lost share: a block above 2 %, a warning below", () => {
    const [high, low] = readiness(false, [
      ["sensors_ready", "fail", "frame_loss_high", { frame_loss_pct: 4.2 }],
      ["sensors_ready", "warn", "recent_frame_loss", { frame_loss_pct: 1 }],
    ]).checks;
    expect(checkDetail(high, t, formatInt, "kmh")).toBe(
      'dashboard.capture_readiness.sensors_ready.frame_loss_high:{"percent":"4.2"}',
    );
    expect(checkDetail(low, t, formatInt, "kmh")).toBe(
      'dashboard.capture_readiness.sensors_ready.recent_frame_loss:{"percent":"1.0"}',
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

describe("capability line", () => {
  const marks = (model: ReturnType<typeof capabilityModel>) =>
    model?.items.map((item) => [
      item.family,
      item.mark,
      item.note,
      item.fix?.target ?? null,
    ]);

  test("is absent without an active car", () => {
    expect(capabilityModel(null, null, "80 km/h", null, t)).toBeNull();
  });

  test("marks tested, estimated and untested families with their fix", () => {
    const model = capabilityModel(
      {
        wheel: "ok",
        driveline: "missing_final_drive",
        engine: "estimated_top_gear",
      },
      null,
      "80 km/h",
      null,
      t,
    );
    expect(marks(model)).toEqual([
      ["wheel", "ok", null, null],
      ["driveline", "no", "capabilities.driveline.missing_final_drive", "cars"],
      [
        "engine",
        "caveat",
        "capabilities.engine.estimated_top_gear",
        "speed_source",
      ],
    ]);
    expect(model?.manualNote).toBeNull();
    expect(
      marks(
        capabilityModel(
          { wheel: "ok", driveline: "ok", engine: "measured" },
          null,
          "80 km/h",
          null,
          t,
        ),
      )?.map(([, mark]) => mark),
    ).toEqual(["ok", "ok", "ok"]);
  });

  test("an EV's driveline is its motor and its engine is not applicable", () => {
    const model = capabilityModel(
      { wheel: "ok", driveline: "ok", engine: "not_applicable" },
      "EV",
      "80 km/h",
      null,
      t,
    );
    expect(
      model?.items.map((item) => [item.label, item.mark, item.note, item.fix]),
    ).toEqual([
      ["capabilities.family.wheel", "ok", null, null],
      ["capabilities.family.motor", "ok", null, null],
      [
        "capabilities.family.combustion_engine",
        "na",
        "capabilities.engine.not_applicable",
        null,
      ],
    ]);
    // A plug-in hybrid's estimate points to OBD-II, which shows when it ran.
    expect(
      capabilityModel(
        { wheel: "ok", driveline: "ok", engine: "hybrid_estimated" },
        "PHEV",
        "80 km/h",
        null,
        t,
      )?.items[2],
    ).toMatchObject({
      label: "capabilities.family.engine",
      mark: "caveat",
      fix: {
        target: "speed_source",
        label: "dashboard.capabilities.fix.engine.hybrid_estimated",
      },
    });
  });

  test("a typed-in speed tests nothing for sure and says so once", () => {
    const model = capabilityModel(
      {
        wheel: "manual_speed",
        driveline: "manual_speed",
        engine: "manual_speed",
      },
      null,
      "80 km/h",
      null,
      t,
    );
    expect(model?.items.map((item) => [item.mark, item.fix])).toEqual([
      ["no", null],
      ["no", null],
      ["no", null],
    ]);
    expect(model?.manualNote).toBe(
      'dashboard.capabilities.manual_note:{"speed":"80 km/h"}',
    );
    // GPS was chosen but has no receiver: say so instead of "speed is typed in".
    expect(
      capabilityModel(
        {
          wheel: "manual_speed",
          driveline: "manual_speed",
          engine: "manual_speed",
        },
        null,
        "80 km/h",
        "No GPS receiver found",
        t,
      )?.manualNote,
    ).toBe(
      'dashboard.capabilities.fallback_note:{"reason":"No GPS receiver found","speed":"80 km/h"}',
    );
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
    expect(guidedTestModel(IDLE_STATUS, "kmh", false, null, t).visible).toBe(
      false,
    );
    expect(guidedTestModel(recordingRun, "kmh", false, null, t).visible).toBe(
      true,
    );
  });

  test("offers to start with the sweep before any step", () => {
    const model = guidedTestModel(recordingRun, "kmh", false, null, t);

    expect(states(model)).toEqual(["todo", "todo", "todo", "todo"]);
    expect(model.action).toEqual({
      label: "dashboard.guided.start",
      phase: "sweep",
    });
    expect(model.finished).toBe(false);
  });

  test("walks sweep, hold, the neutral coast-down, then the firm stops, then finishes", () => {
    const hold = guidedTestModel(
      {
        ...recordingRun,
        guided_phase: "hold",
        guided_phases_completed: ["sweep"],
      },
      "kmh",
      false,
      null,
      t,
    );
    expect(states(hold)).toEqual(["done", "current", "todo", "todo"]);
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
      null,
      t,
    );
    expect(states(coast)).toEqual(["done", "done", "current", "todo"]);
    expect(coast.action).toEqual({
      label: 'dashboard.guided.next:{"step":"dashboard.guided.brake.title"}',
      phase: "brake",
    });

    const brake = guidedTestModel(
      {
        ...recordingRun,
        guided_phase: "brake",
        guided_phases_completed: ["sweep", "hold", "coast_down"],
      },
      "kmh",
      false,
      null,
      t,
    );
    expect(states(brake)).toEqual(["done", "done", "done", "current"]);
    expect(brake.action).toEqual({
      label: "dashboard.guided.finish",
      phase: null,
    });
  });

  test("counts the firm stops the brake step captured, live", () => {
    const progress = (stops: number, phase: "brake" | null = "brake") =>
      guidedTestModel(
        {
          ...recordingRun,
          guided_phase: phase,
          guided_phases_completed:
            phase === null
              ? ["sweep", "hold", "coast_down", "brake"]
              : ["sweep", "hold", "coast_down"],
          guided_brake_stops: stops,
        },
        "kmh",
        false,
        null,
        t,
      ).steps.map((step) => step.progress);

    expect(progress(0)).toEqual([
      null,
      null,
      null,
      'dashboard.guided.brake.progress:{"n":0,"total":3}',
    ]);
    expect(progress(2)[3]).toBe(
      'dashboard.guided.brake.progress:{"n":2,"total":3}',
    );
    // Enough stops: the step says so.
    expect(progress(3)[3]).toBe(
      'dashboard.guided.brake.progress_done:{"n":3,"total":3}',
    );
    // A finished test still shows what the brake step captured.
    expect(progress(1, null)[3]).toBe(
      'dashboard.guided.brake.progress:{"n":1,"total":3}',
    );
  });

  test("restores a finished guided test from the server's completed steps", () => {
    const model = guidedTestModel(
      {
        ...recordingRun,
        guided_phases_completed: ["sweep", "hold", "coast_down", "brake"],
      },
      "kmh",
      false,
      null,
      t,
    );

    expect(model.finished).toBe(true);
    expect(states(model)).toEqual(["done", "done", "done", "done"]);
    expect(model.action).toBeNull();
  });

  test("a new run without completed steps starts over", () => {
    const model = guidedTestModel(
      { ...recordingRun, run_id: "run-2", guided_phases_completed: [] },
      "kmh",
      false,
      null,
      t,
    );

    expect(model.finished).toBe(false);
    expect(model.action?.phase).toBe("sweep");
  });

  test("an EV skips the neutral coast-down and the top-gear advice", async () => {
    const model = guidedTestModel(
      {
        ...recordingRun,
        guided_phase: "hold",
        guided_phases_completed: ["sweep"],
      },
      "kmh",
      false,
      "EV",
      activeT,
    );
    expect(model.steps.map((step) => step.phase)).toEqual([
      "sweep",
      "hold",
      "brake",
    ]);
    expect(model.action).toEqual({
      label: "Next: Firm stops",
      phase: "brake",
    });
    expect(model.hint).toContain("no coast-down step");
    // Regenerative braking spares the discs: the stops must use them.
    expect(model.steps[2].instruction).toContain("regenerative braking");
    for (const step of model.steps) {
      expect(step.instruction).not.toMatch(/top gear|neutral|\{\w+\}/);
    }
    expect(
      guidedTestModel(
        {
          ...recordingRun,
          guided_phases_completed: ["sweep", "hold", "brake"],
        },
        "kmh",
        false,
        "EV",
        t,
      ).finished,
    ).toBe(true);
  });

  test("disables the button while a request is in flight", () => {
    expect(guidedTestModel(recordingRun, "kmh", true, null, t).disabled).toBe(
      true,
    );
  });

  test.each([
    {
      language: "en",
      unit: "kmh",
      sweep: "from about 50 to 120 km/h,",
      coast: "about 30 km/h slower",
      brake: "brake firmly from about 100 to 40 km/h,",
    },
    {
      language: "en",
      unit: "mps",
      sweep: "from about 14 to 33 m/s,",
      coast: "about 8 m/s slower",
      brake: "brake firmly from about 28 to 11 m/s,",
    },
    {
      language: "nl",
      unit: "kmh",
      sweep: "van ongeveer 50 naar 120 km/u,",
      coast: "ongeveer 30 km/u langzamer",
      brake: "stevig af van ongeveer 100 tot 40 km/u,",
    },
    {
      language: "nl",
      unit: "mps",
      sweep: "van ongeveer 14 naar 33 m/s,",
      coast: "ongeveer 8 m/s langzamer",
      brake: "stevig af van ongeveer 28 tot 11 m/s,",
    },
  ] as const)(
    "names step speeds in the speed unit ($language, $unit)",
    async ({ language, unit, sweep, coast, brake }) => {
      await setLanguage(language);
      try {
        const model = guidedTestModel(recordingRun, unit, false, null, activeT);
        const [sweepStep, holdStep, coastStep, brakeStep] = model.steps;
        expect(sweepStep.instruction).toContain(sweep);
        expect(coastStep.instruction).toContain(coast);
        expect(brakeStep.instruction).toContain(brake);
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
