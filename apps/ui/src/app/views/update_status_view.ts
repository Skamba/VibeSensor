import type {
  HealthStatusPayload,
  UpdateIssue,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
} from "../../api/types";
import type { UiUpdateDom } from "../dom/update_dom";
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
  escapeHtml: (value: unknown) => string;
  selectedTransport: UpdateJourneyTransport;
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

export function formatUpdatePhase(
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
  if (status.state !== "idle") {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.phase_label")),
        escapeHtml(formatUpdatePhase(status.phase, t)),
      ),
    );
  }
  if (status.started_at != null) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.started_at")),
        escapeHtml(formatEpochTimestamp(status.started_at)),
      ),
    );
  }
  if (status.phase_started_at != null && status.state !== "idle") {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.phase_started_at")),
        escapeHtml(formatEpochTimestamp(status.phase_started_at)),
      ),
    );
  }
  if (status.state !== "idle" && status.phase_elapsed_s != null) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.phase_elapsed")),
        escapeHtml(formatDuration(status.phase_elapsed_s)),
      ),
    );
  }
  if (status.finished_at != null) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.finished_at")),
        escapeHtml(formatEpochTimestamp(status.finished_at)),
      ),
    );
  }
  if (status.last_success_at != null) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.last_success")),
        escapeHtml(formatEpochTimestamp(status.last_success_at)),
      ),
    );
  }
  return rows.join("");
}

function renderRuntimeRows(
  status: UpdateStatusPayload,
  showRuntimeAssetsCheck: boolean,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const rows: string[] = [];
  if (status.runtime?.version && status.runtime.version !== "unknown") {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.runtime_version")),
        escapeHtml(status.runtime.version),
      ),
    );
  }
  if (status.runtime?.commit) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.runtime_commit")),
        escapeHtml(status.runtime.commit.slice(0, 12)),
      ),
    );
  }
  if (!status.runtime?.static_assets_hash) return rows.join("");
  rows.push(
    renderStatusGridRow(
      escapeHtml(t("settings.update.runtime_assets")),
      escapeHtml(status.runtime.static_assets_hash.slice(0, 12)),
    ),
  );
  if (showRuntimeAssetsCheck) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.runtime_assets_check")),
        escapeHtml(
          t(
            status.runtime.assets_verified
              ? "settings.update.runtime_assets_ok"
              : "settings.update.runtime_assets_bad",
          ),
        ),
      ),
    );
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

function journeyStageLabel(
  state: JourneyStageState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  return t(`maintenance.stage_state.${state}`);
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

export function primaryJourneyIssue(status: UpdateStatusPayload): UpdateIssue | null {
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

function renderJourneyFailureNote(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const failure = getUpdateFailureSummary(status, deps.t);
  if (!failure) {
    return "";
  }
  const summary = failure.message ? `${failure.phaseLabel} — ${failure.message}` : failure.phaseLabel;
  return `<div class="maintenance-stack maintenance-stack--tight">
    <div class="maintenance-note maintenance-note--bad">
      <strong>${deps.escapeHtml(summary)}</strong>
      ${failure.detail ? `<div class="issue-detail">${deps.escapeHtml(failure.detail)}</div>` : ""}
    </div>
    <div class="maintenance-note">
      <strong>${deps.escapeHtml(failure.recoveryTitle)}</strong>
      <div class="issue-detail">${deps.escapeHtml(failure.recoveryDetail)}</div>
    </div>
  </div>`;
}

function renderJourney(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const stages = journeyStages(resolvedJourneyTransport(status, deps.selectedTransport));
  const items = stages.map((stage, index) => {
    const stageState = resolveJourneyStageState(status, stages, index);
    const markerLabel = stageState === "done" ? "✓" : `${index + 1}`;
    const currentStepAttr = stageState === "active" ? ' aria-current="step"' : "";
    return `<li class="maintenance-stage maintenance-stage--${stageState}" data-stage-phase="${stage.phase}" data-stage-state="${stageState}"${currentStepAttr}>
      <span class="maintenance-stage__marker">${markerLabel}</span>
      <div class="maintenance-stage__body">
        <div class="maintenance-stage__title">${escapeHtml(t(stage.titleKey))}</div>
        <div class="maintenance-stage__detail">${escapeHtml(t(stage.detailKey))}</div>
      </div>
      <span class="maintenance-stage__state">${escapeHtml(journeyStageLabel(stageState, t))}</span>
    </li>`;
  }).join("");
  return `<div class="maintenance-journey">
    ${renderJourneyFailureNote(status, deps)}
    <ol class="maintenance-stage-list">${items}</ol>
  </div>`;
}

function renderIssuesCard(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  if (status.issues.length === 0) {
    return "";
  }
  const { t, escapeHtml } = deps;
  const items = status.issues.map((issue) => `
    <li class="issue-item">
      <div class="issue-phase">${escapeHtml(formatUpdatePhase(issue.phase, t))}</div>
      <div>
        <strong>${escapeHtml(issue.message)}</strong>
        ${issue.detail ? `<div class="issue-detail">${escapeHtml(issue.detail)}</div>` : ""}
      </div>
    </li>
  `).join("");
  return renderMaintenanceCard(
    escapeHtml(t("settings.update.issues")),
    escapeHtml(t("settings.update.issues_intro")),
    `<ul class="issue-list">${items}</ul>`,
  );
}

function renderLatestAttemptCard(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  if (status.state === "idle" || status.state === "running") {
    return "";
  }
  const { t, escapeHtml } = deps;
  const rows = [
    status.started_at != null
      ? renderStatusGridRow(
          escapeHtml(t("settings.update.started_at")),
          escapeHtml(formatEpochTimestamp(status.started_at)),
        )
      : "",
    status.finished_at != null
      ? renderStatusGridRow(
          escapeHtml(t("settings.update.finished_at")),
          escapeHtml(formatEpochTimestamp(status.finished_at)),
        )
      : "",
    renderStatusGridRow(
      escapeHtml(t("settings.update.transport_label")),
      escapeHtml(
        status.transport === "usb_internet"
          ? status.uplink_interface
            ? t("settings.update.transport_value.usb_interface", {
                interface: status.uplink_interface,
              })
            : t("settings.update.transport_value.usb")
          : status.ssid
            ? t("settings.update.transport_value.wifi_ssid", { ssid: status.ssid })
            : t("settings.update.transport_value.wifi"),
      ),
    ),
    status.exit_code != null
      ? renderStatusGridRow(
          escapeHtml(t("settings.update.exit_code")),
          escapeHtml(String(status.exit_code)),
        )
      : "",
  ].filter(Boolean).join("");
  const failure = getUpdateFailureSummary(status, t);
  const noteHtml = failure
    ? `<div class="maintenance-note maintenance-note--bad">
        <strong>${escapeHtml(failure.message ?? failure.phaseLabel)}</strong>
        ${failure.detail ? `<div class="issue-detail">${escapeHtml(failure.detail)}</div>` : ""}
      </div>`
    : "";
  return renderMaintenanceCard(
    escapeHtml(t("settings.update.attempt_title")),
    escapeHtml(t("settings.update.attempt_intro")),
    `<div class="status-grid">${rows}</div>${noteHtml}`,
    renderStateBadge(status, deps),
  );
}

function renderHealthSummaryRows(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  const { t, escapeHtml } = deps;
  const rows = [
    renderStatusGridRow(
      escapeHtml(t("settings.update.health.processing_state")),
      escapeHtml(health.processing_state),
    ),
  ];
  if (health.processing_failures > 0) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.processing_failures")),
        escapeHtml(health.processing_failures),
      ),
    );
  }
  if (health.degradation_reasons.length) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.reasons")),
        escapeHtml(
          health.degradation_reasons
            .map((reason) => formatHealthReason(reason, t))
            .join(", "),
        ),
      ),
    );
  }
  return rows.join("");
}

function renderHealthDataLossRows(
  health: HealthStatusPayload,
  deps: UpdateStatusViewDeps,
): string {
  if (health.data_loss.affected_clients <= 0) return "";
  const { t, escapeHtml } = deps;
  return [
    renderStatusGridRow(
      escapeHtml(t("settings.update.health.affected_clients")),
      escapeHtml(`${health.data_loss.affected_clients}/${health.data_loss.tracked_clients}`),
    ),
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
  if (
    !health.persistence.analysis_in_progress
    && !health.persistence.write_error
    && analysisQueueDepth <= 0
  ) {
    return "";
  }
  const { t, escapeHtml } = deps;
  const rows = [
    renderStatusGridRow(
      escapeHtml(t("settings.update.health.persistence")),
      escapeHtml(health.persistence.write_error || t("settings.update.health.persistence_ok")),
    ),
  ];
  if (health.persistence.analysis_in_progress) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.analysis")),
        escapeHtml(t("settings.update.health.analysis_in_progress")),
      ),
    );
  }
  if (health.persistence.analysis_active_run_id) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.analysis_run")),
        escapeHtml(health.persistence.analysis_active_run_id),
      ),
    );
  }
  if (health.persistence.analysis_started_at != null) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.analysis_started_at")),
        escapeHtml(formatEpochTimestamp(health.persistence.analysis_started_at)),
      ),
    );
  }
  if (health.persistence.analysis_elapsed_s != null) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.analysis_elapsed")),
        escapeHtml(formatDuration(health.persistence.analysis_elapsed_s)),
      ),
    );
  }
  if (analysisQueueDepth > 0) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.update.health.analysis_queue_depth")),
        escapeHtml(String(analysisQueueDepth)),
      ),
    );
  }
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
  const isRunning = status.state === "running";
  if (!status.log_tail.length) {
    const emptyTitle = isRunning
      ? t("settings.update.log_running_title")
      : status.state === "failed"
        ? t("settings.update.log_failed_title")
        : t("settings.update.log_empty_title");
    const emptyBody = isRunning
      ? t("settings.update.log_running_body")
      : status.state === "failed"
        ? t("settings.update.log_failed_body")
        : t("settings.update.log_empty_body");
    return renderMaintenanceCard(
      escapeHtml(t("settings.update.log")),
      escapeHtml(t(isRunning ? "settings.update.log_intro_running" : "settings.update.log_intro")),
      renderInlineEmptyState(
        emptyTitle,
        emptyBody,
        escapeHtml,
      ),
    );
  }
  const logBody = status.log_tail.map((line) => `${escapeHtml(line)}\n`).join("");
  return renderMaintenanceCard(
    escapeHtml(t("settings.update.log")),
    escapeHtml(t(isRunning ? "settings.update.log_intro_running" : "settings.update.log_intro")),
    `${isRunning ? `<div class="maintenance-note">${escapeHtml(t("settings.update.log_running_note"))}</div>` : ""}<pre class="log-pre">${logBody}</pre>`,
  );
}

export function syncUpdateControls(
  els: Pick<
    UiUpdateDom,
    | "updateStartBtn"
    | "updateCancelBtn"
    | "updateSsidInput"
    | "updatePasswordInput"
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
    `<div class="maintenance-pair-grid">${[
      renderMaintenanceCard(
        deps.escapeHtml(deps.t("settings.update.current_status_title")),
        renderStateSummary(status, health, deps),
        renderStateGrid(status, showRuntimeAssetsCheck, deps),
        renderStateBadge(status, deps),
      ),
      renderMaintenanceCard(
        deps.escapeHtml(deps.t("settings.update.journey_title")),
        deps.escapeHtml(deps.t("settings.update.journey_intro")),
        renderJourney(status, deps),
      ),
    ].join("")}</div>`,
    renderIssuesCard(status, deps),
    renderLatestAttemptCard(status, deps),
    renderMaintenanceCard(
      deps.escapeHtml(deps.t("settings.update.health_card_title")),
      renderHealthSummary(health, deps),
      renderHealthGrid(health, deps),
      renderHealthBadge(health, deps),
    ),
    renderLogTail(status, deps),
  ].filter(Boolean).join("");
}
