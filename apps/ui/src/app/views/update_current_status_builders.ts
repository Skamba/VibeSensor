import type {
  HealthStatusPayload,
  UpdateStatusPayload,
} from "../../api/types";
import { formatEpochTimestamp } from "../../format";
import {
  getUpdateFailureSummary,
} from "./update_journey_builder";
import type {
  UpdateCurrentStatusSectionModel,
  UpdateIssuesSectionModel,
  UpdateLatestAttemptSectionModel,
  UpdateStatusRowModel,
  UpdateStatusViewDeps,
} from "./update_status_models";
import {
  buildStateBadge,
  buildStatusRow,
  buildTransportValueText,
  formatDuration,
  formatUpdatePhase,
  hasAssetRelatedIssue,
} from "./update_status_shared";

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
