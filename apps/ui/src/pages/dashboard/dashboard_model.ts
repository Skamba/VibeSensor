import type { GuidedPhase, LoggingStatusPayload } from "../../api/types";
import type { FuelType } from "../../capabilities";
import type { CarSelectionState } from "../../car_selection";
import {
  GUIDED_BRAKE_FROM_KMH,
  GUIDED_BRAKE_STOPS,
  GUIDED_BRAKE_TO_KMH,
  GUIDED_COAST_DROP_KMH,
  GUIDED_SWEEP_FROM_KMH,
  GUIDED_SWEEP_TO_KMH,
} from "../../config";
import { fmt, kmhInUnit, type SpeedUnit, speedUnitKey } from "../../format";
import type { LocationOption } from "../../sensor_locations";
import type {
  AdaptedClient,
  SpectrumFrameData,
} from "../../transport/live_models";
import {
  checkDetail,
  type ChecklistItem,
  checklist,
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
  showOverviewPill: boolean;
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
    showOverviewPill: true,
  });
  if (status.write_error) {
    return {
      variant: "bad",
      text: t("dashboard.health.write_error"),
      summary: status.write_error,
      showOverviewPill: true,
    };
  }
  const connected = clients.filter((client) => client.connected);
  if (!connected.length) {
    return {
      variant: "muted",
      text: t("dashboard.health.no_signal"),
      summary: t("dashboard.logging.waiting"),
      showOverviewPill: true,
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
    return attention(
      t("dashboard.logging.frame_loss", { count: formatInt(dropping) }),
    );
  }
  const unassigned = connected.filter((client) => !locationOf(client)).length;
  if (unassigned > 0) {
    return attention(
      t("dashboard.logging.unassigned", { count: formatInt(unassigned) }),
    );
  }
  const offline = clients.length - connected.length;
  if (offline > 0) {
    return attention(
      t("dashboard.logging.offline", { count: formatInt(offline) }),
    );
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
      showOverviewPill: false,
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
    showOverviewPill: false,
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

/** Location label when the sensor has one, else its name (or id). */
export function sensorLabel(
  client: AdaptedClient,
  code: string,
  options: readonly LocationOption[],
  fallback: string,
): string {
  if (code) {
    return options.find((option) => option.code === code)?.label ?? code;
  }
  return String(client.name || client.id || fallback).trim();
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

/** Names the likely cause when the live speed is missing because GPS has no receiver. */
function speedSourceHint(
  check: { check_key: string; reason_key?: string | null },
  gpsReceiverMissing: boolean,
  t: Translate,
): string | null {
  return gpsReceiverMissing &&
    check.check_key === "reference_ready" &&
    check.reason_key !== "active_car_missing"
    ? `${t("speed.gps_no_receiver.title")}: ${t("speed.gps_no_receiver.body")}`
    : null;
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
  health: LiveHealth;
  speedUnit: SpeedUnit;
  /** GPS is the speed source but no USB receiver is plugged in. */
  gpsReceiverMissing: boolean;
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
  const base = {
    showPill: false,
    summaryText: "",
    summaryPanel: null,
    runIdText: runIdText(status, t),
    elapsedText: "--",
    samplesText: formatInt(status.samples_written ?? 0),
    checklist: null,
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
      summaryPanel:
        status.last_stop_reason === "max_duration"
          ? {
              ...summary,
              detail: t("dashboard.logging.auto_stopped_max_duration"),
            }
          : summary,
      elapsedText: input.lastRunElapsedText,
      startDisabled: notReady,
    };
  }
  if (input.carBlock) {
    const noCars = input.carBlock === "no_cars";
    const prefix = `dashboard.logging.blocked.${input.carBlock}`;
    return {
      ...base,
      pillVariant: "warn",
      pillText: phase("blocked"),
      phaseText: phase("blocked"),
      summaryText: readinessSummary(readiness, t, formatInt, input.speedUnit),
      summaryPanel: panel(prefix, t, {
        action: noCars ? "open-add-car" : "open-cars",
        label: t(`${prefix}.action`),
        variant: noCars ? "success" : "primary",
      }),
      setupMode: true,
    };
  }
  const waiting = readiness !== null && !readiness.is_ready;
  const primary = waiting
    ? (readiness.checks.find(
        (check) =>
          check.state === "fail" && check.check_key !== "capture_ready",
      ) ?? findCheck(readiness, "capture_ready"))
    : null;
  const items = checklist(readiness, waiting, t, formatInt, input.speedUnit);
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
          detail: speedSourceHint(primary, input.gpsReceiverMissing, t),
          action: setupAction(primary, t),
        }
      : null,
    checklist: items.length ? items : null,
    startDisabled: notReady,
    setupMode: waiting,
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

export interface GuidedTestModel {
  visible: boolean;
  hint: string;
  finished: boolean;
  steps: GuidedStep[];
  /** What the button does next: a step to start, `null` to finish, absent when done. */
  action: { label: string; phase: GuidedPhase | null } | null;
  disabled: boolean;
}

function guidedInstruction(
  phase: GuidedPhase,
  unit: SpeedUnit,
  electric: boolean,
  t: Translate,
): string {
  const speed = (kmh: number) => fmt(kmhInUnit(kmh, unit), 0);
  const suffix = electric ? "_ev" : "";
  return t(`dashboard.guided.${phase}.instruction${suffix}`, {
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
 * The optional guided test drive shown while a run records. The server
 * reports the step in progress, the steps completed so far and the brake
 * step's firm stops, so the panel survives a page reload mid-run. An EV drives
 * without top gear or neutral: its steps are the sweep, the hold and the
 * firm stops (docs/user_journeys.md §5.3).
 */
export function guidedTestModel(
  status: LoggingStatusPayload,
  unit: SpeedUnit,
  busy: boolean,
  fuelType: FuelType,
  t: Translate,
): GuidedTestModel {
  const electric = fuelType === "EV";
  const order = electric ? GUIDED_STEPS_EV : GUIDED_STEPS;
  const current = status.guided_phase ?? null;
  const completed = status.guided_phases_completed ?? [];
  const finished =
    current === null && order.every((step) => completed.includes(step));
  const index = current ? order.indexOf(current) : finished ? order.length : -1;
  const steps = order.map((phase, i) => {
    const state: GuidedStep["state"] =
      i < index ? "done" : i === index ? "current" : "todo";
    return {
      phase,
      label: t("dashboard.guided.step_label", {
        n: i + 1,
        total: order.length,
      }),
      title: t(`dashboard.guided.${phase}.title`),
      instruction: guidedInstruction(phase, unit, electric, t),
      progress:
        phase === "brake" && state !== "todo"
          ? brakeProgress(status.guided_brake_stops, t)
          : null,
      state,
    };
  });
  let action: GuidedTestModel["action"] = null;
  if (index < 0) {
    action = { label: t("dashboard.guided.start"), phase: order[0] };
  } else if (index < order.length - 1) {
    const next = order[index + 1];
    action = {
      label: t("dashboard.guided.next", {
        step: t(`dashboard.guided.${next}.title`),
      }),
      phase: next,
    };
  } else if (index === order.length - 1) {
    action = { label: t("dashboard.guided.finish"), phase: null };
  }
  return {
    visible: status.enabled && Boolean(status.run_id),
    hint: t(electric ? "dashboard.guided.hint_ev" : "dashboard.guided.hint"),
    finished,
    steps,
    action,
    disabled: busy,
  };
}
