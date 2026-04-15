import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../transport/http_models";
import type { VisualVariant } from "../style_state";
import { formatEpochTimestamp } from "./dom_helpers";
import type { MaintenanceReadinessPanelModel } from "./maintenance_readiness_view";
import type {
  EspFlashHistoryAttemptModel,
  EspFlashHistoryPanelModel,
  EspFlashJourneyPanelModel,
  EspFlashJourneyStageModel,
  EspFlashJourneyStageState,
  EspFlashLogPanelModel,
  EspFlashPanelRenderModel,
  EspFlashPanelView,
  EspFlashReadinessPanelModel,
  EspFlashStatusBadgeModel,
  EspFlashStatusGridRowModel,
} from "./esp_flash_panel";

const STATE_TO_VARIANT: Readonly<Record<string, VisualVariant>> = {
  failed: "bad",
  running: "warn",
  success: "ok",
};

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
    detailKey: "settings.esp_flash.journey.detail.validating",
    phase: "validating",
    titleKey: "settings.esp_flash.phase.validating",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.preparing",
    phase: "preparing",
    titleKey: "settings.esp_flash.phase.preparing",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.erasing",
    phase: "erasing",
    titleKey: "settings.esp_flash.phase.erasing",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.flashing",
    phase: "flashing",
    titleKey: "settings.esp_flash.phase.flashing",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.done",
    phase: "done",
    titleKey: "settings.esp_flash.phase.done",
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
  panel: EspFlashPanelView;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface EspFlashFeaturePresenter {
  render(state: EspFlashFeatureRenderState): void;
}

function safeEspFlashState(state: string | null | undefined): string {
  return state || "idle";
}

function translateKeyOrFallback(
  t: (key: string, vars?: Record<string, unknown>) => string,
  key: string,
  fallback: string,
): string {
  const translated = t(key);
  return translated === key ? fallback : translated;
}

function formatEspFlashPhase(
  t: (key: string, vars?: Record<string, unknown>) => string,
  phase: string | null | undefined,
): string {
  const safePhase = phase || "idle";
  return translateKeyOrFallback(
    t,
    `settings.esp_flash.phase.${safePhase}`,
    safePhase,
  );
}

function stageStateLabel(
  t: (key: string, vars?: Record<string, unknown>) => string,
  state: EspFlashJourneyStageState,
): string {
  return t(`maintenance.stage_state.${state}`);
}

function journeyStageIndex(phase: string | null | undefined): number {
  return ESP_FLASH_JOURNEY_STAGES.findIndex(
    (stage) => stage.phase === (phase || "idle"),
  );
}

function resolvedJourneyPhase(state: EspFlashFeatureRenderState): string | null {
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
): EspFlashJourneyStageState {
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

function buildJourneyPanelModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashJourneyPanelModel {
  const stages: EspFlashJourneyStageModel[] = ESP_FLASH_JOURNEY_STAGES.map(
    (stage, index) => {
      const stageState = resolveJourneyStageState(state, index);
      return {
        current: stageState === "active",
        detailText: t(stage.detailKey),
        markerText: stageState === "done" ? "\u2713" : `${index + 1}`,
        phase: stage.phase,
        state: stageState,
        stateText: stageStateLabel(t, stageState),
        titleText: t(stage.titleKey),
      };
    },
  );
  const terminalState = safeEspFlashState(state.status.state);
  return {
    stages,
    terminalNoteText:
      terminalState === "failed" || terminalState === "cancelled"
        ? t(`settings.esp_flash.journey_terminal.${terminalState}`)
        : null,
  };
}

function selectedTargetLabel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const selectedValue = state.selectedPortValue;
  const raw =
    state.status.selected_port ||
    (selectedValue !== "__auto__" ? selectedValue : null);
  return raw || t("settings.esp_flash.auto_detect");
}

function detectedPortsLabel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
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

function readinessSummary(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
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

function latestAttemptSummary(
  attempt: FlashAttemptSummary,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
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

function recoverySummary(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): {
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
    message: state.status.error || t("settings.esp_flash.recovery.fallback_error"),
    phaseLabel: formatEspFlashPhase(t, phase),
    recoveryDetail: t(`${keyBase}.detail`),
    recoveryTitle: t(`${keyBase}.title`),
  };
}

function buildActionSummary(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): {
  canStart: boolean;
  panelModel: MaintenanceReadinessPanelModel;
  startLabel: string;
} {
  const safeState = safeEspFlashState(state.status.state);
  const portsDetected = state.availablePorts.length > 0;
  const selectedTarget = selectedTargetLabel(state, t);
  const readinessItems = [
    {
      detail: portsDetected
        ? t("settings.esp_flash.start_readiness.item.connection_ready", {
            ports: detectedPortsLabel(state, t),
          })
        : t("settings.esp_flash.start_readiness.item.connection_blocked"),
      label: t("settings.esp_flash.start_readiness.item.connection"),
      state: portsDetected ? ("ready" as const) : ("blocked" as const),
    },
    {
      detail: portsDetected
        ? t("settings.esp_flash.start_readiness.item.target_ready", {
            target: selectedTarget,
          })
        : t("settings.esp_flash.start_readiness.item.target_blocked"),
      label: t("settings.esp_flash.start_readiness.item.target"),
      state: portsDetected ? ("ready" as const) : ("blocked" as const),
    },
  ];
  const recovery = recoverySummary(state, t);
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
    panelModel: {
      items: recovery
        ? [
            {
              detail: recovery.phaseLabel,
              label: t("settings.esp_flash.recovery.item.failed_step"),
              state: "attention" as const,
            },
            {
              detail: recovery.message,
              label: t("settings.esp_flash.recovery.item.captured_detail"),
              state: "attention" as const,
            },
            {
              detail: portsDetected
                ? `${recovery.recoveryTitle} — ${recovery.recoveryDetail}`
                : t("settings.esp_flash.recovery.item.next_step_blocked"),
              label: t("settings.esp_flash.recovery.item.next_step"),
              state: portsDetected
                ? ("attention" as const)
                : ("blocked" as const),
            },
          ]
        : readinessItems,
      stateLabel,
      stateVariant: isRecoveryState
        ? "bad"
        : safeState === "running"
          ? "warn"
          : portsDetected
            ? "ok"
            : "bad",
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
      title: t(
        isRecoveryState
          ? "settings.esp_flash.recovery.title"
          : "settings.esp_flash.start_readiness.title",
      ),
    },
    startLabel: t(
      isRecoveryState ? "settings.esp_flash.retry" : "settings.esp_flash.start",
    ),
  };
}

function buildReadinessPanelModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashReadinessPanelModel {
  const safeState = safeEspFlashState(state.status.state);
  const rows: EspFlashStatusGridRowModel[] = [
    {
      labelText: t("settings.esp_flash.readiness.detected_ports"),
      valueText: detectedPortsLabel(state, t),
    },
    {
      labelText: t("settings.esp_flash.readiness.selected_target"),
      valueText: selectedTargetLabel(state, t),
    },
  ];
  if (safeState === "running") {
    rows.push({
      labelText: t("settings.esp_flash.readiness.current_step"),
      valueText: formatEspFlashPhase(t, state.status.phase),
    });
  }
  if (state.status.last_success_at != null) {
    rows.push({
      labelText: t("settings.esp_flash.readiness.last_success"),
      valueText: formatEpochTimestamp(state.status.last_success_at),
    });
  }
  const attempts = currentAttemptSummaries(state);
  if (attempts.length > 0) {
    rows.push({
      labelText: t("settings.esp_flash.readiness.last_result"),
      valueText: latestAttemptSummary(attempts[0], t),
    });
  }
  return {
    errorText: state.status.error ?? null,
    rows,
    summaryText: readinessSummary(state, t),
  };
}

function buildStatusBannerModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashStatusBadgeModel {
  const safeState = safeEspFlashState(state.status.state);
  const stateLabel = t(`settings.esp_flash.state.${safeState}`);
  return {
    text: state.status.error ? `${stateLabel} — ${state.status.error}` : stateLabel,
    variant: STATE_TO_VARIANT[safeState] ?? "muted",
  };
}

function buildLogPanelModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashLogPanelModel {
  if (state.status.log_count === 0 && state.logText.length === 0) {
    const safeState = safeEspFlashState(state.status.state);
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
    return {
      emptyState: {
        bodyText: t(bodyKey),
        titleText: t(titleKey),
      },
      text: "",
    };
  }
  return {
    emptyState: null,
    text: state.logText,
  };
}

function buildHistoryPanelModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashHistoryPanelModel {
  const attempts = currentAttemptSummaries(state);
  if (attempts.length === 0) {
    return {
      attempts: [],
      emptyState: {
        bodyText: t("settings.esp_flash.history_empty_body"),
        titleText: t("settings.esp_flash.history_empty_title"),
      },
    };
  }
  const items: EspFlashHistoryAttemptModel[] = attempts.slice(0, 5).map((attempt) => {
    const safeState = safeEspFlashState(attempt.state);
    const portText = attempt.selectedPort || t("settings.esp_flash.auto_detect");
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
    return {
      badge: {
        text: t(`settings.esp_flash.state.${safeState}`),
        variant: STATE_TO_VARIANT[safeState] ?? "muted",
      },
      errorText: attempt.error,
      metaText: meta.join(" · "),
      portText,
    };
  });
  return {
    attempts: items,
    emptyState: null,
  };
}

function buildPortOptions(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashPanelRenderModel["portOptions"] {
  return [
    {
      labelText: t("settings.esp_flash.auto_detect"),
      value: "__auto__",
    },
    ...state.availablePorts.map((port) => ({
      labelText: `${port.port}${port.description ? ` — ${port.description}` : ""}`,
      value: port.port,
    })),
  ];
}

export function buildEspFlashPanelRenderModel(
  state: EspFlashFeatureRenderState,
  deps: {
    t: (key: string, vars?: Record<string, unknown>) => string;
  },
): EspFlashPanelRenderModel {
  const actionSummary = buildActionSummary(state, deps.t);
  const safeState = safeEspFlashState(state.status.state);
  const running = safeState === "running";
  return {
    cancelButtonDisabled: !running,
    cancelButtonHidden: !running,
    history: buildHistoryPanelModel(state, deps.t),
    journey: buildJourneyPanelModel(state, deps.t),
    log: buildLogPanelModel(state, deps.t),
    portOptions: buildPortOptions(state, deps.t),
    portSelectDisabled: running,
    readiness: buildReadinessPanelModel(state, deps.t),
    refreshPortsDisabled: running,
    selectedPortValue: state.selectedPortValue,
    startButtonDisabled: running || !actionSummary.canStart,
    startButtonHidden: running,
    startButtonLabelText: actionSummary.startLabel,
    startSummary: actionSummary.panelModel,
    statusBanner: buildStatusBannerModel(state, deps.t),
  };
}

export function createEspFlashFeaturePresenter(
  ctx: EspFlashFeaturePresenterDeps,
): EspFlashFeaturePresenter {
  return {
    render(state) {
      const model = buildEspFlashPanelRenderModel(state, { t: ctx.t });
      ctx.panel.setModel(model);
    },
  };
}
