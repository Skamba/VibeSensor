import type { HealthStatusPayload, UpdateStatusPayload } from "../../api/types";
import type { UiDomElements } from "../ui_dom_registry";
import { renderStatusGridRow } from "./dom_helpers";

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

function formatTimestamp(epoch: number | null): string {
  if (epoch === null) return "—";
  return new Date(epoch * 1000).toLocaleString();
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

function renderStateHeaderRow(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const pill = `<span class="pill pill--${STATE_VARIANT[status.state] || "muted"}">${escapeHtml(t(`settings.update.state.${status.state}`))}</span>`;
  const phase = status.state === "idle"
    ? ""
    : ` <span class="subtle">${escapeHtml(t(`settings.update.phase.${status.phase}`))}</span>`;
  return renderStatusGridRow(
    escapeHtml(t("settings.update.status")),
    `${pill}${phase}`,
  );
}

function renderLifecycleRows(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const rows: string[] = [];
  if (status.ssid) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.ssid_label")), escapeHtml(status.ssid)));
  if (status.started_at) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.started_at")), escapeHtml(formatTimestamp(status.started_at))));
  if (status.phase_started_at && status.state !== "idle") rows.push(renderStatusGridRow(escapeHtml(t("settings.update.phase_started_at")), escapeHtml(formatTimestamp(status.phase_started_at))));
  if (status.state !== "idle" && status.phase_elapsed_s != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.phase_elapsed")), escapeHtml(formatDuration(status.phase_elapsed_s))));
  if (status.finished_at) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.finished_at")), escapeHtml(formatTimestamp(status.finished_at))));
  if (status.last_success_at) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.last_success")), escapeHtml(formatTimestamp(status.last_success_at))));
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
  return `<div class="update-status-grid">${renderStateHeaderRow(status, deps)}${renderLifecycleRows(status, deps)}${renderRuntimeRows(status, showRuntimeAssetsCheck, deps)}</div>`;
}

function renderHealthSummaryRows(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const pill = `<span class="pill pill--${HEALTH_VARIANT[health.status]}${health.persistence.write_error ? " pill--bad" : ""}">${escapeHtml(t(`settings.update.health.state.${health.status}`))}</span>`;
  const rows = [
    renderStatusGridRow(escapeHtml(t("settings.update.health.label")), pill),
    renderStatusGridRow(escapeHtml(t("settings.update.health.processing_state")), escapeHtml(health.processing_state)),
  ];
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
  if (health.persistence.analysis_started_at) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_started_at")), escapeHtml(formatTimestamp(health.persistence.analysis_started_at))));
  if (health.persistence.analysis_elapsed_s != null) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_elapsed")), escapeHtml(formatDuration(health.persistence.analysis_elapsed_s))));
  if (analysisQueueDepth > 0) rows.push(renderStatusGridRow(escapeHtml(t("settings.update.health.analysis_queue_depth")), escapeHtml(String(analysisQueueDepth))));
  return rows.join("");
}

function renderHealthGrid(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  return `<div class="update-status-grid" style="margin-top:1rem;">${renderHealthSummaryRows(health, deps)}${renderHealthDataLossRows(health, deps)}${renderHealthPersistenceRows(health, deps)}</div>`;
}

function renderIssuesList(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  if (!status.issues.length) return "";
  const { t, escapeHtml } = deps;
  const items = status.issues.map((issue) => {
    const detail = issue.detail
      ? `<div class="issue-detail subtle">${escapeHtml(issue.detail)}</div>`
      : "";
    return `<li class="issue-item"><span class="issue-phase">[${escapeHtml(issue.phase)}]</span> <span class="issue-message">${escapeHtml(issue.message)}</span>${detail}</li>`;
  }).join("");
  return `<div class="update-issues" style="margin-top:1rem;"><strong>${escapeHtml(t("settings.update.issues"))}</strong><ul class="issue-list">${items}</ul></div>`;
}

function renderLogTail(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  if (!status.log_tail.length) return "";
  const { t, escapeHtml } = deps;
  const logBody = status.log_tail.map((line) => `${escapeHtml(line)}\n`).join("");
  return `<details class="update-log" style="margin-top:1rem;"><summary>${escapeHtml(t("settings.update.log"))}</summary><pre class="log-pre" style="max-height:15rem;overflow:auto;font-size:0.75rem;background:var(--bg-secondary,#1a1a2e);padding:0.5rem;border-radius:0.25rem;">${logBody}</pre></details>`;
}

export function syncUpdateControls(
  els: Pick<UiDomElements, "updateStartBtn" | "updateCancelBtn" | "updateSsidInput" | "updatePasswordInput">,
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
  if (status.state === "idle" && !status.last_success_at && !status.issues.length && health.status === "ok") {
    panel.innerHTML = "";
    return;
  }
  panel.innerHTML = [
    renderStateGrid(status, showRuntimeAssetsCheck, deps),
    renderHealthGrid(health, deps),
    renderIssuesList(status, deps),
    renderLogTail(status, deps),
  ].join("");
}
