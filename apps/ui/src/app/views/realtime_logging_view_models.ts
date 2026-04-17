import type { LiveHealth } from "../features/realtime_sensor_state";
import type { LoggingStatusPayload } from "../../api/types";
import type {
  InlineStateActionVariant,
  InlineStatePanelElement,
} from "./dom_helpers";

export const REALTIME_LOGGING_SUMMARY_ACTIONS = [
  "open-history",
  "open-cars",
  "open-add-car",
  "open-sensors",
  "open-speed-source",
] as const;

export type RealtimeLoggingSummaryAction = (typeof REALTIME_LOGGING_SUMMARY_ACTIONS)[number];
export type RealtimeLoggingPendingAction = "starting" | "stopping" | null;

export type CaptureReadinessPayload = NonNullable<LoggingStatusPayload["capture_readiness"]>;
export type CaptureReadinessCheckPayload = CaptureReadinessPayload["checks"][number];

export interface RealtimeLoggingSummaryPanelModel
  extends Omit<InlineStatePanelElement, "action"> {
  action?: {
    action: RealtimeLoggingSummaryAction;
    labelText: string;
    variant?: InlineStateActionVariant;
  };
}

export interface RealtimeCaptureReadinessChecklistItemModel {
  checkKey: CaptureReadinessCheckPayload["check_key"];
  state: CaptureReadinessCheckPayload["state"];
  labelText: string;
  stateText: string;
  detailText: string;
}

export interface RealtimeCaptureReadinessChecklistModel {
  titleText: string;
  items: readonly RealtimeCaptureReadinessChecklistItemModel[];
}

export interface RealtimeLoggingPanelViewModel {
  pillVariant: "muted" | "ok" | "warn" | "bad";
  pillText: string;
  phaseText: string;
  summaryText: string;
  summaryPanel: RealtimeLoggingSummaryPanelModel | null;
  runIdText: string;
  elapsedText: string;
  samplesText: string;
  showStart: boolean;
  showStop: boolean;
  startDisabled: boolean;
  stopDisabled: boolean;
  showPill: boolean;
  checklist: RealtimeCaptureReadinessChecklistModel | null;
  setupMode: boolean;
  nextLastCompletedElapsedText: string;
}

export interface CaptureReadinessTextDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  formatInt: (value: number) => string;
}

export interface BuildRealtimeLoggingPanelViewModelParams
  extends CaptureReadinessTextDeps {
  status: LoggingStatusPayload;
  pendingLoggingAction: RealtimeLoggingPendingAction;
  selectionBlockReason: "no_cars" | "no_active" | null;
  liveHealth: LiveHealth;
  connectedCountText: string;
  assignedCountText: string;
  runIdText: string;
  elapsedText: string;
  samplesText: string;
  lastCompletedElapsedText: string;
}

const CAPTURE_READINESS_ORDER = [
  "sensors_ready",
  "reference_ready",
  "speed_stable",
  "capture_ready",
] as const;

export function captureReadinessCheck(
  readiness: CaptureReadinessPayload | null,
  checkKey: CaptureReadinessCheckPayload["check_key"],
): CaptureReadinessCheckPayload | null {
  return readiness?.checks.find((check) => check.check_key === checkKey) ?? null;
}

function captureReadinessDetailNumber(
  check: CaptureReadinessCheckPayload | null,
  key: string,
): number | null {
  const value = check?.details?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function captureReadinessStateText(
  state: CaptureReadinessCheckPayload["state"],
  deps: CaptureReadinessTextDeps,
): string {
  return deps.t(`dashboard.capture_readiness.state.${state}`);
}

function captureReadinessCheckLabel(
  checkKey: CaptureReadinessCheckPayload["check_key"],
  deps: CaptureReadinessTextDeps,
): string {
  return deps.t(`dashboard.capture_readiness.${checkKey}.label`);
}

function captureReadinessDetailText(
  check: CaptureReadinessCheckPayload,
  deps: CaptureReadinessTextDeps,
): string {
  const { t, formatInt } = deps;
  if (check.check_key === "sensors_ready") {
    const liveSensorCount = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "live_sensor_count") ?? 0),
    );
    const unassignedSensorCount = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "unassigned_sensor_count") ?? 0),
    );
    const quietPeriodRemaining = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "quiet_period_remaining_s") ?? 0),
    );
    if (check.reason_key === "no_live_sensors") {
      return t("dashboard.capture_readiness.sensors_ready.no_live_sensors");
    }
    if (check.reason_key === "sensor_locations_missing") {
      return t("dashboard.capture_readiness.sensors_ready.sensor_locations_missing", {
        count: formatInt(unassignedSensorCount),
      });
    }
    if (check.reason_key === "recent_integrity_events") {
      return t("dashboard.capture_readiness.sensors_ready.recent_integrity_events", {
        seconds: formatInt(quietPeriodRemaining),
      });
    }
    if (check.reason_key === "limited_sensor_coverage") {
      return t("dashboard.capture_readiness.sensors_ready.limited_sensor_coverage", {
        count: formatInt(liveSensorCount),
      });
    }
    return t("dashboard.capture_readiness.sensors_ready.ready", {
      count: formatInt(liveSensorCount),
    });
  }

  if (check.check_key === "reference_ready") {
    if (check.reason_key === "active_car_missing") {
      return t("dashboard.capture_readiness.reference_ready.active_car_missing");
    }
    if (check.reason_key === "order_reference_incomplete") {
      return t("dashboard.capture_readiness.reference_ready.order_reference_incomplete");
    }
    if (check.reason_key === "speed_source_missing") {
      return t("dashboard.capture_readiness.reference_ready.speed_source_missing");
    }
    if (check.reason_key === "speed_source_not_live") {
      return t("dashboard.capture_readiness.reference_ready.speed_source_not_live");
    }
    if (check.reason_key === "speed_source_fallback_active") {
      return t("dashboard.capture_readiness.reference_ready.speed_source_fallback_active");
    }
    if (check.reason_key === "speed_sample_stale") {
      return t("dashboard.capture_readiness.reference_ready.speed_sample_stale");
    }
    if (check.reason_key === "speed_sample_missing") {
      return t("dashboard.capture_readiness.reference_ready.speed_sample_missing");
    }
    if (check.reason_key === "obd_rpm_missing") {
      return t("dashboard.capture_readiness.reference_ready.obd_rpm_missing");
    }
    if (check.reason_key === "obd_rpm_stale") {
      return t("dashboard.capture_readiness.reference_ready.obd_rpm_stale");
    }
    return t("dashboard.capture_readiness.reference_ready.ready");
  }

  if (check.check_key === "speed_stable") {
    const dwellRemaining = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "dwell_remaining_s") ?? 0),
    );
    const minimumSpeed = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "minimum_speed_kmh") ?? 20),
    );
    if (check.reason_key === "speed_sample_missing") {
      return t("dashboard.capture_readiness.speed_stable.speed_sample_missing");
    }
    if (check.reason_key === "speed_too_low") {
      return t("dashboard.capture_readiness.speed_stable.speed_too_low", {
        minimumSpeed: formatInt(minimumSpeed),
      });
    }
    if (check.reason_key === "speed_stabilizing") {
      return t("dashboard.capture_readiness.speed_stable.speed_stabilizing", {
        seconds: formatInt(dwellRemaining),
      });
    }
    if (check.reason_key === "speed_variation_high") {
      return t("dashboard.capture_readiness.speed_stable.speed_variation_high");
    }
    return t("dashboard.capture_readiness.speed_stable.ready");
  }

  if (check.reason_key === "capture_blocked") {
    return t("dashboard.capture_readiness.capture_ready.capture_blocked");
  }
  if (check.reason_key === "ready_with_warnings") {
    return t("dashboard.capture_readiness.capture_ready.ready_with_warnings");
  }
  return t("dashboard.capture_readiness.capture_ready.ready");
}

export function captureReadinessSummaryText(
  readiness: CaptureReadinessPayload | null,
  deps: CaptureReadinessTextDeps,
): string {
  if (!readiness) {
    return "";
  }
  const primaryCheck = readiness.is_ready
    ? readiness.checks.find((check) => check.state === "warn" && check.check_key !== "capture_ready")
    : readiness.checks.find((check) => check.state === "fail" && check.check_key !== "capture_ready");
  if (primaryCheck) {
    return captureReadinessDetailText(primaryCheck, deps);
  }
  if (readiness.is_ready) {
    return "";
  }
  const overallCheck = captureReadinessCheck(readiness, "capture_ready");
  return overallCheck ? captureReadinessDetailText(overallCheck, deps) : "";
}

function setupRecordingAction(
  check: CaptureReadinessCheckPayload,
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel["action"] | undefined {
  const { t } = deps;
  if (check.check_key === "sensors_ready") {
    return {
      action: "open-sensors",
      labelText: t("dashboard.logging.blocked.setup.action.sensors"),
    };
  }
  if (check.check_key === "reference_ready") {
    if (check.reason_key === "active_car_missing" || check.reason_key === "order_reference_incomplete") {
      return {
        action: "open-cars",
        labelText: t("dashboard.logging.blocked.setup.action.cars"),
      };
    }
    return {
      action: "open-speed-source",
      labelText: t("dashboard.logging.blocked.setup.action.speed_source"),
    };
  }
  if (check.check_key === "speed_stable" && check.reason_key === "speed_sample_missing") {
    return {
      action: "open-speed-source",
      labelText: t("dashboard.logging.blocked.setup.action.speed_source"),
    };
  }
  return undefined;
}

function buildBlockedRecordingPanel(
  blockReason: "no_cars" | "no_active",
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel {
  const { t } = deps;
  if (blockReason === "no_cars") {
    return {
      titleText: t("dashboard.logging.blocked.no_cars.title"),
      bodyText: t("dashboard.logging.blocked.no_cars.body"),
      detailText: t("dashboard.logging.blocked.no_cars.detail"),
      action: {
        action: "open-add-car",
        labelText: t("dashboard.logging.blocked.no_cars.action"),
        variant: "success",
      },
    };
  }
  return {
    titleText: t("dashboard.logging.blocked.no_active.title"),
    bodyText: t("dashboard.logging.blocked.no_active.body"),
    detailText: t("dashboard.logging.blocked.no_active.detail"),
    action: {
      action: "open-cars",
      labelText: t("dashboard.logging.blocked.no_active.action"),
    },
  };
}

function buildSetupRecordingPanel(
  readiness: CaptureReadinessPayload | null,
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel | null {
  if (!readiness || readiness.is_ready) {
    return null;
  }
  const primaryCheck = readiness.checks.find((check) => (
    check.state === "fail" && check.check_key !== "capture_ready"
  )) ?? captureReadinessCheck(readiness, "capture_ready");
  if (!primaryCheck) {
    return null;
  }
  return {
    titleText: deps.t("dashboard.logging.blocked.setup.title"),
    bodyText: captureReadinessDetailText(primaryCheck, deps),
    action: setupRecordingAction(primaryCheck, deps),
  };
}

function buildPostRunSummaryPanel(
  kind: "processing" | "saved",
  runId: string,
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel {
  const { t } = deps;
  if (kind === "processing") {
    return {
      titleText: t("dashboard.logging.processing.title", { runId }),
      bodyText: t("dashboard.logging.processing.body"),
      detailText: t("dashboard.logging.processing.detail"),
      action: {
        action: "open-history",
        labelText: t("dashboard.logging.processing.action"),
      },
    };
  }
  return {
    titleText: t("dashboard.logging.saved.title", { runId }),
    bodyText: t("dashboard.logging.saved.body"),
    detailText: t("dashboard.logging.saved.detail"),
    action: {
      action: "open-history",
      labelText: t("dashboard.logging.saved.action"),
    },
  };
}

export function buildRealtimeCaptureReadinessChecklistModel(
  readiness: CaptureReadinessPayload | null,
  params: CaptureReadinessTextDeps & { setupMode: boolean },
): RealtimeCaptureReadinessChecklistModel | null {
  if (!readiness) {
    return null;
  }
  const items = CAPTURE_READINESS_ORDER
    .filter((checkKey) => checkKey !== "capture_ready")
    .map((checkKey) => captureReadinessCheck(readiness, checkKey))
    .filter((check): check is CaptureReadinessCheckPayload => (
      check !== null && (!params.setupMode || check.state !== "pass")
    ))
    .map((check) => ({
      checkKey: check.check_key,
      state: check.state,
      labelText: captureReadinessCheckLabel(check.check_key, params),
      stateText: captureReadinessStateText(check.state, params),
      detailText: captureReadinessDetailText(check, params),
    }));
  if (!items.length) {
    return null;
  }
  return {
    titleText: params.t("dashboard.capture_readiness.title"),
    items,
  };
}

export function buildRealtimeLoggingPanelViewModel(
  params: BuildRealtimeLoggingPanelViewModelParams,
): RealtimeLoggingPanelViewModel {
  const {
    status,
    pendingLoggingAction,
    selectionBlockReason,
    liveHealth,
    connectedCountText,
    assignedCountText,
    runIdText,
    elapsedText,
    samplesText,
    t,
    formatInt,
  } = params;
  const captureReadiness = status.capture_readiness ?? null;
  const recordingReady = Boolean(captureReadiness?.is_ready);
  const readinessSummary = captureReadinessSummaryText(captureReadiness, { t, formatInt });
  let nextLastCompletedElapsedText = params.lastCompletedElapsedText;

  if (status.enabled) {
    nextLastCompletedElapsedText = elapsedText;
  } else if (!status.analysis_in_progress && !status.last_completed_run_id) {
    nextLastCompletedElapsedText = "--";
  }

  if (pendingLoggingAction === "starting") {
    return {
      pillVariant: "muted",
      pillText: t("dashboard.recording_phase.starting"),
      phaseText: t("dashboard.recording_phase.starting"),
      summaryText: t("dashboard.logging.starting"),
      summaryPanel: null,
      runIdText,
      elapsedText: "--",
      samplesText,
      showStart: true,
      showStop: false,
      startDisabled: true,
      stopDisabled: true,
      showPill: true,
      checklist: null,
      setupMode: false,
      nextLastCompletedElapsedText,
    };
  }

  if (pendingLoggingAction === "stopping") {
    return {
      pillVariant: "warn",
      pillText: t("dashboard.recording_phase.stopping"),
      phaseText: t("dashboard.recording_phase.stopping"),
      summaryText: t("dashboard.logging.stopping"),
      summaryPanel: null,
      runIdText,
      elapsedText,
      samplesText,
      showStart: false,
      showStop: true,
      startDisabled: true,
      stopDisabled: true,
      showPill: true,
      checklist: null,
      setupMode: false,
      nextLastCompletedElapsedText,
    };
  }

  if (status.enabled) {
    return {
      pillVariant: status.write_error ? "bad" : "ok",
      pillText: status.write_error || t("dashboard.recording_phase.recording"),
      phaseText: status.write_error ? t("dashboard.health.attention") : t("dashboard.recording_phase.recording"),
      summaryText: liveHealth.variant === "ok"
        ? t("dashboard.logging.running", { connected: connectedCountText, assigned: assignedCountText })
        : liveHealth.summary,
      summaryPanel: null,
      runIdText,
      elapsedText,
      samplesText,
      showStart: false,
      showStop: true,
      startDisabled: true,
      stopDisabled: false,
      showPill: Boolean(status.write_error),
      checklist: null,
      setupMode: false,
      nextLastCompletedElapsedText,
    };
  }

  if (status.analysis_in_progress) {
    const runId = status.last_completed_run_id ?? t("status.unavailable");
    return {
      pillVariant: "warn",
      pillText: t("dashboard.recording_phase.processing"),
      phaseText: t("dashboard.recording_phase.processing"),
      summaryText: "",
      summaryPanel: buildPostRunSummaryPanel("processing", runId, { t, formatInt }),
      runIdText,
      elapsedText: nextLastCompletedElapsedText,
      samplesText,
      showStart: true,
      showStop: false,
      startDisabled: !recordingReady,
      stopDisabled: true,
      showPill: false,
      checklist: null,
      setupMode: false,
      nextLastCompletedElapsedText,
    };
  }

  if (status.last_completed_run_id) {
    return {
      pillVariant: "ok",
      pillText: t("dashboard.recording_phase.saved"),
      phaseText: t("dashboard.recording_phase.saved"),
      summaryText: "",
      summaryPanel: buildPostRunSummaryPanel("saved", status.last_completed_run_id, { t, formatInt }),
      runIdText,
      elapsedText: nextLastCompletedElapsedText,
      samplesText,
      showStart: true,
      showStop: false,
      startDisabled: !recordingReady,
      stopDisabled: true,
      showPill: false,
      checklist: null,
      setupMode: false,
      nextLastCompletedElapsedText,
    };
  }

  if (selectionBlockReason) {
    return {
      pillVariant: "warn",
      pillText: t("dashboard.recording_phase.blocked"),
      phaseText: t("dashboard.recording_phase.blocked"),
      summaryText: readinessSummary,
      summaryPanel: buildBlockedRecordingPanel(selectionBlockReason, { t, formatInt }),
      runIdText,
      elapsedText: "--",
      samplesText,
      showStart: true,
      showStop: false,
      startDisabled: true,
      stopDisabled: true,
      showPill: false,
      checklist: null,
      setupMode: true,
      nextLastCompletedElapsedText,
    };
  }

  const waitingOnReadiness = captureReadiness !== null && !captureReadiness.is_ready;
  return {
    pillVariant: waitingOnReadiness ? "muted" : "ok",
    pillText: waitingOnReadiness
      ? t("dashboard.recording_phase.preparing")
      : t("dashboard.recording_phase.ready"),
    phaseText: waitingOnReadiness
      ? t("dashboard.recording_phase.preparing")
      : t("dashboard.recording_phase.ready"),
    summaryText: waitingOnReadiness ? "" : readinessSummary || liveHealth.summary,
    summaryPanel: waitingOnReadiness ? buildSetupRecordingPanel(captureReadiness, { t, formatInt }) : null,
    runIdText,
    elapsedText: "--",
    samplesText,
    showStart: true,
    showStop: false,
    startDisabled: !recordingReady,
    stopDisabled: true,
    showPill: false,
    checklist: buildRealtimeCaptureReadinessChecklistModel(captureReadiness, {
      setupMode: waitingOnReadiness,
      t,
      formatInt,
    }),
    setupMode: waitingOnReadiness,
    nextLastCompletedElapsedText,
  };
}
