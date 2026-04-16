import type {
  HealthStatusPayload,
  UpdateStatusPayload,
} from "../../transport/http_models";
import { formatEpochTimestamp } from "./dom_helpers";
import {
  buildUpdateJourneySectionModel,
  formatUpdatePhase,
  getUpdateFailureSummary,
} from "./update_journey_builder";
import type {
  UpdateCurrentStatusSectionModel,
  UpdateHealthSectionModel,
  UpdateIssuesSectionModel,
  UpdateLatestAttemptSectionModel,
  UpdateLogSectionModel,
  UpdateStatusBadgeModel,
  UpdateStatusBadgeVariant,
  UpdateStatusPanelViewModel,
  UpdateStatusRowModel,
  UpdateStatusViewDeps,
} from "./update_status_models";

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
