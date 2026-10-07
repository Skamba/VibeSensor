import type { GuidedPhase, LoggingStatusPayload } from "../../api/types";
import type { FuelType } from "../../capabilities";
import type { CarSelectionState } from "../../car_selection";
import type { Feedback } from "../../components/feedback";
import {
  GUIDED_BRAKE_FROM_KMH,
  GUIDED_BRAKE_STOPS,
  GUIDED_BRAKE_TO_KMH,
  GUIDED_COAST_DROP_KMH,
  GUIDED_SWEEP_FROM_KMH,
  GUIDED_SWEEP_TO_KMH,
} from "../../config";
import { fmt, kmhInUnit, type SpeedUnit, speedUnitKey } from "../../format";
import type { KeepAwakeMode } from "../../keep_awake";
import type {
  AdaptedClient,
  SpectrumFrameData,
} from "../../transport/live_models";
import {
  checkDetail,
  type ChecklistItem,
  checklist,
  detailCount,
  findCheck,
  type Readiness,
  readinessSummary,
} from "./readiness";

/** Pure view models for the Live dashboard: overview, run health, recording. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;
type FormatInt = (value: number) => string;
export type Variant = "muted" | "ok" | "warn" | "bad";

export type PendingAction = "starting" | "stopping" | null;
export type LoggingError = { kind: "error" | "unavailable"; message: string };
export type SummaryAction =
  | "open-history"
  | "open-cars"
  | "open-add-car"
  | "open-sensors"
  | "open-speed-source";

export interface LiveHealth {
  variant: Variant;
  text: string;
  summary: string;
}

export interface SummaryPanel {
  title: string;
  body: string;
  detail: string | null;
  action: {
    action: SummaryAction;
    label: string;
    variant: "primary" | "success";
  } | null;
}

export interface RecordingModel {
  pillVariant: Variant;
  pillText: string;
  showPill: boolean;
  phaseText: string;
  summaryText: string;
  summaryPanel: SummaryPanel | null;
  runIdText: string;
  elapsedText: string;
  samplesText: string;
  checklist: ChecklistItem[] | null;
  /** Why Start is greyed out when the summary panel shows something else. */
  blockedReason: string | null;
  showStop: boolean;
  startDisabled: boolean;
  stopDisabled: boolean;
  setupMode: boolean;
}

export const IDLE_STATUS: LoggingStatusPayload = {
  enabled: false,
  run_id: null,
  write_error: null,
  analysis_in_progress: false,
  start_time_utc: null,
  samples_written: 0,
  samples_dropped: 0,
  last_completed_run_id: null,
  last_completed_run_error: null,
  guided_brake_stops: 0,
  capture_readiness: null,
  no_data_timeout_s: 60,
};

/**
 * "m:ss" or "h:mm:ss" a run has recorded: the server's monotonic `elapsedS`
 * when its status arrived (`receivedAtMs`), plus browser time since then.
 * Never `start_time_utc`: the Pi wall clock is wrong until it is set.
 */
export function formatElapsed(
  elapsedS: number | null | undefined,
  receivedAtMs: number,
  nowMs: number,
): string {
  if (elapsedS == null || !Number.isFinite(elapsedS)) {
    return "--";
  }
  const total = Math.max(
    0,
    Math.floor(elapsedS + Math.max(0, nowMs - receivedAtMs) / 1000),
  );
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`
    : `${minutes}:${seconds}`;
}

/** Changes in these fields add or finish a run, so History must reload. */
export function runsAffected(
  previous: LoggingStatusPayload,
  next: LoggingStatusPayload,
): boolean {
  return (
    previous.enabled !== next.enabled ||
    previous.run_id !== next.run_id ||
    previous.analysis_in_progress !== next.analysis_in_progress ||
    previous.last_completed_run_id !== next.last_completed_run_id ||
    previous.last_completed_run_error !== next.last_completed_run_error
  );
}

/** No run going and nothing just recorded: readiness is what matters. */
export function isIdle(status: LoggingStatusPayload): boolean {
  return (
    !status.enabled &&
    !status.analysis_in_progress &&
    !status.last_completed_run_id
  );
}

/** The one-line run health shown on the overview and the shell status pill. */
export function liveHealth(
  input: {
    clients: readonly AdaptedClient[];
    locationOf: (client: AdaptedClient) => string;
    status: LoggingStatusPayload;
    carActive: boolean;
    speedUnit: SpeedUnit;
  },
  t: Translate,
  formatInt: FormatInt,
): LiveHealth {
  const { clients, locationOf, status } = input;
  const attention = (summary: string): LiveHealth => ({
    variant: "warn",
    text: t("dashboard.health.attention"),
    summary,
  });
  if (status.write_error) {
    return {
      variant: "bad",
      text: t("dashboard.health.write_error"),
      summary: status.write_error,
    };
  }
  const connected = clients.filter((client) => client.connected);
  if (!connected.length) {
    return {
      variant: "muted",
      text: t("dashboard.health.no_signal"),
      summary: t("dashboard.logging.waiting"),
    };
  }
  if (!input.carActive) {
    return attention(t("dashboard.logging.active_car_required"));
  }
  // Only recent loss: the cumulative `dropped_frames` never resets, so a single
  // lost frame used to keep this chip on "Needs attention" until a restart.
  const dropping = connected.filter(
    (client) => client.frame_loss_recent,
  ).length;
  if (dropping > 0) {
    return attention(t("dashboard.logging.frame_loss", { count: dropping }));
  }
  const unassigned = connected.filter((client) => !locationOf(client)).length;
  if (unassigned > 0) {
    return attention(t("dashboard.logging.unassigned", { count: unassigned }));
  }
  const offline = clients.length - connected.length;
  if (offline > 0) {
    return attention(t("dashboard.logging.offline", { count: offline }));
  }
  if (status.enabled) {
    return {
      variant: "ok",
      text: t("dashboard.health.recording"),
      summary: t("dashboard.logging.running", {
        connected: formatInt(connected.length),
        assigned: formatInt(
          clients.filter((client) => locationOf(client)).length,
        ),
      }),
    };
  }
  const readiness = status.capture_readiness ?? null;
  if (readiness && !readiness.is_ready) {
    return attention(
      readinessSummary(readiness, t, formatInt, input.speedUnit),
    );
  }
  return {
    variant: "ok",
    text: t("dashboard.health.ready"),
    summary: "",
  };
}

const FRESH_MULTIPLIER = 1.25;
const DELAYED_MULTIPLIER = 2.5;

/** Fresh/delayed/stale relative to the slowest sensor's frame cadence. */
export function classifyFreshness(
  ageMs: number,
  clients: ReadonlyArray<
    Pick<AdaptedClient, "frame_samples" | "sample_rate_hz">
  >,
): "fresh" | "delayed" | "stale" {
  const cadenceMs = Math.max(
    0,
    ...clients.map(
      (client) => (client.frame_samples * 1000) / client.sample_rate_hz,
    ),
  );
  if (ageMs <= Math.ceil(cadenceMs * FRESH_MULTIPLIER)) {
    return "fresh";
  }
  return ageMs <= Math.ceil(cadenceMs * DELAYED_MULTIPLIER)
    ? "delayed"
    : "stale";
}

const SPEED_REFERENCE_PROBLEMS = new Set([
  "speed_source_missing",
  "speed_source_not_live",
  "speed_source_fallback_active",
  "speed_sample_missing",
  "speed_sample_stale",
]);

export function freshnessText(
  clients: readonly AdaptedClient[],
  readiness: Readiness | null,
  t: Translate,
  formatInt: FormatInt,
): string {
  const connected = clients.filter((client) => client.connected);
  const ages = connected
    .map((client) => client.last_seen_age_ms)
    .filter(
      (age): age is number => typeof age === "number" && Number.isFinite(age),
    );
  if (!ages.length) {
    return t("dashboard.data_freshness_none");
  }
  const reference = findCheck(readiness, "reference_ready");
  if (
    reference &&
    reference.state !== "pass" &&
    SPEED_REFERENCE_PROBLEMS.has(reference.reason_key ?? "")
  ) {
    return t("dashboard.data_freshness_sensors_only");
  }
  const ageMs = Math.max(...ages.map((age) => Math.max(0, age)));
  const age = t("status.age_ms_ago", { value: formatInt(ageMs) });
  return t(`dashboard.data_freshness_${classifyFreshness(ageMs, connected)}`, {
    age,
  });
}

/** The connected sensor with the highest vibration level right now. */
export function strongestSensor(
  clients: readonly AdaptedClient[],
  spectra: SpectrumFrameData,
): { client: AdaptedClient; db: number } | null {
  let best: { client: AdaptedClient; db: number } | null = null;
  for (const client of clients) {
    const db =
      spectra.clients[client.id]?.strength_metrics?.vibration_strength_db;
    if (
      client.connected &&
      typeof db === "number" &&
      Number.isFinite(db) &&
      (!best || db > best.db)
    ) {
      best = { client, db };
    }
  }
  return best;
}

export function activeCarText(
  selection: CarSelectionState,
  t: Translate,
): string {
  switch (selection.kind) {
    case "loading":
      return t("dashboard.active_car_loading");
    case "no_cars":
      return t("dashboard.active_car_none_no_cars");
    case "no_active_car":
      return t("dashboard.active_car_none_blocked");
    default:
      return selection.car.name;
  }
}

export function speedText(
  speedMps: number | null,
  unit: SpeedUnit,
  labelKey: string,
  t: Translate,
  fmt: (value: number, digits: number) => string,
  fallbackReason: string | null = null,
): string {
  const unitText = t(speedUnitKey(unit));
  if (typeof speedMps !== "number" || !Number.isFinite(speedMps)) {
    return t("speed.none", { unit: unitText });
  }
  return t(labelKey, {
    unit: unitText,
    value: fmt(kmhInUnit(speedMps * 3.6, unit), 1),
    ...(fallbackReason ? { reason: fallbackReason } : {}),
  });
}

function runIdText(status: LoggingStatusPayload, t: Translate): string {
  if (status.enabled && status.run_id) {
    return t("dashboard.logging.run_id", { runId: status.run_id });
  }
  const lastRunId = status.last_run_id ?? status.last_completed_run_id;
  return lastRunId
    ? t("dashboard.logging.last_run_id", { runId: lastRunId })
    : "";
}

function setupAction(
  check: { check_key: string; reason_key?: string | null },
  t: Translate,
) {
  const action = (target: SummaryAction, key: string) => ({
    action: target,
    label: t(`dashboard.logging.blocked.setup.action.${key}`),
    variant: "primary" as const,
  });
  if (check.check_key === "sensors_ready") {
    return action("open-sensors", "sensors");
  }
  if (check.check_key === "reference_ready") {
    return check.reason_key === "active_car_missing"
      ? action("open-cars", "cars")
      : action("open-speed-source", "speed_source");
  }
  if (
    check.check_key === "speed_stable" &&
    check.reason_key === "speed_sample_missing"
  ) {
    return action("open-speed-source", "speed_source");
  }
  return null;
}

/**
 * The likely cause when the live speed is missing: GPS has no receiver, or
 * its receiver is still waiting for a fix.
 */
export function liveSpeedHint(
  input: Pick<RecordingInputs, "gpsReceiverMissing" | "gpsFixWaitS">,
  t: Translate,
  formatInt: FormatInt,
): string | null {
  if (input.gpsReceiverMissing) {
    return `${t("speed.gps_no_receiver.title")}: ${t("speed.gps_no_receiver.body")}`;
  }
  return input.gpsFixWaitS === null
    ? null
    : t("speed.gps_waiting_fix", {
        seconds: formatInt(Math.floor(input.gpsFixWaitS)),
      });
}

function speedSourceHint(
  check: { check_key: string; reason_key?: string | null },
  input: Pick<RecordingInputs, "gpsReceiverMissing" | "gpsFixWaitS">,
  t: Translate,
  formatInt: FormatInt,
): string | null {
  if (
    check.check_key !== "reference_ready" ||
    check.reason_key === "active_car_missing"
  ) {
    return null;
  }
  return liveSpeedHint(input, t, formatInt);
}

/** The failing check that keeps Start greyed out, if any. */
function blockingCheck(readiness: Readiness | null) {
  if (!readiness || readiness.is_ready) {
    return null;
  }
  return (
    readiness.checks.find(
      (check) => check.state === "fail" && check.check_key !== "capture_ready",
    ) ?? findCheck(readiness, "capture_ready")
  );
}

function panel(
  prefix: string,
  t: Translate,
  action: SummaryPanel["action"],
): SummaryPanel {
  return {
    title: t(`${prefix}.title`),
    body: t(`${prefix}.body`),
    detail: t(`${prefix}.detail`),
    action,
  };
}

export interface RecordingInputs {
  status: LoggingStatusPayload;
  pending: PendingAction;
  /** Set while no car is active (including while cars are loading). */
  carBlock: "no_cars" | "no_active" | null;
  /** The setup card on Live lists the missing car, speed source or sensors. */
  setupIncomplete: boolean;
  health: LiveHealth;
  speedUnit: SpeedUnit;
  /** GPS is the speed source but no USB receiver is plugged in. */
  gpsReceiverMissing: boolean;
  /** Seconds the GPS receiver has been waiting for a fix, if it is. */
  gpsFixWaitS: number | null;
  connectedText: string;
  assignedText: string;
  elapsedText: string;
  /** Elapsed time of the run that just finished (kept after it stops). */
  lastRunElapsedText: string;
}

/** The recording card for the current server status and pending action. */
export function recordingModel(
  input: RecordingInputs,
  t: Translate,
  formatInt: FormatInt,
): RecordingModel {
  const { status, pending } = input;
  const readiness = status.capture_readiness ?? null;
  const notReady = !readiness?.is_ready;
  const phase = (key: string) => t(`dashboard.recording_phase.${key}`);
  const blocked = blockingCheck(readiness);
  const blockedReason = () => {
    if (!blocked) {
      return null;
    }
    const hint = speedSourceHint(blocked, input, t, formatInt);
    const reason = checkDetail(blocked, t, formatInt, input.speedUnit);
    return t("dashboard.logging.start_blocked", {
      reason: hint ? `${reason} ${hint}` : reason,
    });
  };
  const base = {
    showPill: false,
    summaryText: "",
    summaryPanel: null,
    runIdText: runIdText(status, t),
    elapsedText: "--",
    samplesText: formatInt(status.samples_written ?? 0),
    checklist: null,
    blockedReason: null,
    showStop: false,
    startDisabled: true,
    stopDisabled: true,
    setupMode: false,
  };
  if (pending === "starting") {
    return {
      ...base,
      pillVariant: "muted",
      pillText: phase("starting"),
      phaseText: phase("starting"),
      showPill: true,
      summaryText: t("dashboard.logging.starting"),
    };
  }
  if (pending === "stopping") {
    return {
      ...base,
      pillVariant: "warn",
      pillText: phase("stopping"),
      phaseText: phase("stopping"),
      showPill: true,
      summaryText: t("dashboard.logging.stopping"),
      elapsedText: input.elapsedText,
      showStop: true,
    };
  }
  if (status.enabled) {
    return {
      ...base,
      pillVariant: status.write_error ? "bad" : "ok",
      pillText: status.write_error || phase("recording"),
      phaseText: status.write_error
        ? t("dashboard.health.attention")
        : phase("recording"),
      showPill: Boolean(status.write_error),
      summaryText:
        input.health.variant === "ok"
          ? t("dashboard.logging.running", {
              connected: input.connectedText,
              assigned: input.assignedText,
            })
          : input.health.summary,
      elapsedText: input.elapsedText,
      showStop: true,
      stopDisabled: false,
    };
  }
  if (status.analysis_in_progress || status.last_completed_run_id) {
    const key = status.analysis_in_progress ? "processing" : "saved";
    const summary = panel(`dashboard.logging.${key}`, t, {
      action: "open-history",
      label: t(`dashboard.logging.${key}.action`),
      variant: "primary",
    });
    return {
      ...base,
      // The counters describe the run stopped since the server started, if any.
      samplesText: status.last_run_id
        ? formatInt(status.samples_written ?? 0)
        : "--",
      pillVariant: status.analysis_in_progress ? "warn" : "ok",
      pillText: phase(key),
      phaseText: phase(key),
      summaryPanel: summary,
      elapsedText: input.lastRunElapsedText,
      blockedReason: blockedReason(),
      startDisabled: notReady,
    };
  }
  // The setup card names the missing car, speed source or sensors, with its fix.
  if (input.carBlock) {
    return {
      ...base,
      pillVariant: "warn",
      pillText: phase("blocked"),
      phaseText: phase("blocked"),
      setupMode: true,
    };
  }
  const waiting = readiness !== null && !readiness.is_ready;
  const primary = input.setupIncomplete ? null : blocked;
  const items = input.setupIncomplete
    ? []
    : checklist(readiness, waiting, t, formatInt, input.speedUnit);
  return {
    ...base,
    pillVariant: waiting ? "muted" : "ok",
    pillText: phase(waiting ? "preparing" : "ready"),
    phaseText: phase(waiting ? "preparing" : "ready"),
    summaryText: waiting
      ? ""
      : readinessSummary(readiness, t, formatInt, input.speedUnit) ||
        input.health.summary,
    summaryPanel: primary
      ? {
          title: t("dashboard.logging.blocked.setup.title"),
          body: checkDetail(primary, t, formatInt, input.speedUnit),
          detail: speedSourceHint(primary, input, t, formatInt),
          action: setupAction(primary, t),
        }
      : null,
    checklist: items.length ? items : null,
    startDisabled: notReady,
    setupMode: waiting,
  };
}

/** Notices at the top of Live that a driver must see at a glance. */
export interface DriveAlerts {
  /** Recording, but no sensor data for a while: the run stops if it stays away. */
  sensorSilent: Feedback | null;
  /** Why the last run stopped by itself; kept until the next run starts. */
  stopNotice: Feedback | null;
  /** While recording: set the phone's auto-lock to Never. */
  keepAwakeHint: Feedback | null;
}

/** A few seconds without data is normal Wi-Fi jitter; longer is worth a look. */
const SENSOR_SILENT_NOTICE_S = 5;

export function driveAlerts(
  input: { status: LoggingStatusPayload; keepAwake: KeepAwakeMode },
  t: Translate,
  formatInt: FormatInt,
): DriveAlerts {
  const { status } = input;
  const timeoutS = status.no_data_timeout_s;
  const silentS = status.enabled ? (status.no_data_s ?? null) : null;
  const sensorSilent: Feedback | null =
    silentS !== null && silentS >= SENSOR_SILENT_NOTICE_S
      ? {
          title: t("dashboard.logging.sensor_silent.title"),
          body: t("dashboard.logging.sensor_silent.body", {
            seconds: formatInt(Math.round(silentS)),
            remaining: formatInt(Math.max(0, Math.round(timeoutS - silentS))),
          }),
          tone: "error",
        }
      : null;
  let stopNotice: Feedback | null = null;
  if (!status.enabled && status.last_stop_reason === "no_data_timeout") {
    stopNotice = {
      title: t("dashboard.logging.auto_stopped_no_data.title"),
      body: t("dashboard.logging.auto_stopped_no_data.body", {
        seconds: formatInt(Math.round(timeoutS)),
      }),
      tone: "error",
    };
  } else if (!status.enabled && status.last_stop_reason === "max_duration") {
    stopNotice = {
      body: t("dashboard.logging.auto_stopped_max_duration"),
      tone: "info",
    };
  }
  return {
    sensorSilent,
    stopNotice,
    keepAwakeHint:
      status.enabled && input.keepAwake !== "wake-lock"
        ? {
            body: t("dashboard.logging.keep_awake_hint"),
            tone: "info",
            compact: true,
          }
        : null,
  };
}

/** Replaces the recording card when the status cannot be read or an action failed. */
export function withLoggingError(
  model: RecordingModel,
  error: LoggingError,
  t: Translate,
): RecordingModel {
  const unavailable = t("status.unavailable");
  if (error.kind === "unavailable") {
    return {
      pillVariant: "bad",
      pillText: unavailable,
      showPill: true,
      phaseText: unavailable,
      summaryText: unavailable,
      summaryPanel: null,
      runIdText: "",
      elapsedText: "--",
      samplesText: "--",
      checklist: null,
      blockedReason: null,
      showStop: false,
      startDisabled: true,
      stopDisabled: true,
      setupMode: false,
    };
  }
  const message = error.message || unavailable;
  return {
    ...model,
    pillVariant: "bad",
    pillText: message,
    showPill: true,
    summaryText: message,
    summaryPanel: null,
  };
}

// --- First-run setup and the action bar -----------------------------------------

export type SetupStepKey = "car" | "speed" | "sensors";

export interface SetupStep {
  key: SetupStepKey;
  /** `current` is the first step still to do; later ones are `todo`. */
  state: "done" | "current" | "todo";
  title: string;
  status: string;
  action: { action: SummaryAction; label: string } | null;
}

export interface SetupModel {
  steps: SetupStep[];
  /** The first step still to do; `null` once the car, speed and sensors are set. */
  next: SetupStep | null;
}

export interface SetupInputs {
  carSelection: CarSelectionState;
  readiness: Readiness | null;
  /** Live sensors connected right now. */
  connected: number;
  /** The chosen source when it gives a speed, e.g. "GPS" or "Typed in: 80 km/h". */
  speedDoneText: string;
  /** Why the speed is missing (no GPS receiver, waiting for a fix), if known. */
  speedHint: string | null;
  speedUnit: SpeedUnit;
}

/** Reasons the speed-source tab fixes (everything but a missing car). */
const SPEED_SETUP_REASONS = new Set([
  "speed_source_missing",
  "speed_source_not_live",
  "speed_source_fallback_active",
  "speed_sample_stale",
  "speed_sample_missing",
  "obd_rpm_missing",
  "obd_rpm_stale",
]);

/**
 * The three things a first recording needs, in the order to set them up:
 * an active car, a speed source that gives a speed, and live sensors that all
 * have a location. Frame loss or drifting clocks are not setup steps; the
 * readiness list explains those. `null` until the cars and the readiness are
 * known.
 */
export function setupModel(
  input: SetupInputs,
  t: Translate,
  formatInt: FormatInt,
): SetupModel | null {
  const { carSelection, readiness } = input;
  if (carSelection.kind === "loading" || readiness === null) {
    return null;
  }
  const action = (
    target: SummaryAction,
    key: string,
    vars?: Record<string, unknown>,
  ) => ({ action: target, label: t(`dashboard.setup.action.${key}`, vars) });
  const carDone = carSelection.kind === "active";
  const car = {
    key: "car" as const,
    done: carDone,
    status:
      carSelection.kind === "active"
        ? carSelection.car.name
        : t(`dashboard.setup.car.${carSelection.kind}`),
    action:
      carSelection.kind === "no_cars"
        ? action("open-add-car", "add_car")
        : action("open-cars", "choose_car"),
  };
  const reference = findCheck(readiness, "reference_ready");
  const speedProblem =
    reference !== null &&
    reference.state === "fail" &&
    SPEED_SETUP_REASONS.has(reference.reason_key ?? "");
  const speedUnknown = reference?.reason_key === "active_car_missing";
  const speedDetail = speedProblem
    ? [checkDetail(reference, t, formatInt, input.speedUnit), input.speedHint]
        .filter(Boolean)
        .join(" ")
    : "";
  const speed = {
    key: "speed" as const,
    done: !speedProblem && !speedUnknown,
    status: speedProblem
      ? speedDetail
      : speedUnknown
        ? t("dashboard.setup.speed.after_car")
        : input.speedDoneText,
    action: action("open-speed-source", "speed_source"),
  };
  const sensorsCheck = findCheck(readiness, "sensors_ready");
  const sensorsReason =
    sensorsCheck?.state === "fail" ? (sensorsCheck.reason_key ?? "") : "";
  const unplaced =
    sensorsCheck && sensorsReason === "sensor_locations_missing"
      ? Math.max(1, detailCount(sensorsCheck, "unassigned_sensor_count"))
      : 0;
  const sensorsDone =
    sensorsReason !== "no_live_sensors" &&
    sensorsReason !== "sensor_locations_missing";
  const sensors = {
    key: "sensors" as const,
    done: sensorsDone,
    status:
      sensorsDone || !sensorsCheck
        ? t("dashboard.setup.sensors.done", {
            count: input.connected,
          })
        : checkDetail(sensorsCheck, t, formatInt, input.speedUnit),
    action: unplaced
      ? action("open-sensors", "place_sensors", { count: unplaced })
      : action("open-sensors", "sensors"),
  };
  const firstOpen = [car, speed, sensors].findIndex((step) => !step.done);
  const steps = [car, speed, sensors].map(
    (step, index): SetupStep => ({
      key: step.key,
      state: step.done ? "done" : index === firstOpen ? "current" : "todo",
      title: t(`dashboard.setup.${step.key}.title`),
      status: step.status,
      action: step.done ? null : step.action,
    }),
  );
  return { steps, next: firstOpen < 0 ? null : steps[firstOpen] };
}

export type ActionBarButton =
  | { kind: "start"; label: string; disabled: boolean }
  | { kind: "stop"; label: string; disabled: boolean }
  | { kind: "history"; label: string }
  | { kind: "setup"; label: string; action: SummaryAction };

export interface ActionBarModel {
  state:
    | "checking"
    | "setup"
    | "blocked"
    | "ready"
    | "starting"
    | "recording"
    | "stopping"
    | "after"
    | "unavailable";
  title: string;
  /** "m:ss" recorded so far, while recording. */
  elapsed: string | null;
  detail: string | null;
  /** The detail is an error (a failed start or stop, a write error). */
  error: boolean;
  primary: ActionBarButton;
  secondary: ActionBarButton | null;
}

/**
 * The one next thing to do on Live, for the bar at the bottom of a phone
 * screen (inside the recording card on a wide screen): finish a setup step,
 * start, stop with the elapsed time, or open the run just recorded.
 */
export function actionBarModel(
  input: {
    status: LoggingStatusPayload;
    pending: PendingAction;
    recording: RecordingModel;
    setup: SetupModel | null;
    error: LoggingError | null;
  },
  t: Translate,
): ActionBarModel {
  const { status, pending, recording, setup, error } = input;
  const start = (disabled: boolean): ActionBarButton => ({
    kind: "start",
    label: t("dashboard.start_recording"),
    disabled,
  });
  const failure =
    error?.kind === "error" ? recording.pillText : status.write_error || null;
  const bar = (
    state: ActionBarModel["state"],
    title: string,
    primary: ActionBarButton,
    rest: Partial<ActionBarModel> = {},
  ): ActionBarModel => ({
    state,
    title,
    elapsed: null,
    detail: failure,
    error: failure !== null,
    primary,
    secondary: null,
    ...rest,
  });
  if (error?.kind === "unavailable") {
    return bar("unavailable", t("status.unavailable"), start(true));
  }
  if (pending === "starting") {
    return bar("starting", t("dashboard.bar.starting"), start(true));
  }
  if (recording.showStop) {
    const stopping = pending === "stopping";
    return bar(
      stopping ? "stopping" : "recording",
      t(stopping ? "dashboard.bar.stopping" : "dashboard.bar.recording"),
      {
        kind: "stop",
        label: t("dashboard.stop_recording"),
        disabled: recording.stopDisabled,
      },
      { elapsed: recording.elapsedText },
    );
  }
  if (status.analysis_in_progress || status.last_completed_run_id) {
    return bar(
      "after",
      t(
        status.analysis_in_progress
          ? "dashboard.bar.analyzing"
          : "dashboard.bar.saved",
      ),
      { kind: "history", label: t("dashboard.logging.saved.action") },
      { secondary: start(recording.startDisabled) },
    );
  }
  const next = setup?.next;
  if (setup && next?.action) {
    return bar(
      "setup",
      t("dashboard.bar.setup_step", {
        n: setup.steps.indexOf(next) + 1,
        total: setup.steps.length,
        step: next.title,
      }),
      { kind: "setup", label: next.action.label, action: next.action.action },
    );
  }
  if (status.capture_readiness == null) {
    return bar("checking", t("dashboard.bar.checking"), start(true));
  }
  if (recording.startDisabled) {
    return bar("blocked", t("dashboard.bar.not_ready"), start(true), {
      detail:
        failure ??
        recording.blockedReason ??
        recording.summaryPanel?.body ??
        null,
    });
  }
  return bar("ready", t("dashboard.bar.ready"), start(false));
}

// --- Guided test drive ---------------------------------------------------------

/**
 * Sweep, hold, a neutral coast-down, then firm stops for the brake check: the
 * order the driver does them in.
 */
const GUIDED_STEPS: readonly GuidedPhase[] = [
  "sweep",
  "hold",
  "coast_down",
  "brake",
];
/** An EV has no neutral that decouples its motor, so it skips the coast-down. */
const GUIDED_STEPS_EV: readonly GuidedPhase[] = ["sweep", "hold", "brake"];

export interface GuidedStep {
  phase: GuidedPhase;
  label: string;
  title: string;
  instruction: string;
  /** The brake step's firm stops counted so far, once it has started. */
  progress: string | null;
  state: "done" | "current" | "todo";
}

/** The step in progress, for the large card at the top of Live. */
export interface GuidedCurrentStep {
  phase: GuidedPhase;
  label: string;
  title: string;
  /** A glanceable version of the instruction. */
  short: string;
  progress: string | null;
  /** The next step to start, or `null` to finish the guided test. */
  action: { label: string; phase: GuidedPhase | null };
}

export interface GuidedTestModel {
  /**
   * `preview` lists the steps to read while parked; `active` is the guided
   * test of the run being recorded.
   */
  mode: "hidden" | "preview" | "active";
  hint: string;
  finished: boolean;
  steps: GuidedStep[];
  /** Starts the guided test, before any step; `current.action` moves on from there. */
  action: { label: string; phase: GuidedPhase } | null;
  current: GuidedCurrentStep | null;
  disabled: boolean;
  /**
   * With a typed-in speed no step can show in the run (each needs live speed),
   * so this says so in place of offering the guided test; `null` otherwise.
   */
  typedInNote: string | null;
}

function guidedText(
  phase: GuidedPhase,
  kind: "instruction" | "short",
  unit: SpeedUnit,
  electric: boolean,
  t: Translate,
): string {
  const speed = (kmh: number) => fmt(kmhInUnit(kmh, unit), 0);
  // Only the sweep (top gear) and the brake step (regen) read differently in an EV.
  const ev = electric && (kind === "instruction" || phase === "sweep");
  return t(`dashboard.guided.${phase}.${kind}${ev ? "_ev" : ""}`, {
    from: speed(GUIDED_SWEEP_FROM_KMH),
    to: speed(GUIDED_SWEEP_TO_KMH),
    drop: speed(GUIDED_COAST_DROP_KMH),
    brakeFrom: speed(GUIDED_BRAKE_FROM_KMH),
    brakeTo: speed(GUIDED_BRAKE_TO_KMH),
    stops: GUIDED_BRAKE_STOPS,
    unit: t(speedUnitKey(unit)),
  });
}

/**
 * How many firm stops the server counted in the brake step, by the analysis's
 * own braking rule (`guided_brake_stops`).
 */
function brakeProgress(stops: number, t: Translate): string {
  const vars = { n: stops, total: GUIDED_BRAKE_STOPS };
  return stops >= GUIDED_BRAKE_STOPS
    ? t("dashboard.guided.brake.progress_done", vars)
    : t("dashboard.guided.brake.progress", vars);
}

/**
 * The optional guided test drive. While parked, Live previews its steps so the
 * driver can read them before setting off. While a run records, the server
 * reports the step in progress, the steps completed so far and the brake
 * step's firm stops, so the guided test survives a page reload mid-run; the
 * step in progress also gets a short card with the Next button at the top of
 * Live. An EV drives without top gear or neutral: its steps are the sweep, the
 * hold and the firm stops (docs/user_journeys.md §5.3).
 */
export function guidedTestModel(
  status: LoggingStatusPayload,
  unit: SpeedUnit,
  busy: boolean,
  fuelType: FuelType,
  t: Translate,
  typedInSpeed = false,
): GuidedTestModel {
  const electric = fuelType === "EV";
  const order = electric ? GUIDED_STEPS_EV : GUIDED_STEPS;
  const recording = status.enabled && Boolean(status.run_id);
  const current = recording ? (status.guided_phase ?? null) : null;
  const completed = recording ? (status.guided_phases_completed ?? []) : [];
  const finished =
    current === null && order.every((step) => completed.includes(step));
  const index = current ? order.indexOf(current) : finished ? order.length : -1;
  const label = (i: number) =>
    t("dashboard.guided.step_label", { n: i + 1, total: order.length });
  const title = (phase: GuidedPhase) => t(`dashboard.guided.${phase}.title`);
  const steps = order.map((phase, i) => {
    const state: GuidedStep["state"] =
      i < index ? "done" : i === index ? "current" : "todo";
    return {
      phase,
      label: label(i),
      title: title(phase),
      instruction: guidedText(phase, "instruction", unit, electric, t),
      progress:
        phase === "brake" && state !== "todo"
          ? brakeProgress(status.guided_brake_stops, t)
          : null,
      state,
    };
  });
  let currentStep: GuidedCurrentStep | null = null;
  if (current !== null && index >= 0) {
    const next = order[index + 1];
    currentStep = {
      phase: current,
      label: label(index),
      title: title(current),
      short: guidedText(current, "short", unit, electric, t),
      progress: steps[index].progress,
      action: next
        ? {
            label: t("dashboard.guided.next", { step: title(next) }),
            phase: next,
          }
        : { label: t("dashboard.guided.finish"), phase: null },
    };
  }
  return {
    mode: recording ? "active" : status.enabled ? "hidden" : "preview",
    hint: t(electric ? "dashboard.guided.hint_ev" : "dashboard.guided.hint"),
    finished,
    steps,
    action:
      recording && index < 0 && !typedInSpeed
        ? { label: t("dashboard.guided.start"), phase: order[0] }
        : null,
    current: currentStep,
    disabled: busy,
    typedInNote: typedInSpeed ? t("dashboard.guided.typed_in_note") : null,
  };
}

/**
 * Stopping mid-step ends the guided test with the run, so a tap meant for Next
 * asks first. Without a step in progress, Stop stops straight away.
 */
export function stopConfirmation(
  model: GuidedTestModel,
  t: Translate,
): string | null {
  const step = model.current;
  return step
    ? t("dashboard.guided.confirm_stop", {
        step: step.title,
        label: step.label,
      })
    : null;
}
