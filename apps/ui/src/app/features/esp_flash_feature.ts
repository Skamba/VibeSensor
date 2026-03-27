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

export function createEspFlashFeature(ctx: EspFlashFeatureDeps): EspFlashFeature {
  const { els, t, escapeHtml } = ctx;
  let nextLogIndex = 0;
  let latestStatus: EspFlashStatusPayload | null = null;
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

  function resolveJourneyStageState(status: EspFlashStatusPayload, stageIndex: number): JourneyStageState {
    if (status.state === "success") return "done";
    if (status.state === "idle") return "upcoming";
    const currentIndex = ESP_FLASH_JOURNEY_STAGES.findIndex((stage) => stage.phase === (status.phase || "idle"));
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
      return `<li class="maintenance-stage maintenance-stage--${stageState}">
        <span class="maintenance-stage__marker">${index + 1}</span>
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
      <div class="maintenance-journey__title">${escapeHtml(t("settings.esp_flash.journey_title"))}</div>
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

  function latestAttemptSummary(attempt: EspFlashHistoryAttemptPayload): string {
    const stateLabel = t(`settings.esp_flash.state.${safeEspFlashState(attempt.state)}`);
    const when = formatEpochTimestamp(attempt.finished_at ?? attempt.started_at);
    return t("settings.esp_flash.last_result_value", { state: stateLabel, when });
  }

  function renderReadinessPanel(): void {
    if (!els.espFlashReadinessPanel || !latestStatus) return;
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
    if (latestAttempts.length > 0) {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.last_result")),
          escapeHtml(latestAttemptSummary(latestAttempts[0])),
        ),
      );
    }
    const errorHtml = latestStatus.error
      ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(latestStatus.error)}</div>`
      : "";
    els.espFlashReadinessPanel.innerHTML = `<div class="subtle">${escapeHtml(readinessSummary(latestStatus))}</div><div class="status-grid">${rows.join("")}</div>${renderJourney(latestStatus)}${errorHtml}`;
  }

  function renderLogsEmptyState(status: EspFlashStatusPayload): string {
    const safeState = safeEspFlashState(status.state);
    const titleKey = safeState === "running"
      ? "settings.esp_flash.logs_running_title"
      : "settings.esp_flash.logs_idle_title";
    const bodyKey = safeState === "running"
      ? "settings.esp_flash.logs_running_body"
      : "settings.esp_flash.logs_idle_body";
    return `<div class="empty-state empty-state--inline"><strong>${escapeHtml(t(titleKey))}</strong><span>${escapeHtml(t(bodyKey))}</span></div>`;
  }

  function renderHistoryPanel(attempts: EspFlashHistoryAttemptPayload[]): void {
    if (!els.espFlashHistoryPanel) return;
    if (!attempts.length) {
      els.espFlashHistoryPanel.innerHTML = `<div class="empty-state empty-state--inline"><strong>${escapeHtml(t("settings.esp_flash.history_empty_title"))}</strong><span>${escapeHtml(t("settings.esp_flash.history_empty_body"))}</span></div>`;
      return;
    }
    const rows = attempts.slice(0, 5).map((attempt) => {
      const safeState = safeEspFlashState(attempt.state);
      const stateLabel = t(`settings.esp_flash.state.${safeState}`);
      const variant = STATE_TO_VARIANT[safeState] || "muted";
      const port = attempt.selected_port || t("settings.esp_flash.auto_detect");
      const meta = [
        attempt.finished_at != null
          ? t("settings.esp_flash.history_finished_at", { value: formatEpochTimestamp(attempt.finished_at) })
          : t("settings.esp_flash.history_started_at", { value: formatEpochTimestamp(attempt.started_at) }),
        attempt.auto_detect
          ? t("settings.esp_flash.history_auto_detect_used")
          : t("settings.esp_flash.history_manual_target_used"),
      ];
      if (attempt.exit_code != null) {
        meta.push(t("settings.esp_flash.history_exit_code", { code: attempt.exit_code }));
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
      const payload = await getEspFlashPorts();
      availablePorts = payload.ports || [];
      const options = [`<option value="__auto__">${escapeHtml(t("settings.esp_flash.auto_detect"))}</option>`];
      for (const port of availablePorts) {
        const label = `${port.port}${port.description ? ` — ${port.description}` : ""}`;
        options.push(`<option value="${escapeHtml(port.port)}">${escapeHtml(label)}</option>`);
      }
      els.espFlashPortSelect.innerHTML = options.join("");
      renderReadinessPanel();
    } catch {
      // Port list unavailable — keep existing options
    }
  }

  function renderStatus(status: EspFlashStatusPayload): void {
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
    if (els.espFlashStartBtn) els.espFlashStartBtn.disabled = status.state === "running";
    if (els.espFlashCancelBtn) els.espFlashCancelBtn.disabled = status.state !== "running";
    if (els.espFlashPortSelect) els.espFlashPortSelect.disabled = status.state === "running";
    if (status.state !== "running") nextLogIndex = status.log_count || 0;
    renderReadinessPanel();
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
    renderHistoryPanel(latestAttempts);
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
