import type {
  EspFlashHistoryAttemptPayload,
  EspFlashHistoryPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../api/types";
import {
  ESP_FLASH_POLL_ACTIVE_MS,
  ESP_FLASH_POLL_IDLE_MS,
} from "../../config";
import type { FeatureDepsBase } from "../feature_deps_base";
import { createPollingController } from "./polling_controller";
import {
  cancelEspFlash,
  getEspFlashHistory,
  getEspFlashLogs,
  getEspFlashPorts,
  getEspFlashStatus,
  startEspFlash,
} from "../../api/settings";
import { formatEpochTimestamp, renderStatusGridRow } from "../views/dom_helpers";
import { renderMaintenanceReadinessPanel } from "../views/maintenance_readiness_view";

export interface EspFlashFeatureDeps extends FeatureDepsBase {}

export interface EspFlashFeature {
  bindHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

const LOG_PANEL_BASE_CLASS = "maintenance-log-slot";

const STATE_TO_VARIANT: Readonly<Record<string, string>> = {
  success: "ok",
  running: "warn",
  failed: "bad",
};

type JourneyStageState = "upcoming" | "active" | "done" | "attention";

interface FlashAttemptSummary {
  autoDetect: boolean;
  error: string | null;
  exitCode: number | null;
  finishedAt: number | null;
  selectedPort: string | null;
  startedAt: number | null;
  state: string;
}

const ESP_FLASH_JOURNEY_STAGES = [
  {
    phase: "validating",
    titleKey: "settings.esp_flash.phase.validating",
    detailKey: "settings.esp_flash.journey.detail.validating",
  },
  {
    phase: "preparing",
    titleKey: "settings.esp_flash.phase.preparing",
    detailKey: "settings.esp_flash.journey.detail.preparing",
  },
  {
    phase: "erasing",
    titleKey: "settings.esp_flash.phase.erasing",
    detailKey: "settings.esp_flash.journey.detail.erasing",
  },
  {
    phase: "flashing",
    titleKey: "settings.esp_flash.phase.flashing",
    detailKey: "settings.esp_flash.journey.detail.flashing",
  },
  {
    phase: "done",
    titleKey: "settings.esp_flash.phase.done",
    detailKey: "settings.esp_flash.journey.detail.done",
  },
] as const;

function safeEspFlashState(state: string | null | undefined): string {
  return state || "idle";
}

function createIdleStatus(): EspFlashStatusPayload {
  return {
    auto_detect: true,
    error: null,
    exit_code: null,
    finished_at: null,
    job_id: null,
    last_success_at: null,
    log_count: 0,
    phase: "idle",
    selected_port: null,
    started_at: null,
    state: "idle",
  };
}

function recoveryGuidanceKey(state: string, phase: string): string {
  if (state === "cancelled") {
    return "settings.esp_flash.recovery.cancelled";
  }
  switch (phase) {
    case "preparing":
      return "settings.esp_flash.recovery.preparing";
    case "erasing":
      return "settings.esp_flash.recovery.erasing";
    case "flashing":
      return "settings.esp_flash.recovery.flashing";
    case "validating":
      return "settings.esp_flash.recovery.validating";
    default:
      return "settings.esp_flash.recovery.generic";
  }
}

export function createEspFlashFeature(ctx: EspFlashFeatureDeps): EspFlashFeature {
  const { els, t, escapeHtml } = ctx;
  let nextLogIndex = 0;
  let latestStatus: EspFlashStatusPayload = createIdleStatus();
  let latestJourneyPhase: string | null = null;
  let availablePorts: EspSerialPortPayload[] = [];
  let latestAttempts: EspFlashHistoryAttemptPayload[] = [];

  function translateKeyOrFallback(key: string, fallback: string): string {
    const translated = t(key);
    return translated === key ? fallback : translated;
  }

  function formatEspFlashPhase(phase: string | null | undefined): string {
    const safePhase = phase || "idle";
    return translateKeyOrFallback(`settings.esp_flash.phase.${safePhase}`, safePhase);
  }

  function stageStateLabel(state: JourneyStageState): string {
    return t(`maintenance.stage_state.${state}`);
  }

  function journeyStageIndex(phase: string | null | undefined): number {
    return ESP_FLASH_JOURNEY_STAGES.findIndex((stage) => stage.phase === (phase || "idle"));
  }

  function resolvedJourneyPhase(status: EspFlashStatusPayload): string | null {
    if (journeyStageIndex(status.phase) !== -1) {
      return status.phase || null;
    }
    if (status.state === "failed" || status.state === "cancelled") {
      return latestJourneyPhase;
    }
    return null;
  }

  function resolveJourneyStageState(status: EspFlashStatusPayload, stageIndex: number): JourneyStageState {
    if (status.state === "success") return "done";
    if (status.state === "idle") return "upcoming";
    const currentIndex = journeyStageIndex(resolvedJourneyPhase(status));
    if (currentIndex === -1) {
      return "upcoming";
    }
    if (stageIndex < currentIndex) return "done";
    if (stageIndex === currentIndex) {
      return status.state === "failed" || status.state === "cancelled" ? "attention" : "active";
    }
    return "upcoming";
  }

  function renderJourney(status: EspFlashStatusPayload): string {
    const items = ESP_FLASH_JOURNEY_STAGES.map((stage, index) => {
      const stageState = resolveJourneyStageState(status, index);
      const markerLabel = stageState === "done" ? "✓" : `${index + 1}`;
      const currentStepAttr = stageState === "active" ? ' aria-current="step"' : "";
      return `<li class="maintenance-stage maintenance-stage--${stageState}" data-stage-phase="${stage.phase}" data-stage-state="${stageState}"${currentStepAttr}>
        <span class="maintenance-stage__marker">${markerLabel}</span>
        <div class="maintenance-stage__body">
          <div class="maintenance-stage__title">${escapeHtml(t(stage.titleKey))}</div>
          <div class="maintenance-stage__detail">${escapeHtml(t(stage.detailKey))}</div>
        </div>
        <span class="maintenance-stage__state">${escapeHtml(stageStateLabel(stageState))}</span>
      </li>`;
    }).join("");
    const terminalState = safeEspFlashState(status.state);
    const terminalNote = terminalState === "failed" || terminalState === "cancelled"
      ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(t(`settings.esp_flash.journey_terminal.${terminalState}`))}</div>`
      : "";
    return `<div class="maintenance-journey">
      ${terminalNote}
      <ol class="maintenance-stage-list">${items}</ol>
    </div>`;
  }

  function selectedTargetLabel(status: EspFlashStatusPayload): string {
    const selectedValue = els.espFlashPortSelect?.value;
    const raw = status.selected_port || (selectedValue && selectedValue !== "__auto__" ? selectedValue : null);
    return raw || t("settings.esp_flash.auto_detect");
  }

  function detectedPortsLabel(): string {
    if (availablePorts.length === 0) return t("settings.esp_flash.readiness.no_ports");
    if (availablePorts.length === 1) {
      const port = availablePorts[0];
      const label = port.description ? `${port.port} — ${port.description}` : port.port;
      return t("settings.esp_flash.readiness.one_port", { port: label });
    }
    return t("settings.esp_flash.readiness.multiple_ports", { count: availablePorts.length });
  }

  function readinessSummary(status: EspFlashStatusPayload): string {
    const safeState = safeEspFlashState(status.state);
    switch (safeState) {
      case "running":
        return t("settings.esp_flash.readiness.summary.running");
      case "success":
        return t("settings.esp_flash.readiness.summary.success");
      case "failed":
        return t("settings.esp_flash.readiness.summary.failed");
      case "cancelled":
        return t("settings.esp_flash.readiness.summary.cancelled");
      default:
        return availablePorts.length > 0
          ? t("settings.esp_flash.readiness.summary.ready_ports")
          : t("settings.esp_flash.readiness.summary.ready_no_ports");
    }
  }

  function latestAttemptSummary(attempt: FlashAttemptSummary): string {
    const stateLabel = t(`settings.esp_flash.state.${safeEspFlashState(attempt.state)}`);
    const when = formatEpochTimestamp(attempt.finishedAt ?? attempt.startedAt);
    return t("settings.esp_flash.last_result_value", { state: stateLabel, when });
  }

  function currentAttemptSummaries(status: EspFlashStatusPayload): FlashAttemptSummary[] {
    if (latestAttempts.length > 0) {
      return latestAttempts.map((attempt) => ({
        autoDetect: attempt.auto_detect,
        error: attempt.error ?? null,
        exitCode: attempt.exit_code ?? null,
        finishedAt: attempt.finished_at ?? null,
        selectedPort: attempt.selected_port ?? null,
        startedAt: attempt.started_at ?? null,
        state: safeEspFlashState(attempt.state),
      }));
    }
    const safeState = safeEspFlashState(status.state);
    if (safeState === "idle" || safeState === "running") {
      return [];
    }
    return [{
      autoDetect: status.auto_detect,
      error: status.error ?? null,
      exitCode: status.exit_code ?? null,
      finishedAt: status.finished_at ?? null,
      selectedPort: status.selected_port ?? null,
      startedAt: status.started_at ?? null,
      state: safeState,
    }];
  }

  function recoverySummary(status: EspFlashStatusPayload): {
    message: string;
    phaseLabel: string;
    recoveryDetail: string;
    recoveryTitle: string;
  } | null {
    const safeState = safeEspFlashState(status.state);
    if (safeState !== "failed" && safeState !== "cancelled") {
      return null;
    }
    const phase = resolvedJourneyPhase(status) ?? status.phase ?? "idle";
    const keyBase = recoveryGuidanceKey(safeState, phase);
    return {
      message: status.error || t("settings.esp_flash.recovery.fallback_error"),
      phaseLabel: formatEspFlashPhase(phase),
      recoveryTitle: t(`${keyBase}.title`),
      recoveryDetail: t(`${keyBase}.detail`),
    };
  }

  function buildActionSummary(status: EspFlashStatusPayload): {
    canStart: boolean;
    html: string;
    startLabel: string;
  } {
    const safeState = safeEspFlashState(status.state);
    const portsDetected = availablePorts.length > 0;
    const selectedTarget = selectedTargetLabel(status);
    const readinessItems = [
      {
        label: t("settings.esp_flash.start_readiness.item.connection"),
        detail: portsDetected
          ? t("settings.esp_flash.start_readiness.item.connection_ready", {
              ports: detectedPortsLabel(),
            })
          : t("settings.esp_flash.start_readiness.item.connection_blocked"),
        state: portsDetected ? ("ready" as const) : ("blocked" as const),
      },
      {
        label: t("settings.esp_flash.start_readiness.item.target"),
        detail: portsDetected
          ? t("settings.esp_flash.start_readiness.item.target_ready", { target: selectedTarget })
          : t("settings.esp_flash.start_readiness.item.target_blocked"),
        state: portsDetected ? ("ready" as const) : ("blocked" as const),
      },
    ];
    const recovery = recoverySummary(status);
    const isRecoveryState = recovery !== null;
    const stateLabel = isRecoveryState
      ? portsDetected
        ? t(`settings.esp_flash.state.${safeState}`)
        : t("maintenance.readiness.blocked")
      : safeState === "running"
        ? t("maintenance.readiness.running")
        : portsDetected
          ? t("maintenance.readiness.ready")
          : t("maintenance.readiness.blocked");
    return {
      canStart: safeState !== "running" && portsDetected,
      startLabel: t(
        isRecoveryState ? "settings.esp_flash.retry" : "settings.esp_flash.start",
      ),
      html: renderMaintenanceReadinessPanel(
        {
          title: t(
            isRecoveryState
              ? "settings.esp_flash.recovery.title"
              : "settings.esp_flash.start_readiness.title",
          ),
          summary: t(
            isRecoveryState
              ? portsDetected
                ? "settings.esp_flash.recovery.summary_retry"
                : "settings.esp_flash.recovery.summary_blocked"
              : safeState === "running"
                ? "settings.esp_flash.start_readiness.summary_running"
                : portsDetected
                  ? "settings.esp_flash.start_readiness.summary_ready"
                  : "settings.esp_flash.start_readiness.summary_blocked",
          ),
          stateLabel,
          stateVariant: isRecoveryState ? "bad" : safeState === "running" ? "warn" : portsDetected ? "ok" : "bad",
          items: recovery
            ? [
                {
                  label: t("settings.esp_flash.recovery.item.failed_step"),
                  detail: recovery.phaseLabel,
                  state: "attention" as const,
                },
                {
                  label: t("settings.esp_flash.recovery.item.captured_detail"),
                  detail: recovery.message,
                  state: "attention" as const,
                },
                {
                  label: t("settings.esp_flash.recovery.item.next_step"),
                  detail: portsDetected
                    ? `${recovery.recoveryTitle} — ${recovery.recoveryDetail}`
                    : t("settings.esp_flash.recovery.item.next_step_blocked"),
                  state: portsDetected ? ("attention" as const) : ("blocked" as const),
                },
              ]
            : readinessItems,
        },
        escapeHtml,
      ),
    };
  }

  function syncFlashControls(status: EspFlashStatusPayload): { canStart: boolean } {
    const safeState = safeEspFlashState(status.state);
    const readiness = buildActionSummary(status);
    if (els.espFlashStartSummary) {
      els.espFlashStartSummary.innerHTML = readiness.html;
    }
    if (els.espFlashStartBtn) {
      els.espFlashStartBtn.textContent = readiness.startLabel;
      els.espFlashStartBtn.hidden = safeState === "running";
      els.espFlashStartBtn.disabled = safeState === "running" || !readiness.canStart;
    }
    if (els.espFlashCancelBtn) {
      els.espFlashCancelBtn.hidden = safeState !== "running";
      els.espFlashCancelBtn.disabled = safeState !== "running";
    }
    if (els.espFlashPortSelect) {
      els.espFlashPortSelect.disabled = safeState === "running";
    }
    if (els.espFlashRefreshPortsBtn) {
      els.espFlashRefreshPortsBtn.disabled = safeState === "running";
    }
    return readiness;
  }

  function renderReadinessPanel(): void {
    if (!els.espFlashReadinessPanel) return;
    const safeState = safeEspFlashState(latestStatus.state);
    const rows = [
      renderStatusGridRow(
        escapeHtml(t("settings.esp_flash.readiness.detected_ports")),
        escapeHtml(detectedPortsLabel()),
      ),
      renderStatusGridRow(
        escapeHtml(t("settings.esp_flash.readiness.selected_target")),
        escapeHtml(selectedTargetLabel(latestStatus)),
      ),
    ];
    if (safeState === "running") {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.current_step")),
          escapeHtml(formatEspFlashPhase(latestStatus.phase)),
        ),
      );
    }
    if (latestStatus.last_success_at != null) {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.last_success")),
          escapeHtml(formatEpochTimestamp(latestStatus.last_success_at)),
        ),
      );
    }
    const attempts = currentAttemptSummaries(latestStatus);
    if (attempts.length > 0) {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.last_result")),
          escapeHtml(latestAttemptSummary(attempts[0])),
        ),
      );
    }
    const errorHtml = latestStatus.error
      ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(latestStatus.error)}</div>`
      : "";
    els.espFlashReadinessPanel.innerHTML = `<div class="subtle">${escapeHtml(readinessSummary(latestStatus))}</div><div class="status-grid">${rows.join("")}</div>${errorHtml}`;
  }

  function renderJourneyPanel(): void {
    if (!els.espFlashJourneyPanel) return;
    els.espFlashJourneyPanel.innerHTML = renderJourney(latestStatus);
  }

  function renderLogsEmptyState(status: EspFlashStatusPayload): string {
    const safeState = safeEspFlashState(status.state);
    const titleKey = safeState === "running"
      ? "settings.esp_flash.logs_running_title"
      : safeState === "failed" || safeState === "cancelled"
        ? "settings.esp_flash.logs_failed_title"
        : "settings.esp_flash.logs_idle_title";
    const bodyKey = safeState === "running"
      ? "settings.esp_flash.logs_running_body"
      : safeState === "failed" || safeState === "cancelled"
        ? "settings.esp_flash.logs_failed_body"
        : "settings.esp_flash.logs_idle_body";
    return `<div class="empty-state empty-state--inline"><strong>${escapeHtml(t(titleKey))}</strong><span>${escapeHtml(t(bodyKey))}</span></div>`;
  }

  function renderHistoryPanel(attempts: FlashAttemptSummary[]): void {
    if (!els.espFlashHistoryPanel) return;
    if (!attempts.length) {
      els.espFlashHistoryPanel.innerHTML = `<div class="empty-state empty-state--inline"><strong>${escapeHtml(t("settings.esp_flash.history_empty_title"))}</strong><span>${escapeHtml(t("settings.esp_flash.history_empty_body"))}</span></div>`;
      return;
    }
    const rows = attempts.slice(0, 5).map((attempt) => {
      const safeState = safeEspFlashState(attempt.state);
      const stateLabel = t(`settings.esp_flash.state.${safeState}`);
      const variant = STATE_TO_VARIANT[safeState] || "muted";
      const port = attempt.selectedPort || t("settings.esp_flash.auto_detect");
      const meta = [
        attempt.finishedAt != null
          ? t("settings.esp_flash.history_finished_at", { value: formatEpochTimestamp(attempt.finishedAt) })
          : t("settings.esp_flash.history_started_at", { value: formatEpochTimestamp(attempt.startedAt) }),
        attempt.autoDetect
          ? t("settings.esp_flash.history_auto_detect_used")
          : t("settings.esp_flash.history_manual_target_used"),
      ];
      if (attempt.exitCode != null) {
        meta.push(t("settings.esp_flash.history_exit_code", { code: attempt.exitCode }));
      }
      const errorHtml = attempt.error
        ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(attempt.error)}</div>`
        : "";
      return `<li class="maintenance-attempt"><div class="maintenance-attempt__header"><span class="pill pill--${variant}">${escapeHtml(stateLabel)}</span><strong>${escapeHtml(port)}</strong></div><div class="maintenance-attempt__meta subtle">${escapeHtml(meta.join(" · "))}</div>${errorHtml}</li>`;
    });
    els.espFlashHistoryPanel.innerHTML = `<ul class="maintenance-attempt-list">${rows.join("")}</ul>`;
  }

  async function refreshPorts(): Promise<void> {
    if (!els.espFlashPortSelect) return;
    try {
      const previousValue = els.espFlashPortSelect.value || "__auto__";
      const payload = await getEspFlashPorts();
      availablePorts = payload.ports || [];
      const options = [`<option value="__auto__">${escapeHtml(t("settings.esp_flash.auto_detect"))}</option>`];
      for (const port of availablePorts) {
        const label = `${port.port}${port.description ? ` — ${port.description}` : ""}`;
        options.push(`<option value="${escapeHtml(port.port)}">${escapeHtml(label)}</option>`);
      }
      els.espFlashPortSelect.innerHTML = options.join("");
      els.espFlashPortSelect.value = availablePorts.some((port) => port.port === previousValue)
        ? previousValue
        : "__auto__";
      syncFlashControls(latestStatus);
      renderReadinessPanel();
    } catch {
      // Port list unavailable — keep existing options
    }
  }

  function renderStatus(status: EspFlashStatusPayload): void {
    if (journeyStageIndex(status.phase) !== -1) {
      latestJourneyPhase = status.phase || null;
    } else if (status.state === "idle" || status.state === "success") {
      latestJourneyPhase = null;
    }
    latestStatus = status;
    if (els.espFlashStatusBanner) {
      // Defensively fallback to "idle" when state is missing from API response
      const safeState = safeEspFlashState(status.state);
      const stateLabel = t(`settings.esp_flash.state.${safeState}`);
      const extra = status.error ? ` — ${status.error}` : "";
      els.espFlashStatusBanner.textContent = `${stateLabel}${extra}`;
      const variant = STATE_TO_VARIANT[safeState] || "muted";
      els.espFlashStatusBanner.className = `pill pill--${variant}`;
    }
    if (status.state !== "running") nextLogIndex = status.log_count || 0;
    syncFlashControls(status);
    renderReadinessPanel();
    renderHistoryPanel(currentAttemptSummaries(status));
    renderJourneyPanel();
  }

  async function refreshLogs(status: EspFlashStatusPayload): Promise<void> {
    if (!els.espFlashLogPanel) return;
    const panel = els.espFlashLogPanel;
    if (status.log_count === 0) {
      panel.className = LOG_PANEL_BASE_CLASS;
      panel.innerHTML = renderLogsEmptyState(status);
      nextLogIndex = 0;
      return;
    }
    if (nextLogIndex === 0) {
      panel.textContent = "";
    }
    panel.className = `${LOG_PANEL_BASE_CLASS} maintenance-log-panel`;
    const logs = await getEspFlashLogs(nextLogIndex);
    if (logs.lines.length > 0) {
      panel.textContent += `${logs.lines.join("\n")}\n`;
      panel.scrollTop = panel.scrollHeight;
    }
    nextLogIndex = logs.next_index;
  }

  async function refreshHistory(): Promise<void> {
    if (!els.espFlashHistoryPanel) return;
    let payload: EspFlashHistoryPayload;
    try {
      payload = await getEspFlashHistory();
    } catch {
      // History is non-critical; keep existing panel content on transient error.
      return;
    }
    latestAttempts = payload.attempts || [];
    renderHistoryPanel(currentAttemptSummaries(latestStatus));
    renderReadinessPanel();
  }

  const polling = createPollingController({
    poll: async () => {
      const status = await getEspFlashStatus();
      renderStatus(status);
      await refreshLogs(status);
      await refreshHistory();
      return status.state === "running"
        ? ESP_FLASH_POLL_ACTIVE_MS
        : ESP_FLASH_POLL_IDLE_MS;
    },
    onErrorDelayMs: ESP_FLASH_POLL_ACTIVE_MS,
  });

  async function onStart(): Promise<void> {
    const readiness = syncFlashControls(latestStatus);
    if (!readiness.canStart) {
      return;
    }
    const selected = els.espFlashPortSelect?.value || "__auto__";
    const autoDetect = selected === "__auto__";
    const port = autoDetect ? null : selected;
    try {
      await startEspFlash(port, autoDetect);
      if (els.espFlashLogPanel) {
        els.espFlashLogPanel.className = LOG_PANEL_BASE_CLASS;
        els.espFlashLogPanel.textContent = "";
      }
      nextLogIndex = 0;
      polling.restart();
    } catch (err) {
      ctx.showError(`${t("settings.esp_flash.start_failed")}\n${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function onCancel(): Promise<void> {
    try {
      await cancelEspFlash();
    } catch {
      // Cancel request may fail if the job already finished; poll to sync state.
    }
    polling.restart();
  }

  function bindHandlers(): void {
    els.espFlashStartBtn?.addEventListener("click", () => void onStart());
    els.espFlashCancelBtn?.addEventListener("click", () => void onCancel());
    els.espFlashRefreshPortsBtn?.addEventListener("click", () => void refreshPorts());
    els.espFlashPortSelect?.addEventListener("change", () => {
      syncFlashControls(latestStatus);
      renderReadinessPanel();
    });
    syncFlashControls(latestStatus);
  }

  function startPolling(): void {
    void refreshPorts();
    polling.start();
  }

  function stopPolling(): void {
    polling.stop();
  }

  return { bindHandlers, startPolling, stopPolling };
}
