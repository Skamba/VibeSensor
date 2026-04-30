import type { HealthStatusPayload } from "../../api/types";
import { formatEpochTimestamp } from "../../format";
import type {
  UpdateHealthSectionModel,
  UpdateStatusBadgeModel,
  UpdateStatusBadgeVariant,
  UpdateStatusRowModel,
  UpdateStatusViewDeps,
} from "./update_status_models";
import { buildStatusRow, formatDuration } from "./update_status_shared";

const HEALTH_VARIANT: Readonly<
  Record<HealthStatusPayload["status"], UpdateStatusBadgeVariant>
> = {
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
  persistence_write_error:
    "settings.update.health.reason.persistence_write_error",
};

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
    !health.persistence.analysis_in_progress &&
    !health.persistence.write_error &&
    analysisQueueDepth <= 0
  ) {
    return [];
  }
  const rows = [
    buildStatusRow(
      t("settings.update.health.persistence"),
      health.persistence.write_error ||
        t("settings.update.health.persistence_ok"),
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
    variant: health.persistence.write_error
      ? "bad"
      : HEALTH_VARIANT[health.status],
    text: t(`settings.update.health.state.${health.status}`),
  };
}

function buildHealthSummaryText(
  health: HealthStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const key =
    health.persistence.write_error || health.status === "degraded"
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
