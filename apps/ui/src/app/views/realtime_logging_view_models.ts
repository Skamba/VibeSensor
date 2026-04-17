import type { LiveHealth } from "../features/realtime_sensor_state";
import type { LoggingStatusPayload } from "../../api/types";
import {
  buildRealtimeCaptureReadinessChecklistModel,
  captureReadinessSummaryText,
  type CaptureReadinessTextDeps,
  type RealtimeCaptureReadinessChecklistModel,
} from "./realtime_capture_readiness_models";
import {
  buildBlockedRecordingPanel,
  buildPostRunSummaryPanel,
  buildSetupRecordingPanel,
  type RealtimeLoggingSummaryPanelModel,
} from "./realtime_logging_summary_models";

export {
  buildRealtimeCaptureReadinessChecklistModel,
  captureReadinessCheck,
  captureReadinessSummaryText,
  type CaptureReadinessCheckPayload,
  type CaptureReadinessPayload,
  type RealtimeCaptureReadinessChecklistItemModel,
  type RealtimeCaptureReadinessChecklistModel,
} from "./realtime_capture_readiness_models";
export {
  REALTIME_LOGGING_SUMMARY_ACTIONS,
  type RealtimeLoggingSummaryAction,
  type RealtimeLoggingSummaryPanelModel,
} from "./realtime_logging_summary_models";

export type RealtimeLoggingPendingAction = "starting" | "stopping" | null;

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
