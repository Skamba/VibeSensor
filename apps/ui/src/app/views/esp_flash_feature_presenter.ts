import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../transport/http_models";
import type { EspFlashPanelDom } from "./esp_flash_panel";
import { formatEpochTimestamp, renderStatusGridRow } from "./dom_helpers";
import {
  renderMaintenanceReadinessPanel,
  type MaintenanceReadinessPanelModel,
} from "./maintenance_readiness_view";
import { setVariantState, type VisualVariant } from "../style_state";

const LOG_PANEL_BASE_CLASS = "maintenance-log-slot";

const STATE_TO_VARIANT: Readonly<Record<string, VisualVariant>> = {
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

export interface EspFlashFeatureRenderState {
  attempts: readonly EspFlashHistoryAttemptPayload[];
  availablePorts: readonly EspSerialPortPayload[];
  lastJourneyPhase: string | null;
  logText: string;
  selectedPortValue: string;
  status: EspFlashStatusPayload;
}

export interface EspFlashFeaturePresenterDeps {
  dom: EspFlashPanelDom;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
}

export interface EspFlashFeaturePresenter {
  render(state: EspFlashFeatureRenderState): void;
}

function safeEspFlashState(state: string | null | undefined): string {
  return state || "idle";
}

export function createEspFlashFeaturePresenter(
  ctx: EspFlashFeaturePresenterDeps,
): EspFlashFeaturePresenter {
  const { dom: els, t, escapeHtml } = ctx;

  function translateKeyOrFallback(key: string, fallback: string): string {
    const translated = t(key);
    return translated === key ? fallback : translated;
  }

  function formatEspFlashPhase(phase: string | null | undefined): string {
    const safePhase = phase || "idle";
    return translateKeyOrFallback(
      `settings.esp_flash.phase.${safePhase}`,
      safePhase,
    );
  }

  function stageStateLabel(state: JourneyStageState): string {
    return t(`maintenance.stage_state.${state}`);
  }

  function journeyStageIndex(phase: string | null | undefined): number {
    return ESP_FLASH_JOURNEY_STAGES.findIndex(
      (stage) => stage.phase === (phase || "idle"),
    );
  }

  function resolvedJourneyPhase(
    state: EspFlashFeatureRenderState,
  ): string | null {
    if (journeyStageIndex(state.status.phase) !== -1) {
      return state.status.phase || null;
    }
    const safeState = safeEspFlashState(state.status.state);
    if (safeState === "failed" || safeState === "cancelled") {
      return state.lastJourneyPhase;
    }
    return null;
  }

  function resolveJourneyStageState(
    state: EspFlashFeatureRenderState,
    stageIndex: number,
  ): JourneyStageState {
    const safeState = safeEspFlashState(state.status.state);
    if (safeState === "success") {
      return "done";
    }
    if (safeState === "idle") {
      return "upcoming";
    }
    const currentIndex = journeyStageIndex(resolvedJourneyPhase(state));
    if (currentIndex === -1) {
      return "upcoming";
    }
    if (stageIndex < currentIndex) {
      return "done";
    }
    if (stageIndex === currentIndex) {
      return safeState === "failed" || safeState === "cancelled"
        ? "attention"
        : "active";
    }
    return "upcoming";
  }

  function renderJourney(state: EspFlashFeatureRenderState): string {
    const items = ESP_FLASH_JOURNEY_STAGES.map((stage, index) => {
      const stageState = resolveJourneyStageState(state, index);
      const markerLabel = stageState === "done" ? "✓" : `${index + 1}`;
      const currentStepAttr =
        stageState === "active" ? ' aria-current="step"' : "";
      return `<li class="maintenance-stage" data-stage-phase="${stage.phase}" data-stage-state="${stageState}"${currentStepAttr}>
        <span class="maintenance-stage__marker">${markerLabel}</span>
        <div class="maintenance-stage__body">
          <div class="maintenance-stage__title">${escapeHtml(t(stage.titleKey))}</div>
          <div class="maintenance-stage__detail">${escapeHtml(t(stage.detailKey))}</div>
        </div>
        <span class="maintenance-stage__state">${escapeHtml(stageStateLabel(stageState))}</span>
      </li>`;
    }).join("");
    const terminalState = safeEspFlashState(state.status.state);
    const terminalNote =
      terminalState === "failed" || terminalState === "cancelled"
        ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(t(`settings.esp_flash.journey_terminal.${terminalState}`))}</div>`
        : "";
    return `<div class="maintenance-journey">
      ${terminalNote}
      <ol class="maintenance-stage-list">${items}</ol>
    </div>`;
  }

  function selectedTargetLabel(state: EspFlashFeatureRenderState): string {
    const selectedValue = state.selectedPortValue;
    const raw =
      state.status.selected_port ||
      (selectedValue !== "__auto__" ? selectedValue : null);
    return raw || t("settings.esp_flash.auto_detect");
  }

  function detectedPortsLabel(state: EspFlashFeatureRenderState): string {
    if (state.availablePorts.length === 0) {
      return t("settings.esp_flash.readiness.no_ports");
    }
    if (state.availablePorts.length === 1) {
      const port = state.availablePorts[0];
      const label = port.description
        ? `${port.port} — ${port.description}`
        : port.port;
      return t("settings.esp_flash.readiness.one_port", { port: label });
    }
    return t("settings.esp_flash.readiness.multiple_ports", {
      count: state.availablePorts.length,
    });
  }

  function readinessSummary(state: EspFlashFeatureRenderState): string {
    const safeState = safeEspFlashState(state.status.state);
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
        return state.availablePorts.length > 0
          ? t("settings.esp_flash.readiness.summary.ready_ports")
          : t("settings.esp_flash.readiness.summary.ready_no_ports");
    }
  }

  function latestAttemptSummary(attempt: FlashAttemptSummary): string {
    const stateLabel = t(
      `settings.esp_flash.state.${safeEspFlashState(attempt.state)}`,
    );
    const when = formatEpochTimestamp(attempt.finishedAt ?? attempt.startedAt);
    return t("settings.esp_flash.last_result_value", {
      state: stateLabel,
      when,
    });
  }

  function currentAttemptSummaries(
    state: EspFlashFeatureRenderState,
  ): FlashAttemptSummary[] {
    if (state.attempts.length > 0) {
      return state.attempts.map((attempt) => ({
        autoDetect: attempt.auto_detect,
        error: attempt.error ?? null,
        exitCode: attempt.exit_code ?? null,
        finishedAt: attempt.finished_at ?? null,
        selectedPort: attempt.selected_port ?? null,
        startedAt: attempt.started_at ?? null,
        state: safeEspFlashState(attempt.state),
      }));
    }
    const safeState = safeEspFlashState(state.status.state);
    if (safeState === "idle" || safeState === "running") {
      return [];
    }
    return [
      {
        autoDetect: state.status.auto_detect,
        error: state.status.error ?? null,
        exitCode: state.status.exit_code ?? null,
        finishedAt: state.status.finished_at ?? null,
        selectedPort: state.status.selected_port ?? null,
        startedAt: state.status.started_at ?? null,
        state: safeState,
      },
    ];
  }

  function recoverySummary(state: EspFlashFeatureRenderState): {
    message: string;
    phaseLabel: string;
    recoveryDetail: string;
    recoveryTitle: string;
  } | null {
    const safeState = safeEspFlashState(state.status.state);
    if (safeState !== "failed" && safeState !== "cancelled") {
      return null;
    }
    const phase = resolvedJourneyPhase(state) ?? state.status.phase ?? "idle";
    const keyBase =
      safeState === "cancelled"
        ? "settings.esp_flash.recovery.cancelled"
        : phase === "preparing"
          ? "settings.esp_flash.recovery.preparing"
          : phase === "erasing"
            ? "settings.esp_flash.recovery.erasing"
            : phase === "flashing"
              ? "settings.esp_flash.recovery.flashing"
              : phase === "validating"
                ? "settings.esp_flash.recovery.validating"
                : "settings.esp_flash.recovery.generic";
    return {
      message:
        state.status.error || t("settings.esp_flash.recovery.fallback_error"),
      phaseLabel: formatEspFlashPhase(phase),
      recoveryTitle: t(`${keyBase}.title`),
      recoveryDetail: t(`${keyBase}.detail`),
    };
  }

  function buildActionSummary(state: EspFlashFeatureRenderState): {
    canStart: boolean;
    panelModel: MaintenanceReadinessPanelModel;
    startLabel: string;
  } {
    const safeState = safeEspFlashState(state.status.state);
    const portsDetected = state.availablePorts.length > 0;
    const selectedTarget = selectedTargetLabel(state);
    const readinessItems = [
      {
        label: t("settings.esp_flash.start_readiness.item.connection"),
        detail: portsDetected
          ? t("settings.esp_flash.start_readiness.item.connection_ready", {
              ports: detectedPortsLabel(state),
            })
          : t("settings.esp_flash.start_readiness.item.connection_blocked"),
        state: portsDetected ? ("ready" as const) : ("blocked" as const),
      },
      {
        label: t("settings.esp_flash.start_readiness.item.target"),
        detail: portsDetected
          ? t("settings.esp_flash.start_readiness.item.target_ready", {
              target: selectedTarget,
            })
          : t("settings.esp_flash.start_readiness.item.target_blocked"),
        state: portsDetected ? ("ready" as const) : ("blocked" as const),
      },
    ];
    const recovery = recoverySummary(state);
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
        isRecoveryState
          ? "settings.esp_flash.retry"
          : "settings.esp_flash.start",
      ),
      panelModel: {
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
        stateVariant: isRecoveryState
          ? "bad"
          : safeState === "running"
            ? "warn"
            : portsDetected
              ? "ok"
              : "bad",
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
                state: portsDetected
                  ? ("attention" as const)
                  : ("blocked" as const),
              },
            ]
          : readinessItems,
      },
    };
  }

  function renderPortOptions(state: EspFlashFeatureRenderState): void {
    if (!els.espFlashPortSelect) {
      return;
    }
    const options = [
      `<option value="__auto__">${escapeHtml(t("settings.esp_flash.auto_detect"))}</option>`,
    ];
    for (const port of state.availablePorts) {
      const label = `${port.port}${port.description ? ` — ${port.description}` : ""}`;
      options.push(
        `<option value="${escapeHtml(port.port)}">${escapeHtml(label)}</option>`,
      );
    }
    els.espFlashPortSelect.innerHTML = options.join("");
    els.espFlashPortSelect.value = state.selectedPortValue;
  }

  function syncFlashControls(
    state: EspFlashFeatureRenderState,
    actionSummary: {
      canStart: boolean;
      panelModel: MaintenanceReadinessPanelModel;
      startLabel: string;
    },
  ): void {
    const safeState = safeEspFlashState(state.status.state);
    if (els.espFlashStartSummary) {
      els.espFlashStartSummary.innerHTML = renderMaintenanceReadinessPanel(
        actionSummary.panelModel,
        escapeHtml,
      );
    }
    if (els.espFlashStartBtn) {
      els.espFlashStartBtn.textContent = actionSummary.startLabel;
      els.espFlashStartBtn.hidden = safeState === "running";
      els.espFlashStartBtn.disabled =
        safeState === "running" || !actionSummary.canStart;
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
  }

  function renderReadinessPanel(state: EspFlashFeatureRenderState): void {
    if (!els.espFlashReadinessPanel) {
      return;
    }
    const safeState = safeEspFlashState(state.status.state);
    const rows = [
      renderStatusGridRow(
        escapeHtml(t("settings.esp_flash.readiness.detected_ports")),
        escapeHtml(detectedPortsLabel(state)),
      ),
      renderStatusGridRow(
        escapeHtml(t("settings.esp_flash.readiness.selected_target")),
        escapeHtml(selectedTargetLabel(state)),
      ),
    ];
    if (safeState === "running") {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.current_step")),
          escapeHtml(formatEspFlashPhase(state.status.phase)),
        ),
      );
    }
    if (state.status.last_success_at != null) {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.last_success")),
          escapeHtml(formatEpochTimestamp(state.status.last_success_at)),
        ),
      );
    }
    const attempts = currentAttemptSummaries(state);
    if (attempts.length > 0) {
      rows.push(
        renderStatusGridRow(
          escapeHtml(t("settings.esp_flash.readiness.last_result")),
          escapeHtml(latestAttemptSummary(attempts[0])),
        ),
      );
    }
    const errorHtml = state.status.error
      ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(state.status.error)}</div>`
      : "";
    els.espFlashReadinessPanel.innerHTML = `<div class="subtle">${escapeHtml(readinessSummary(state))}</div><div class="status-grid">${rows.join("")}</div>${errorHtml}`;
  }

  function renderJourneyPanel(state: EspFlashFeatureRenderState): void {
    if (!els.espFlashJourneyPanel) {
      return;
    }
    els.espFlashJourneyPanel.innerHTML = renderJourney(state);
  }

  function renderLogsEmptyState(status: EspFlashStatusPayload): string {
    const safeState = safeEspFlashState(status.state);
    const titleKey =
      safeState === "running"
        ? "settings.esp_flash.logs_running_title"
        : safeState === "failed" || safeState === "cancelled"
          ? "settings.esp_flash.logs_failed_title"
          : "settings.esp_flash.logs_idle_title";
    const bodyKey =
      safeState === "running"
        ? "settings.esp_flash.logs_running_body"
        : safeState === "failed" || safeState === "cancelled"
          ? "settings.esp_flash.logs_failed_body"
          : "settings.esp_flash.logs_idle_body";
    return `<div class="empty-state empty-state--inline"><strong>${escapeHtml(t(titleKey))}</strong><span>${escapeHtml(t(bodyKey))}</span></div>`;
  }

  function renderHistoryPanel(state: EspFlashFeatureRenderState): void {
    if (!els.espFlashHistoryPanel) {
      return;
    }
    const attempts = currentAttemptSummaries(state);
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
          ? t("settings.esp_flash.history_finished_at", {
              value: formatEpochTimestamp(attempt.finishedAt),
            })
          : t("settings.esp_flash.history_started_at", {
              value: formatEpochTimestamp(attempt.startedAt),
            }),
        attempt.autoDetect
          ? t("settings.esp_flash.history_auto_detect_used")
          : t("settings.esp_flash.history_manual_target_used"),
      ];
      if (attempt.exitCode != null) {
        meta.push(
          t("settings.esp_flash.history_exit_code", { code: attempt.exitCode }),
        );
      }
      const errorHtml = attempt.error
        ? `<div class="maintenance-note maintenance-note--bad">${escapeHtml(attempt.error)}</div>`
        : "";
      return `<li class="maintenance-attempt"><div class="maintenance-attempt__header"><span class="pill" data-variant="${variant}">${escapeHtml(stateLabel)}</span><strong>${escapeHtml(port)}</strong></div><div class="maintenance-attempt__meta subtle">${escapeHtml(meta.join(" · "))}</div>${errorHtml}</li>`;
    });
    els.espFlashHistoryPanel.innerHTML = `<ul class="maintenance-attempt-list">${rows.join("")}</ul>`;
  }

  function renderStatusBanner(state: EspFlashFeatureRenderState): void {
    if (!els.espFlashStatusBanner) {
      return;
    }
    const safeState = safeEspFlashState(state.status.state);
    const stateLabel = t(`settings.esp_flash.state.${safeState}`);
    const extra = state.status.error ? ` — ${state.status.error}` : "";
    els.espFlashStatusBanner.textContent = `${stateLabel}${extra}`;
    const variant = STATE_TO_VARIANT[safeState] || "muted";
    els.espFlashStatusBanner.className = "pill";
    setVariantState(els.espFlashStatusBanner, variant);
  }

  function renderLogPanel(state: EspFlashFeatureRenderState): void {
    if (!els.espFlashLogPanel) {
      return;
    }
    const panel = els.espFlashLogPanel;
    if (state.status.log_count === 0 && state.logText.length === 0) {
      panel.className = LOG_PANEL_BASE_CLASS;
      panel.innerHTML = renderLogsEmptyState(state.status);
      return;
    }
    panel.className = `${LOG_PANEL_BASE_CLASS} maintenance-log-panel`;
    panel.textContent = state.logText;
    panel.scrollTop = panel.scrollHeight;
  }

  function render(state: EspFlashFeatureRenderState): void {
    renderPortOptions(state);
    renderStatusBanner(state);
    const actionSummary = buildActionSummary(state);
    syncFlashControls(state, actionSummary);
    renderReadinessPanel(state);
    renderJourneyPanel(state);
    renderHistoryPanel(state);
    renderLogPanel(state);
  }

  return {
    render,
  };
}
