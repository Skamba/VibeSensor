import type {
  HealthStatusPayload,
  UpdateIssue,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
} from "../../transport/http_models";
import { formatEpochTimestamp } from "./dom_helpers";

const STATE_VARIANT: Readonly<Record<UpdateStatusPayload["state"], UpdateStatusBadgeVariant>> = {
  idle: "muted",
  running: "warn",
  success: "ok",
  failed: "bad",
};

const HEALTH_VARIANT: Readonly<Record<HealthStatusPayload["status"], UpdateStatusBadgeVariant>> = {
  ok: "ok",
  warn: "warn",
  degraded: "warn",
};

const HEALTH_REASON_KEYS: Readonly<Record<string, string>> = {
  processing_failures: "settings.update.health.reason.processing_failures",
  frames_dropped: "settings.update.health.reason.frames_dropped",
  queue_overflow_drops: "settings.update.health.reason.queue_overflow_drops",
  server_queue_drops: "settings.update.health.reason.server_queue_drops",
  parse_errors: "settings.update.health.reason.parse_errors",
  persistence_write_error: "settings.update.health.reason.persistence_write_error",
};

const ASSET_ISSUE_RE = /asset|artifacts|stale|hash|missing/i;

type JourneyStageState = "upcoming" | "active" | "done" | "attention";
type UpdateJourneyTransport = UpdateStartRequestPayload["transport"];

export interface UpdateFailureSummary {
  detail: string | null;
  message: string | null;
  phaseLabel: string;
  recoveryDetail: string;
  recoveryTitle: string;
}

type UpdateJourneyStage = {
  phase: string;
  titleKey: string;
  detailKey: string;
};

const WIFI_JOURNEY_STAGES: readonly UpdateJourneyStage[] = [
  {
    phase: "validating",
    titleKey: "settings.update.phase.validating",
    detailKey: "settings.update.journey.detail.validating",
  },
  {
    phase: "stopping_hotspot",
    titleKey: "settings.update.phase.stopping_hotspot",
    detailKey: "settings.update.journey.detail.stopping_hotspot",
  },
  {
    phase: "connecting_wifi",
    titleKey: "settings.update.phase.connecting_wifi",
    detailKey: "settings.update.journey.detail.connecting_wifi",
  },
  {
    phase: "checking",
    titleKey: "settings.update.phase.checking",
    detailKey: "settings.update.journey.detail.checking",
  },
  {
    phase: "downloading",
    titleKey: "settings.update.phase.downloading",
    detailKey: "settings.update.journey.detail.downloading",
  },
  {
    phase: "installing",
    titleKey: "settings.update.phase.installing",
    detailKey: "settings.update.journey.detail.installing",
  },
  {
    phase: "restoring_hotspot",
    titleKey: "settings.update.phase.restoring_hotspot",
    detailKey: "settings.update.journey.detail.restoring_hotspot",
  },
  {
    phase: "done",
    titleKey: "settings.update.phase.done",
    detailKey: "settings.update.journey.detail.done",
  },
] as const;

const USB_JOURNEY_STAGES: readonly UpdateJourneyStage[] = [
  {
    phase: "validating",
    titleKey: "settings.update.phase.validating",
    detailKey: "settings.update.journey.detail.validating",
  },
  {
    phase: "connecting_usb_internet",
    titleKey: "settings.update.phase.connecting_usb_internet",
    detailKey: "settings.update.journey.detail.connecting_usb_internet",
  },
  {
    phase: "checking",
    titleKey: "settings.update.phase.checking",
    detailKey: "settings.update.journey.detail.checking",
  },
  {
    phase: "downloading",
    titleKey: "settings.update.phase.downloading",
    detailKey: "settings.update.journey.detail.downloading",
  },
  {
    phase: "installing",
    titleKey: "settings.update.phase.installing",
    detailKey: "settings.update.journey.detail.installing",
  },
  {
    phase: "done",
    titleKey: "settings.update.phase.done",
    detailKey: "settings.update.journey.detail.done",
  },
] as const;

export interface UpdateStatusViewDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  selectedTransport: UpdateJourneyTransport;
}

export type UpdateStatusBadgeVariant = "muted" | "warn" | "ok" | "bad";

export interface UpdateStatusBadgeModel {
  variant: UpdateStatusBadgeVariant;
  text: string;
}

export interface UpdateStatusRowModel {
  labelText: string;
  valueText: string;
}

export interface UpdateCurrentStatusSectionModel {
  titleText: string;
  summaryText: string;
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
  emptyText: string | null;
}

export interface UpdateJourneyFailureNoteModel {
  summaryText: string;
  detailText: string | null;
  recoveryTitleText: string;
  recoveryDetailText: string;
}

export interface UpdateJourneyStageModel {
  phase: string;
  titleText: string;
  detailText: string;
  markerText: string;
  state: JourneyStageState;
  stateText: string;
  current: boolean;
}

export interface UpdateJourneySectionModel {
  titleText: string;
  subtitleText: string;
  failureNote: UpdateJourneyFailureNoteModel | null;
  stages: readonly UpdateJourneyStageModel[];
}

export interface UpdateIssueSectionItemModel {
  phaseText: string;
  messageText: string;
  detailText: string | null;
}

export interface UpdateIssuesSectionModel {
  titleText: string;
  subtitleText: string;
  items: readonly UpdateIssueSectionItemModel[];
}

export interface UpdateLatestAttemptFailureNoteModel {
  summaryText: string;
  detailText: string | null;
}

export interface UpdateLatestAttemptSectionModel {
  titleText: string;
  subtitleText: string;
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
  failureNote: UpdateLatestAttemptFailureNoteModel | null;
}

export interface UpdateHealthSectionModel {
  titleText: string;
  summaryText: string;
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
}

export interface UpdateLogEmptyStateModel {
  titleText: string;
  bodyText: string;
}

export interface UpdateLogSectionModel {
  titleText: string;
  subtitleText: string;
  noteText: string | null;
  lines: readonly string[];
  emptyState: UpdateLogEmptyStateModel | null;
}

export interface UpdateStatusPanelViewModel {
  currentStatus: UpdateCurrentStatusSectionModel;
  journey: UpdateJourneySectionModel;
  issues: UpdateIssuesSectionModel | null;
  latestAttempt: UpdateLatestAttemptSectionModel | null;
  health: UpdateHealthSectionModel;
  log: UpdateLogSectionModel;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function buildStatusRow(labelText: string, valueText: string): UpdateStatusRowModel {
  return { labelText, valueText };
}

function formatHealthReason(
  reason: string,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  if (reason.startsWith("processing_state:")) {
    const state = reason.slice("processing_state:".length);
    return `${t("settings.update.health.reason.processing_state")} ${state}`;
  }
  const key = HEALTH_REASON_KEYS[reason];
  return key ? t(key) : reason;
}

function translateKeyOrFallback(
  key: string,
  fallback: string,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const translated = t(key);
  return translated === key ? fallback : translated;
}

function normalizeUpdatePhase(phase: string | null | undefined): string {
  if (!phase) return "idle";
  if (phase === "restore") return "restoring_hotspot";
  return phase;
}

export function formatUpdatePhase(
  phase: string | null | undefined,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const normalized = normalizeUpdatePhase(phase);
  return translateKeyOrFallback(`settings.update.phase.${normalized}`, normalized, t);
}

function buildStateBadge(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusBadgeModel {
  return {
    variant: STATE_VARIANT[status.state] ?? "muted",
    text: t(`settings.update.state.${status.state}`),
  };
}

function buildCurrentStatusSummaryText(
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  let key = "settings.update.current_status_summary.ready";
  if (status.state === "running") {
    key = "settings.update.current_status_summary.running";
  } else if (status.state === "failed") {
    key = "settings.update.current_status_summary.failed";
  } else if (status.state === "success") {
    key = "settings.update.current_status_summary.success";
  } else if (health.status !== "ok" || health.persistence.write_error) {
    key = "settings.update.current_status_summary.attention";
  }
  return t(key);
}

function buildTransportValueText(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  if (status.transport === "usb_internet") {
    return status.uplink_interface
      ? t("settings.update.transport_value.usb_interface", {
          interface: status.uplink_interface,
        })
      : t("settings.update.transport_value.usb");
  }
  if (status.ssid) {
    return t("settings.update.transport_value.wifi_ssid", { ssid: status.ssid });
  }
  return t("settings.update.transport_value.wifi");
}

function buildLifecycleRows(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusRowModel[] {
  const rows: UpdateStatusRowModel[] = [];
  if (status.transport === "usb_internet" || status.ssid) {
    rows.push(
      buildStatusRow(
        t("settings.update.transport_label"),
        buildTransportValueText(status, t),
      ),
    );
  }
  if (status.state !== "idle") {
    rows.push(
      buildStatusRow(
        t("settings.update.phase_label"),
        formatUpdatePhase(status.phase, t),
      ),
    );
  }
  if (status.started_at != null) {
    rows.push(
      buildStatusRow(
        t("settings.update.started_at"),
        formatEpochTimestamp(status.started_at),
      ),
    );
  }
  if (status.phase_started_at != null && status.state !== "idle") {
    rows.push(
      buildStatusRow(
        t("settings.update.phase_started_at"),
        formatEpochTimestamp(status.phase_started_at),
      ),
    );
  }
  if (status.state !== "idle" && status.phase_elapsed_s != null) {
    rows.push(
      buildStatusRow(
        t("settings.update.phase_elapsed"),
        formatDuration(status.phase_elapsed_s),
      ),
    );
  }
  if (status.finished_at != null) {
    rows.push(
      buildStatusRow(
        t("settings.update.finished_at"),
        formatEpochTimestamp(status.finished_at),
      ),
    );
  }
  if (status.last_success_at != null) {
    rows.push(
      buildStatusRow(
        t("settings.update.last_success"),
        formatEpochTimestamp(status.last_success_at),
      ),
    );
  }
  return rows;
}

function buildRuntimeRows(
  status: UpdateStatusPayload,
  showRuntimeAssetsCheck: boolean,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusRowModel[] {
  const rows: UpdateStatusRowModel[] = [];
  if (status.runtime?.version && status.runtime.version !== "unknown") {
    rows.push(
      buildStatusRow(
        t("settings.update.runtime_version"),
        status.runtime.version,
      ),
    );
  }
  if (status.runtime?.commit) {
    rows.push(
      buildStatusRow(
        t("settings.update.runtime_commit"),
        status.runtime.commit.slice(0, 12),
      ),
    );
  }
  if (!status.runtime?.static_assets_hash) return rows;
  rows.push(
    buildStatusRow(
      t("settings.update.runtime_assets"),
      status.runtime.static_assets_hash.slice(0, 12),
    ),
  );
  if (showRuntimeAssetsCheck) {
    rows.push(
      buildStatusRow(
        t("settings.update.runtime_assets_check"),
        t(
          status.runtime.assets_verified
            ? "settings.update.runtime_assets_ok"
            : "settings.update.runtime_assets_bad",
        ),
      ),
    );
  }
  return rows;
}

function hasAssetRelatedIssue(status: UpdateStatusPayload): boolean {
  return status.issues.some((issue) => ASSET_ISSUE_RE.test(`${issue.message} ${issue.detail}`));
}

export function buildUpdateCurrentStatusSectionModel(
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateCurrentStatusSectionModel {
  const showRuntimeAssetsCheck = status.state !== "failed" || hasAssetRelatedIssue(status);
  const rows = [
    ...buildLifecycleRows(status, deps.t),
    ...buildRuntimeRows(status, showRuntimeAssetsCheck, deps.t),
  ];
  return {
    titleText: deps.t("settings.update.current_status_title"),
    summaryText: buildCurrentStatusSummaryText(status, health, deps.t),
    badge: buildStateBadge(status, deps.t),
    rows,
    emptyText: rows.length > 0 ? null : deps.t("settings.update.current_status_empty"),
  };
}

function journeyStages(transport: UpdateJourneyTransport): readonly UpdateJourneyStage[] {
  return transport === "usb_internet" ? USB_JOURNEY_STAGES : WIFI_JOURNEY_STAGES;
}

function resolvedJourneyTransport(
  status: UpdateStatusPayload,
  selectedTransport: UpdateJourneyTransport,
): UpdateJourneyTransport {
  if (status.state === "idle") {
    return selectedTransport;
  }
  return status.transport === "usb_internet" ? "usb_internet" : "wifi";
}

function journeyStageIndex(
  phase: string | null | undefined,
  stages: readonly UpdateJourneyStage[],
): number {
  const normalized = normalizeUpdatePhase(phase);
  return stages.findIndex((stage) => stage.phase === normalized);
}

function resolveJourneyStageState(
  status: UpdateStatusPayload,
  stages: readonly UpdateJourneyStage[],
  stageIndex: number,
): JourneyStageState {
  if (status.state === "success") return "done";
  if (status.state === "idle") return "upcoming";
  const currentIndex = journeyStageIndex(status.phase, stages);
  if (currentIndex === -1) {
    return "upcoming";
  }
  if (stageIndex < currentIndex) return "done";
  if (stageIndex === currentIndex) {
    return status.state === "failed" ? "attention" : "active";
  }
  return "upcoming";
}

function primaryJourneyIssue(status: UpdateStatusPayload): UpdateIssue | null {
  const currentPhase = normalizeUpdatePhase(status.phase);
  for (let index = status.issues.length - 1; index >= 0; index -= 1) {
    const issue = status.issues[index];
    if (normalizeUpdatePhase(issue.phase) === currentPhase) {
      return issue;
    }
  }
  return status.issues.length > 0 ? status.issues[status.issues.length - 1] : null;
}

function recoveryGuidanceKey(phase: string): string {
  switch (normalizeUpdatePhase(phase)) {
    case "stopping_hotspot":
    case "connecting_wifi":
    case "restoring_hotspot":
      return "settings.update.recovery.wifi";
    case "connecting_usb_internet":
      return "settings.update.recovery.usb";
    case "checking":
    case "downloading":
      return "settings.update.recovery.network";
    case "installing":
      return "settings.update.recovery.install";
    default:
      return "settings.update.recovery.generic";
  }
}

export function getUpdateFailureSummary(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateFailureSummary | null {
  if (status.state !== "failed") {
    return null;
  }
  const issue = primaryJourneyIssue(status);
  const phase = issue?.phase ?? status.phase;
  const keyBase = recoveryGuidanceKey(phase);
  return {
    detail: issue?.detail ?? null,
    message: issue?.message ?? null,
    phaseLabel: formatUpdatePhase(phase, t),
    recoveryTitle: t(`${keyBase}.title`),
    recoveryDetail: t(`${keyBase}.detail`),
  };
}

function buildJourneyFailureNoteModel(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateJourneyFailureNoteModel | null {
  const failure = getUpdateFailureSummary(status, t);
  if (!failure) {
    return null;
  }
  return {
    summaryText: failure.message ? `${failure.phaseLabel} — ${failure.message}` : failure.phaseLabel,
    detailText: failure.detail,
    recoveryTitleText: failure.recoveryTitle,
    recoveryDetailText: failure.recoveryDetail,
  };
}

export function buildUpdateJourneySectionModel(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateJourneySectionModel {
  const stages = journeyStages(resolvedJourneyTransport(status, deps.selectedTransport));
  return {
    titleText: deps.t("settings.update.journey_title"),
    subtitleText: deps.t("settings.update.journey_intro"),
    failureNote: buildJourneyFailureNoteModel(status, deps.t),
    stages: stages.map((stage, index) => {
      const state = resolveJourneyStageState(status, stages, index);
      return {
        phase: stage.phase,
        titleText: deps.t(stage.titleKey),
        detailText: deps.t(stage.detailKey),
        markerText: state === "done" ? "✓" : `${index + 1}`,
        state,
        stateText: deps.t(`maintenance.stage_state.${state}`),
        current: state === "active",
      };
    }),
  };
}

export function buildUpdateIssuesSectionModel(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateIssuesSectionModel | null {
  if (status.issues.length === 0) {
    return null;
  }
  return {
    titleText: deps.t("settings.update.issues"),
    subtitleText: deps.t("settings.update.issues_intro"),
    items: status.issues.map((issue) => ({
      phaseText: formatUpdatePhase(issue.phase, deps.t),
      messageText: issue.message,
      detailText: issue.detail ?? null,
    })),
  };
}

export function buildUpdateLatestAttemptSectionModel(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateLatestAttemptSectionModel | null {
  if (status.state === "idle" || status.state === "running") {
    return null;
  }
  const rows: UpdateStatusRowModel[] = [];
  if (status.started_at != null) {
    rows.push(
      buildStatusRow(
        deps.t("settings.update.started_at"),
        formatEpochTimestamp(status.started_at),
      ),
    );
  }
  if (status.finished_at != null) {
    rows.push(
      buildStatusRow(
        deps.t("settings.update.finished_at"),
        formatEpochTimestamp(status.finished_at),
      ),
    );
  }
  rows.push(
    buildStatusRow(
      deps.t("settings.update.transport_label"),
      buildTransportValueText(status, deps.t),
    ),
  );
  if (status.exit_code != null) {
    rows.push(
      buildStatusRow(
        deps.t("settings.update.exit_code"),
        String(status.exit_code),
      ),
    );
  }
  const failure = getUpdateFailureSummary(status, deps.t);
  return {
    titleText: deps.t("settings.update.attempt_title"),
    subtitleText: deps.t("settings.update.attempt_intro"),
    badge: buildStateBadge(status, deps.t),
    rows,
    failureNote: failure
      ? {
          summaryText: failure.message ?? failure.phaseLabel,
          detailText: failure.detail,
        }
      : null,
  };
}

function buildHealthSummaryRows(
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusRowModel[] {
  const rows = [
    buildStatusRow(
      t("settings.update.health.processing_state"),
      health.processing_state,
    ),
  ];
  if (health.processing_failures > 0) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.processing_failures"),
        String(health.processing_failures),
      ),
    );
  }
  if (health.degradation_reasons.length) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.reasons"),
        health.degradation_reasons
          .map((reason) => formatHealthReason(reason, t))
          .join(", "),
      ),
    );
  }
  return rows;
}

function buildHealthDataLossRows(
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusRowModel[] {
  if (health.data_loss.affected_clients <= 0) {
    return [];
  }
  return [
    buildStatusRow(
      t("settings.update.health.affected_clients"),
      `${health.data_loss.affected_clients}/${health.data_loss.tracked_clients}`,
    ),
    buildStatusRow(
      t("settings.update.health.data_loss"),
      [
        `frames=${health.data_loss.frames_dropped}`,
        `queue=${health.data_loss.queue_overflow_drops}`,
        `server=${health.data_loss.server_queue_drops}`,
        `parse=${health.data_loss.parse_errors}`,
      ].join(", "),
    ),
  ];
}

function buildHealthPersistenceRows(
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusRowModel[] {
  const analysisQueueDepth = health.persistence.analysis_queue_depth ?? 0;
  if (
    !health.persistence.analysis_in_progress
    && !health.persistence.write_error
    && analysisQueueDepth <= 0
  ) {
    return [];
  }
  const rows = [
    buildStatusRow(
      t("settings.update.health.persistence"),
      health.persistence.write_error || t("settings.update.health.persistence_ok"),
    ),
  ];
  if (health.persistence.analysis_in_progress) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.analysis"),
        t("settings.update.health.analysis_in_progress"),
      ),
    );
  }
  if (health.persistence.analysis_active_run_id) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.analysis_run"),
        health.persistence.analysis_active_run_id,
      ),
    );
  }
  if (health.persistence.analysis_started_at != null) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.analysis_started_at"),
        formatEpochTimestamp(health.persistence.analysis_started_at),
      ),
    );
  }
  if (health.persistence.analysis_elapsed_s != null) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.analysis_elapsed"),
        formatDuration(health.persistence.analysis_elapsed_s),
      ),
    );
  }
  if (analysisQueueDepth > 0) {
    rows.push(
      buildStatusRow(
        t("settings.update.health.analysis_queue_depth"),
        String(analysisQueueDepth),
      ),
    );
  }
  return rows;
}

function buildHealthBadge(
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusBadgeModel {
  return {
    variant: health.persistence.write_error ? "bad" : HEALTH_VARIANT[health.status],
    text: t(`settings.update.health.state.${health.status}`),
  };
}

function buildHealthSummaryText(
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const key = health.persistence.write_error || health.status === "degraded"
    ? "settings.update.health_card_summary.degraded"
    : health.status === "warn"
      ? "settings.update.health_card_summary.warn"
      : "settings.update.health_card_summary.ok";
  return t(key);
}

export function buildUpdateHealthSectionModel(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateHealthSectionModel {
  return {
    titleText: deps.t("settings.update.health_card_title"),
    summaryText: buildHealthSummaryText(health, deps.t),
    badge: buildHealthBadge(health, deps.t),
    rows: [
      ...buildHealthSummaryRows(health, deps.t),
      ...buildHealthDataLossRows(health, deps.t),
      ...buildHealthPersistenceRows(health, deps.t),
    ],
  };
}

export function buildUpdateLogSectionModel(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateLogSectionModel {
  const isRunning = status.state === "running";
  if (status.log_tail.length === 0) {
    return {
      titleText: deps.t("settings.update.log"),
      subtitleText: deps.t(
        isRunning ? "settings.update.log_intro_running" : "settings.update.log_intro",
      ),
      noteText: null,
      lines: [],
      emptyState: {
        titleText: isRunning
          ? deps.t("settings.update.log_running_title")
          : status.state === "failed"
            ? deps.t("settings.update.log_failed_title")
            : deps.t("settings.update.log_empty_title"),
        bodyText: isRunning
          ? deps.t("settings.update.log_running_body")
          : status.state === "failed"
            ? deps.t("settings.update.log_failed_body")
            : deps.t("settings.update.log_empty_body"),
      },
    };
  }
  return {
    titleText: deps.t("settings.update.log"),
    subtitleText: deps.t(
      isRunning ? "settings.update.log_intro_running" : "settings.update.log_intro",
    ),
    noteText: isRunning ? deps.t("settings.update.log_running_note") : null,
    lines: [...status.log_tail],
    emptyState: null,
  };
}

export function buildUpdateStatusPanelViewModel(
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateStatusPanelViewModel {
  return {
    currentStatus: buildUpdateCurrentStatusSectionModel(status, health, deps),
    journey: buildUpdateJourneySectionModel(status, deps),
    issues: buildUpdateIssuesSectionModel(status, deps),
    latestAttempt: buildUpdateLatestAttemptSectionModel(status, deps),
    health: buildUpdateHealthSectionModel(health, deps),
    log: buildUpdateLogSectionModel(status, deps),
  };
}
