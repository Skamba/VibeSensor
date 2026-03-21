import type { HealthStatusPayload, UpdateStatusPayload } from "../../api/types";
import type { UiDomElements } from "../ui_dom_registry";

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
  const { t, escapeHtml } = deps;
  const isRunning = status.state === "running";
  const isIdle = status.state === "idle";
  const analysisQueueDepth = health.persistence.analysis_queue_depth ?? 0;
  const hasAssetRelatedIssue = status.issues.some((issue) =>
    ASSET_ISSUE_RE.test(`${issue.message} ${issue.detail}`),
  );
  const showRuntimeAssetsCheck = status.state !== "failed" || hasAssetRelatedIssue;

  if (isIdle && !status.last_success_at && !status.issues.length && health.status === "ok") {
    panel.innerHTML = "";
    return;
  }

  const stateKey = `settings.update.state.${status.state}`;
  const phaseKey = `settings.update.phase.${status.phase}`;

  let html = `<div class="update-status-grid">`;
  html += `<div class="update-status-row">`;
  html += `<span class="update-label">${escapeHtml(t("settings.update.status"))}</span>`;
  html += `<span class="pill pill--${STATE_VARIANT[status.state] || "muted"}">${escapeHtml(t(stateKey))}</span>`;
  if (!isIdle) {
    html += ` <span class="subtle">${escapeHtml(t(phaseKey))}</span>`;
  }
  html += `</div>`;

  if (status.ssid) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.ssid_label"))}</span>`;
    html += `<span>${escapeHtml(status.ssid)}</span>`;
    html += `</div>`;
  }
  if (status.started_at) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.started_at"))}</span>`;
    html += `<span>${escapeHtml(formatTimestamp(status.started_at))}</span>`;
    html += `</div>`;
  }
  if (status.phase_started_at && !isIdle) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.phase_started_at"))}</span>`;
    html += `<span>${escapeHtml(formatTimestamp(status.phase_started_at))}</span>`;
    html += `</div>`;
  }
  if (!isIdle && status.phase_elapsed_s !== null && status.phase_elapsed_s !== undefined) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.phase_elapsed"))}</span>`;
    html += `<span>${escapeHtml(formatDuration(status.phase_elapsed_s))}</span>`;
    html += `</div>`;
  }
  if (status.finished_at) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.finished_at"))}</span>`;
    html += `<span>${escapeHtml(formatTimestamp(status.finished_at))}</span>`;
    html += `</div>`;
  }
  if (status.last_success_at) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.last_success"))}</span>`;
    html += `<span>${escapeHtml(formatTimestamp(status.last_success_at))}</span>`;
    html += `</div>`;
  }
  if (status.runtime?.version && status.runtime.version !== "unknown") {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.runtime_version"))}</span>`;
    html += `<span>${escapeHtml(status.runtime.version)}</span>`;
    html += `</div>`;
  }
  if (status.runtime?.commit) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.runtime_commit"))}</span>`;
    html += `<span>${escapeHtml(status.runtime.commit.slice(0, 12))}</span>`;
    html += `</div>`;
  }
  if (status.runtime?.static_assets_hash) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.runtime_assets"))}</span>`;
    html += `<span>${escapeHtml(status.runtime.static_assets_hash.slice(0, 12))}</span>`;
    html += `</div>`;
    if (showRuntimeAssetsCheck) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.runtime_assets_check"))}</span>`;
      html += `<span>${escapeHtml(t(status.runtime.assets_verified ? "settings.update.runtime_assets_ok" : "settings.update.runtime_assets_bad"))}</span>`;
      html += `</div>`;
    }
  }
  html += `</div>`;

  html += `<div class="update-status-grid" style="margin-top:1rem;">`;
  html += `<div class="update-status-row">`;
  html += `<span class="update-label">${escapeHtml(t("settings.update.health.label"))}</span>`;
  html += `<span class="pill pill--${HEALTH_VARIANT[health.status]}${health.persistence.write_error ? " pill--bad" : ""}">${escapeHtml(t(`settings.update.health.state.${health.status}`))}</span>`;
  html += `</div>`;
  html += `<div class="update-status-row">`;
  html += `<span class="update-label">${escapeHtml(t("settings.update.health.processing_state"))}</span>`;
  html += `<span>${escapeHtml(health.processing_state)}</span>`;
  html += `</div>`;

  if (health.processing_failures > 0) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.health.processing_failures"))}</span>`;
    html += `<span>${escapeHtml(health.processing_failures)}</span>`;
    html += `</div>`;
  }

  if (health.degradation_reasons.length) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.health.reasons"))}</span>`;
    html += `<span>${escapeHtml(health.degradation_reasons.map((reason) => formatHealthReason(reason, t)).join(", "))}</span>`;
    html += `</div>`;
  }

  if (health.data_loss.affected_clients > 0) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.health.affected_clients"))}</span>`;
    html += `<span>${escapeHtml(`${health.data_loss.affected_clients}/${health.data_loss.tracked_clients}`)}</span>`;
    html += `</div>`;
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.health.data_loss"))}</span>`;
    html += `<span>${escapeHtml([
      `frames=${health.data_loss.frames_dropped}`,
      `queue=${health.data_loss.queue_overflow_drops}`,
      `server=${health.data_loss.server_queue_drops}`,
      `parse=${health.data_loss.parse_errors}`,
    ].join(", "))}</span>`;
    html += `</div>`;
  }

  if (health.persistence.analysis_in_progress || health.persistence.write_error || analysisQueueDepth > 0) {
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.health.persistence"))}</span>`;
    html += `<span>${escapeHtml(
      health.persistence.write_error
        ? health.persistence.write_error
        : t("settings.update.health.persistence_ok"),
    )}</span>`;
    html += `</div>`;
    if (health.persistence.analysis_in_progress) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.health.analysis"))}</span>`;
      html += `<span>${escapeHtml(t("settings.update.health.analysis_in_progress"))}</span>`;
      html += `</div>`;
      if (health.persistence.analysis_active_run_id) {
        html += `<div class="update-status-row">`;
        html += `<span class="update-label">${escapeHtml(t("settings.update.health.analysis_run"))}</span>`;
        html += `<span>${escapeHtml(health.persistence.analysis_active_run_id)}</span>`;
        html += `</div>`;
      }
      if (health.persistence.analysis_started_at) {
        html += `<div class="update-status-row">`;
        html += `<span class="update-label">${escapeHtml(t("settings.update.health.analysis_started_at"))}</span>`;
        html += `<span>${escapeHtml(formatTimestamp(health.persistence.analysis_started_at))}</span>`;
        html += `</div>`;
      }
      if (health.persistence.analysis_elapsed_s !== null && health.persistence.analysis_elapsed_s !== undefined) {
        html += `<div class="update-status-row">`;
        html += `<span class="update-label">${escapeHtml(t("settings.update.health.analysis_elapsed"))}</span>`;
        html += `<span>${escapeHtml(formatDuration(health.persistence.analysis_elapsed_s))}</span>`;
        html += `</div>`;
      }
    }
    if (analysisQueueDepth > 0) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.health.analysis_queue_depth"))}</span>`;
      html += `<span>${escapeHtml(String(analysisQueueDepth))}</span>`;
      html += `</div>`;
    }
  }
  html += `</div>`;

  if (status.issues.length) {
    html += `<div class="update-issues" style="margin-top:1rem;">`;
    html += `<strong>${escapeHtml(t("settings.update.issues"))}</strong>`;
    html += `<ul class="issue-list">`;
    for (const issue of status.issues) {
      html += `<li class="issue-item">`;
      html += `<span class="issue-phase">[${escapeHtml(issue.phase)}]</span> `;
      html += `<span class="issue-message">${escapeHtml(issue.message)}</span>`;
      if (issue.detail) {
        html += `<div class="issue-detail subtle">${escapeHtml(issue.detail)}</div>`;
      }
      html += `</li>`;
    }
    html += `</ul></div>`;
  }

  if (status.log_tail.length) {
    html += `<details class="update-log" style="margin-top:1rem;">`;
    html += `<summary>${escapeHtml(t("settings.update.log"))}</summary>`;
    html += `<pre class="log-pre" style="max-height:15rem;overflow:auto;font-size:0.75rem;background:var(--bg-secondary,#1a1a2e);padding:0.5rem;border-radius:0.25rem;">`;
    for (const line of status.log_tail) {
      html += escapeHtml(line) + "\n";
    }
    html += `</pre></details>`;
  }

  panel.innerHTML = html;
}
