import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../api/types";
import { formatEpochTimestamp } from "../../format";
import type { VisualVariant } from "../visual_variant";
import type { MaintenanceReadinessPanelModel } from "./maintenance_readiness_view";
import type {
  EspFlashReadinessPanelModel,
  EspFlashStatusBadgeModel,
  EspFlashStatusGridRowModel,
} from "./esp_flash_panel";

const STATE_TO_VARIANT: Readonly<Record<string, VisualVariant>> = {
  failed: "bad",
  running: "warn",
  success: "ok",
};

const JOURNEY_PHASES = new Set([
  "validating",
  "preparing",
  "erasing",
  "flashing",
  "done",
]);

export interface EspFlashFeatureRenderState {
  attempts: readonly EspFlashHistoryAttemptPayload[];
  availablePorts: readonly EspSerialPortPayload[];
  lastJourneyPhase: string | null;
  logText: string;
  selectedPortValue: string;
  status: EspFlashStatusPayload;
}

export interface FlashAttemptSummary {
  autoDetect: boolean;
  error: string | null;
  exitCode: number | null;
  finishedAt: number | null;
  selectedPort: string | null;
  startedAt: number | null;
  state: string;
}

export function safeEspFlashState(state: string | null | undefined): string {
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

export function formatEspFlashPhase(
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

export function currentAttemptSummaries(
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
  const phase =
    state.status.phase && JOURNEY_PHASES.has(state.status.phase)
      ? state.status.phase
      : state.lastJourneyPhase ?? state.status.phase ?? "idle";
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

export function buildActionSummary(
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

export function buildReadinessPanelModel(
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

export function statusVariantForEspFlashState(state: string): VisualVariant {
  return STATE_TO_VARIANT[state] ?? "muted";
}

export function buildStatusBannerModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashStatusBadgeModel {
  const safeState = safeEspFlashState(state.status.state);
  const stateLabel = t(`settings.esp_flash.state.${safeState}`);
  return {
    text: state.status.error ? `${stateLabel} — ${state.status.error}` : stateLabel,
    variant: statusVariantForEspFlashState(safeState),
  };
}
