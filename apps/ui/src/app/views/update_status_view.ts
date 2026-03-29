import type { HealthStatusPayload, UpdateStatusPayload } from "../../api/types";
import type { UiDomElements } from "../ui_dom_registry";
import { formatEpochTimestamp, renderStatusGridRow } from "./dom_helpers";

const STATE_VARIANT: Readonly<Record<string, string>> = {
  idle: "muted",
  running: "warn",
  success: "ok",
  failed: "bad",
};

const HEALTH_VARIANT: Readonly<Record<HealthStatusPayload["status"], string>> = {
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

export interface UpdateStatusViewDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
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

function formatUpdatePhase(
  phase: string | null | undefined,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const normalized = normalizeUpdatePhase(phase);
  return translateKeyOrFallback(`settings.update.phase.${normalized}`, normalized, t);
}

function renderInlineEmptyState(
  title: string,
  body: string,
  escapeHtml: (value: unknown) => string,
): string {
  return `<div class="empty-state empty-state--inline"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(body)}</span></div>`;
}

function renderMaintenanceCard(
  titleHtml: string,
  subtitleHtml: string,
  bodyHtml: string,
  badgeHtml = "",
): string {
  return `<section class="maintenance-card"><div class="maintenance-card__header"><div><div class="maintenance-card__title">${titleHtml}</div><div class="subtle">${subtitleHtml}</div></div>${badgeHtml}</div><div class="maintenance-card__body">${bodyHtml}</div></section>`;
}

function renderStateBadge(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  return `<span class="pill pill--${STATE_VARIANT[status.state] || "muted"}">${escapeHtml(t(`settings.update.state.${status.state}`))}</span>`;
}

function renderStateSummary(
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
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
  return escapeHtml(t(key));
}

function renderLifecycleRows(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const rows: string[] = [];
  if (status.transport === "usb_internet" || status.ssid) {
    let transportValue = t("settings.update.transport_value.wifi");
    if (status.transport === "usb_internet") {
      transportValue = status.uplink_interface
        ? t("settings.update.transport_value.usb_interface", {
          interface: status.uplink_interface,
        })
        : t("settings.update.transport_value.usb");
    } else if (status.ssid) {
      transportValue = t("settings.update.transport_value.wifi_ssid", { ssid: status.ssid });
    }
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.transport_label")),
        escapeHtml(transportValue),
      ),
    );
  }
  if (status.state !== "idle") rows.push(renderStatusGridRow(escapeHtml(t("settings.update.phase_label")), escapeHtml(formatUpdatePhase(status.phase, t))));
  if (status.started_at != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.started_at")), escapeHtml(formatEpochTimestamp(status.started_at))));
  if (status.phase_started_at != null && status.state !== "idle") rows.push(renderStatusGridRow(escapeHtml(t("settings.update.phase_started_at")), escapeHtml(formatEpochTimestamp(status.phase_started_at))));
  if (status.state !== "idle" && status.phase_elapsed_s != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.phase_elapsed")), escapeHtml(formatDuration(status.phase_elapsed_s))));
  if (status.finished_at != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.finished_at")), escapeHtml(formatEpochTimestamp(status.finished_at))));
  if (status.last_success_at != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.last_success")), escapeHtml(formatEpochTimestamp(status.last_success_at))));
  return rows.join("");
}

function renderRuntimeRows(
  status: UpdateStatusPayload,
  showRuntimeAssetsCheck: boolean,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const rows: string[] = [];
  if (status.runtime?.version && status.runtime.version !== "unknown") rows.push(renderStatusGridRow(escapeHtml(t("settings.update.runtime_version")), escapeHtml(status.runtime.version)));
  if (status.runtime?.commit) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.runtime_commit")), escapeHtml(status.runtime.commit.slice(0, 12))));
  if (!status.runtime?.static_assets_hash) return rows.join("");
  rows.push(renderStatusGridRow(escapeHtml(t("settings.update.runtime_assets")), escapeHtml(status.runtime.static_assets_hash.slice(0, 12))));
  if (showRuntimeAssetsCheck) {
    rows.push(renderStatusGridRow(
      escapeHtml(t("settings.update.runtime_assets_check")),
      escapeHtml(t(status.runtime.assets_verified ? "settings.update.runtime_assets_ok" : "settings.update.runtime_assets_bad")),
    ));
  }
  return rows.join("");
}

function renderStateGrid(
  status: UpdateStatusPayload,
  showRuntimeAssetsCheck: boolean,
  deps: UpdateStatusViewDeps,
): string {
  const rows = `${renderLifecycleRows(status, deps)}${renderRuntimeRows(status, showRuntimeAssetsCheck, deps)}`;
  if (!rows) {
    return `<div class="maintenance-note">${deps.escapeHtml(deps.t("settings.update.current_status_empty"))}</div>`;
  }
  return `<div class="status-grid">${rows}</div>`;
}

function renderHealthSummaryRows(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const rows = [renderStatusGridRow(escapeHtml(t("settings.update.health.processing_state")), escapeHtml(health.processing_state))];
  if (health.processing_failures > 0) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.processing_failures")), escapeHtml(health.processing_failures)));
  if (health.degradation_reasons.length) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.reasons")), escapeHtml(health.degradation_reasons.map((reason) => formatHealthReason(reason, t)).join(", "))));
  return rows.join("");
}

function renderHealthDataLossRows(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  if (health.data_loss.affected_clients <= 0) return "";
  const { t, escapeHtml } = deps;
  return [
    renderStatusGridRow(escapeHtml(t("settings.update.health.affected_clients")), escapeHtml(`${health.data_loss.affected_clients}/${health.data_loss.tracked_clients}`)),
    renderStatusGridRow(
      escapeHtml(t("settings.update.health.data_loss")),
      escapeHtml([
        `frames=${health.data_loss.frames_dropped}`,
        `queue=${health.data_loss.queue_overflow_drops}`,
        `server=${health.data_loss.server_queue_drops}`,
        `parse=${health.data_loss.parse_errors}`,
      ].join(", ")),
    ),
  ].join("");
}

function renderHealthPersistenceRows(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const analysisQueueDepth = health.persistence.analysis_queue_depth ?? 0;
  if (!health.persistence.analysis_in_progress && !health.persistence.write_error && analysisQueueDepth <= 0) return "";
  const { t, escapeHtml } = deps;
  const rows = [
    renderStatusGridRow(
      escapeHtml(t("settings.update.health.persistence")),
      escapeHtml(health.persistence.write_error || t("settings.update.health.persistence_ok")),
    ),
  ];
  if (health.persistence.analysis_in_progress) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis")), escapeHtml(t("settings.update.health.analysis_in_progress"))));
  if (health.persistence.analysis_active_run_id) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_run")), escapeHtml(health.persistence.analysis_active_run_id)));
  if (health.persistence.analysis_started_at != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_started_at")), escapeHtml(formatEpochTimestamp(health.persistence.analysis_started_at))));
  if (health.persistence.analysis_elapsed_s != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_elapsed")), escapeHtml(formatDuration(health.persistence.analysis_elapsed_s))));
  if (analysisQueueDepth > 0) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_queue_depth")), escapeHtml(String(analysisQueueDepth))));
  return rows.join("");
}

function renderHealthBadge(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const variant = health.persistence.write_error ? "bad" : HEALTH_VARIANT[health.status];
  return `<span class="pill pill--${variant}">${escapeHtml(t(`settings.update.health.state.${health.status}`))}</span>`;
}

function renderHealthSummary(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const key = health.persistence.write_error || health.status === "degraded"
    ? "settings.update.health_card_summary.degraded"
    : health.status === "warn"
      ? "settings.update.health_card_summary.warn"
      : "settings.update.health_card_summary.ok";
  return escapeHtml(t(key));
}

function renderHealthGrid(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  return `<div class="status-grid">${renderHealthSummaryRows(health, deps)}${renderHealthDataLossRows(health, deps)}${renderHealthPersistenceRows(health, deps)}</div>`;
}

function renderLogTail(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  if (!status.log_tail.length) {
    return renderMaintenanceCard(
      escapeHtml(t("settings.update.log")),
      escapeHtml(t("settings.update.log_intro")),
      renderInlineEmptyState(
        t("settings.update.log_empty_title"),
        t("settings.update.log_empty_body"),
        escapeHtml,
      ),
    );
  }
  const logBody = status.log_tail.map((line) => `${escapeHtml(line)}\n`).join("");
  return renderMaintenanceCard(
    escapeHtml(t("settings.update.log")),
    escapeHtml(t("settings.update.log_intro")),
    `<pre class="log-pre">${logBody}</pre>`,
  );
}

export function syncUpdateControls(
  els: Pick<
    UiDomElements,
    | "updateStartBtn"
    | "updateCancelBtn"
    | "updateSsidInput"
    | "updatePasswordInput"
    | "updateTransportWifiRadio"
    | "updateTransportUsbRadio"
  >,
  status: UpdateStatusPayload,
): void {
  const isRunning = status.state === "running";
  if (els.updateStartBtn) {
    els.updateStartBtn.hidden = isRunning;
    els.updateStartBtn.disabled = isRunning;
  }
  if (els.updateCancelBtn) {
    els.updateCancelBtn.hidden = !isRunning;
  }
  if (els.updateSsidInput) els.updateSsidInput.disabled = isRunning;
  if (els.updatePasswordInput) els.updatePasswordInput.disabled = isRunning;
  if (els.updateTransportWifiRadio) els.updateTransportWifiRadio.disabled = isRunning;
  if (els.updateTransportUsbRadio) els.updateTransportUsbRadio.disabled = isRunning;
}

export function renderUpdateStatusPanel(
  panel: HTMLElement,
  status: UpdateStatusPayload,
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): void {
  const hasAssetRelatedIssue = status.issues.some((issue) =>
    ASSET_ISSUE_RE.test(`${issue.message} ${issue.detail}`),
  );
  const showRuntimeAssetsCheck = status.state !== "failed" || hasAssetRelatedIssue;
  panel.innerHTML = [
    renderMaintenanceCard(
      deps.escapeHtml(deps.t("settings.update.current_status_title")),
      renderStateSummary(status, health, deps),
      renderStateGrid(status, showRuntimeAssetsCheck, deps),
      renderStateBadge(status, deps),
    ),
    renderMaintenanceCard(
      deps.escapeHtml(deps.t("settings.update.health_card_title")),
      renderHealthSummary(health, deps),
      renderHealthGrid(health, deps),
      renderHealthBadge(health, deps),
    ),
    renderLogTail(status, deps),
  ].filter(Boolean).join("");
}
