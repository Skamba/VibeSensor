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
  summaryAction: RealtimeLoggingSummaryPanelModel["action"] | null;
  summaryHidden: boolean;
  summaryLayout: "panel" | undefined;
  runIdText: string;
  runIdHidden: boolean;
  elapsedText: string;
  samplesText: string;
  showStart: boolean;
  startHidden: boolean;
  showStop: boolean;
  stopHidden: boolean;
  startDisabled: boolean;
  stopDisabled: boolean;
  showPill: boolean;
  pillHidden: boolean;
  loggingRowHidden: boolean;
  checklist: RealtimeCaptureReadinessChecklistModel | null;
  checklistHidden: boolean;
  setupMode: boolean;
  showProgressSection: boolean;
  shellLayout: "setup" | undefined;
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
  const readinessSummary = captureReadinessSummaryText(captureReadiness, {
    t,
    formatInt,
  });
  function finalize(model: {
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
  }): RealtimeLoggingPanelViewModel {
    const summaryAction = model.summaryPanel?.action ?? null;
    const summaryHidden =
      model.summaryText === "" && model.summaryPanel === null;
    const summaryLayout = model.summaryPanel ? "panel" : undefined;
    const runIdHidden = model.runIdText === "";
    const startHidden = !model.showStart;
    const stopHidden = !model.showStop;
    const pillHidden = !model.showPill;
    const loggingRowHidden = pillHidden && runIdHidden;
    const checklistHidden = model.checklist === null;
    const showProgressSection = !model.setupMode || model.checklist !== null;
    const shellLayout = model.setupMode ? "setup" : undefined;
    return {
      ...model,
      summaryAction,
      summaryHidden,
      summaryLayout,
      runIdHidden,
      startHidden,
      stopHidden,
      pillHidden,
      loggingRowHidden,
      checklistHidden,
      showProgressSection,
      shellLayout,
    };
  }
  let nextLastCompletedElapsedText = params.lastCompletedElapsedText;

  if (status.enabled) {
    nextLastCompletedElapsedText = elapsedText;
  } else if (!status.analysis_in_progress && !status.last_completed_run_id) {
    nextLastCompletedElapsedText = "--";
  }

  if (pendingLoggingAction === "starting") {
    return finalize({
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
    });
  }

  if (pendingLoggingAction === "stopping") {
    return finalize({
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
    });
  }

  if (status.enabled) {
    return finalize({
      pillVariant: status.write_error ? "bad" : "ok",
      pillText: status.write_error || t("dashboard.recording_phase.recording"),
      phaseText: status.write_error
        ? t("dashboard.health.attention")
        : t("dashboard.recording_phase.recording"),
      summaryText:
        liveHealth.variant === "ok"
          ? t("dashboard.logging.running", {
              connected: connectedCountText,
              assigned: assignedCountText,
            })
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
    });
  }

  if (status.analysis_in_progress) {
    const runId = status.last_completed_run_id ?? t("status.unavailable");
    return finalize({
      pillVariant: "warn",
      pillText: t("dashboard.recording_phase.processing"),
      phaseText: t("dashboard.recording_phase.processing"),
      summaryText: "",
      summaryPanel: buildPostRunSummaryPanel("processing", runId, {
        t,
        formatInt,
      }),
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
    });
  }

  if (status.last_completed_run_id) {
    return finalize({
      pillVariant: "ok",
      pillText: t("dashboard.recording_phase.saved"),
      phaseText: t("dashboard.recording_phase.saved"),
      summaryText: "",
      summaryPanel: buildPostRunSummaryPanel(
        "saved",
        status.last_completed_run_id,
        { t, formatInt },
      ),
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
    });
  }

  if (selectionBlockReason) {
    return finalize({
      pillVariant: "warn",
      pillText: t("dashboard.recording_phase.blocked"),
      phaseText: t("dashboard.recording_phase.blocked"),
      summaryText: readinessSummary,
      summaryPanel: buildBlockedRecordingPanel(selectionBlockReason, {
        t,
        formatInt,
      }),
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
    });
  }

  const waitingOnReadiness =
    captureReadiness !== null && !captureReadiness.is_ready;
  return finalize({
    pillVariant: waitingOnReadiness ? "muted" : "ok",
    pillText: waitingOnReadiness
      ? t("dashboard.recording_phase.preparing")
      : t("dashboard.recording_phase.ready"),
    phaseText: waitingOnReadiness
      ? t("dashboard.recording_phase.preparing")
      : t("dashboard.recording_phase.ready"),
    summaryText: waitingOnReadiness
      ? ""
      : readinessSummary || liveHealth.summary,
    summaryPanel: waitingOnReadiness
      ? buildSetupRecordingPanel(captureReadiness, { t, formatInt })
      : null,
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
  });
}
