import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../api/types";
import type {
  Readiness,
  ReadinessItem,
  Stage,
  StageState,
  StatusRow,
  Variant,
} from "../../components/maintenance";
import { formatEpochTimestamp } from "../../format";

/** Pure text and state derivations for the ESP flash page. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

export const AUTO_PORT = "__auto__";
const JOURNEY_PHASES = [
  "validating",
  "preparing",
  "erasing",
  "flashing",
  "done",
] as const;
const STATE_VARIANTS: Record<string, Variant> = {
  failed: "bad",
  running: "warn",
  success: "ok",
};

export interface FlashView {
  status: EspFlashStatusPayload;
  ports: readonly EspSerialPortPayload[];
  selectedPort: string;
  attempts: readonly EspFlashHistoryAttemptPayload[];
  lastJourneyPhase: string | null;
}

export interface AttemptItem {
  state: string;
  stateText: string;
  variant: Variant;
  port: string;
  meta: string;
  error: string | null;
}

export function flashState(status: EspFlashStatusPayload): string {
  return status.state || "idle";
}

function isJourneyPhase(phase: string | null | undefined): phase is string {
  return JOURNEY_PHASES.some((journeyPhase) => journeyPhase === phase);
}

function stopped(state: string): boolean {
  return state === "failed" || state === "cancelled";
}

/**
 * Remembers the last journey step so a later status that only says "failed"
 * still points at the step that failed.
 */
export function nextJourneyPhase(
  previous: string | null,
  status: EspFlashStatusPayload,
): string | null {
  if (isJourneyPhase(status.phase)) {
    return status.phase;
  }
  const state = flashState(status);
  return state === "idle" || state === "success" ? null : previous;
}

function phaseLabel(t: Translate, phase: string | null | undefined): string {
  const key = `settings.esp_flash.phase.${phase || "idle"}`;
  const text = t(key);
  return text === key ? phase || "idle" : text;
}

export function portLabel(port: EspSerialPortPayload): string {
  return port.description ? `${port.port} — ${port.description}` : port.port;
}

function targetLabel(view: FlashView, t: Translate): string {
  const picked = view.selectedPort !== AUTO_PORT ? view.selectedPort : null;
  return (
    view.status.selected_port || picked || t("settings.esp_flash.auto_detect")
  );
}

function detectedPortsLabel(view: FlashView, t: Translate): string {
  if (view.ports.length === 0) {
    return t("settings.esp_flash.readiness.no_ports");
  }
  if (view.ports.length === 1) {
    return t("settings.esp_flash.readiness.one_port", {
      port: portLabel(view.ports[0]),
    });
  }
  return t("settings.esp_flash.readiness.multiple_ports", {
    count: view.ports.length,
  });
}

function stateVariant(state: string): Variant {
  return STATE_VARIANTS[state] ?? "muted";
}

export function statusBadge(
  view: FlashView,
  t: Translate,
): { text: string; variant: Variant } {
  const state = flashState(view.status);
  const label = t(`settings.esp_flash.state.${state}`);
  return {
    text: view.status.error ? `${label} — ${view.status.error}` : label,
    variant: stateVariant(state),
  };
}

export function canStart(view: FlashView): boolean {
  return flashState(view.status) !== "running" && view.ports.length > 0;
}

export function startLabel(view: FlashView, t: Translate): string {
  return t(
    stopped(flashState(view.status))
      ? "settings.esp_flash.retry"
      : "settings.esp_flash.start",
  );
}

function recoveryItems(
  view: FlashView,
  t: Translate,
  portsDetected: boolean,
): ReadinessItem[] {
  const state = flashState(view.status);
  const phase = isJourneyPhase(view.status.phase)
    ? view.status.phase
    : (view.lastJourneyPhase ?? view.status.phase ?? "idle");
  const guidance =
    state === "cancelled"
      ? "cancelled"
      : isJourneyPhase(phase) && phase !== "done"
        ? phase
        : "generic";
  const keyBase = `settings.esp_flash.recovery.${guidance}`;
  return [
    {
      label: t("settings.esp_flash.recovery.item.failed_step"),
      detail: phaseLabel(t, phase),
      state: "attention",
    },
    {
      label: t("settings.esp_flash.recovery.item.captured_detail"),
      detail:
        view.status.error || t("settings.esp_flash.recovery.fallback_error"),
      state: "attention",
    },
    {
      label: t("settings.esp_flash.recovery.item.next_step"),
      detail: portsDetected
        ? `${t(`${keyBase}.title`)} — ${t(`${keyBase}.detail`)}`
        : t("settings.esp_flash.recovery.item.next_step_blocked"),
      state: portsDetected ? "attention" : "blocked",
    },
  ];
}

/** The start (or, after a failure, recovery) checklist above the buttons. */
export function startReadiness(view: FlashView, t: Translate): Readiness {
  const state = flashState(view.status);
  const portsDetected = view.ports.length > 0;
  if (stopped(state)) {
    return {
      title: t("settings.esp_flash.recovery.title"),
      summary: t(
        portsDetected
          ? "settings.esp_flash.recovery.summary_retry"
          : "settings.esp_flash.recovery.summary_blocked",
      ),
      stateLabel: portsDetected
        ? t(`settings.esp_flash.state.${state}`)
        : t("maintenance.readiness.blocked"),
      stateVariant: "bad",
      items: recoveryItems(view, t, portsDetected),
    };
  }
  const running = state === "running";
  const readiness = portsDetected ? "ready" : "blocked";
  return {
    title: t("settings.esp_flash.start_readiness.title"),
    summary: t(
      `settings.esp_flash.start_readiness.summary_${running ? "running" : readiness}`,
    ),
    stateLabel: t(`maintenance.readiness.${running ? "running" : readiness}`),
    stateVariant: running ? "warn" : portsDetected ? "ok" : "bad",
    items: [
      {
        label: t("settings.esp_flash.start_readiness.item.connection"),
        detail: portsDetected
          ? t("settings.esp_flash.start_readiness.item.connection_ready", {
              ports: detectedPortsLabel(view, t),
            })
          : t("settings.esp_flash.start_readiness.item.connection_blocked"),
        state: readiness,
      },
      {
        label: t("settings.esp_flash.start_readiness.item.target"),
        detail: portsDetected
          ? t("settings.esp_flash.start_readiness.item.target_ready", {
              target: targetLabel(view, t),
            })
          : t("settings.esp_flash.start_readiness.item.target_blocked"),
        state: readiness,
      },
    ],
  };
}

interface Attempt {
  autoDetect: boolean;
  error: string | null;
  exitCode: number | null;
  finishedAt: number | null;
  selectedPort: string | null;
  startedAt: number | null;
  state: string;
}

/** API history, or the finished status itself when the history is empty. */
function attempts(view: FlashView): Attempt[] {
  if (view.attempts.length > 0) {
    return view.attempts.map((attempt) => ({
      autoDetect: attempt.auto_detect,
      error: attempt.error ?? null,
      exitCode: attempt.exit_code ?? null,
      finishedAt: attempt.finished_at ?? null,
      selectedPort: attempt.selected_port ?? null,
      startedAt: attempt.started_at ?? null,
      state: attempt.state || "idle",
    }));
  }
  const { status } = view;
  const state = flashState(status);
  if (state === "idle" || state === "running") {
    return [];
  }
  return [
    {
      autoDetect: status.auto_detect,
      error: status.error ?? null,
      exitCode: status.exit_code ?? null,
      finishedAt: status.finished_at ?? null,
      selectedPort: status.selected_port ?? null,
      startedAt: status.started_at ?? null,
      state,
    },
  ];
}

export function readinessSummary(view: FlashView, t: Translate): string {
  const state = flashState(view.status);
  if (state === "running" || state === "success" || stopped(state)) {
    return t(`settings.esp_flash.readiness.summary.${state}`);
  }
  return t(
    view.ports.length > 0
      ? "settings.esp_flash.readiness.summary.ready_ports"
      : "settings.esp_flash.readiness.summary.ready_no_ports",
  );
}

export function readinessRows(view: FlashView, t: Translate): StatusRow[] {
  const rows: StatusRow[] = [
    {
      label: t("settings.esp_flash.readiness.detected_ports"),
      value: detectedPortsLabel(view, t),
    },
    {
      label: t("settings.esp_flash.readiness.selected_target"),
      value: targetLabel(view, t),
    },
  ];
  if (flashState(view.status) === "running") {
    rows.push({
      label: t("settings.esp_flash.readiness.current_step"),
      value: phaseLabel(t, view.status.phase),
    });
  }
  if (view.status.last_success_at != null) {
    rows.push({
      label: t("settings.esp_flash.readiness.last_success"),
      value: formatEpochTimestamp(view.status.last_success_at),
    });
  }
  const latest = attempts(view)[0];
  if (latest) {
    rows.push({
      label: t("settings.esp_flash.readiness.last_result"),
      value: t("settings.esp_flash.last_result_value", {
        state: t(`settings.esp_flash.state.${latest.state}`),
        when: formatEpochTimestamp(latest.finishedAt ?? latest.startedAt),
      }),
    });
  }
  return rows;
}

function stageState(view: FlashView, index: number): StageState {
  const state = flashState(view.status);
  if (state === "success") {
    return "done";
  }
  const phase = isJourneyPhase(view.status.phase)
    ? view.status.phase
    : stopped(state)
      ? view.lastJourneyPhase
      : null;
  const current = JOURNEY_PHASES.findIndex((p) => p === phase);
  if (state === "idle" || current === -1 || index > current) {
    return "upcoming";
  }
  if (index < current) {
    return "done";
  }
  return stopped(state) ? "attention" : "active";
}

export function journeyStages(view: FlashView, t: Translate): Stage[] {
  return JOURNEY_PHASES.map((phase, index) => {
    const state = stageState(view, index);
    return {
      phase,
      state,
      title: t(`settings.esp_flash.phase.${phase}`),
      detail: t(`settings.esp_flash.journey.detail.${phase}`),
      stateText: t(`maintenance.stage_state.${state}`),
    };
  });
}

export function journeyNote(view: FlashView, t: Translate): string | null {
  const state = flashState(view.status);
  return stopped(state)
    ? t(`settings.esp_flash.journey_terminal.${state}`)
    : null;
}

/** Placeholder for the log panel until the job has produced output. */
export function logPlaceholder(
  view: FlashView,
  logText: string,
  t: Translate,
): { title: string; body: string } | null {
  if (view.status.log_count > 0 || logText.length > 0) {
    return null;
  }
  const state = flashState(view.status);
  const kind =
    state === "running" ? "running" : stopped(state) ? "failed" : "idle";
  return {
    title: t(`settings.esp_flash.logs_${kind}_title`),
    body: t(`settings.esp_flash.logs_${kind}_body`),
  };
}

export function historyItems(view: FlashView, t: Translate): AttemptItem[] {
  return attempts(view)
    .slice(0, 5)
    .map((attempt) => {
      const meta = [
        attempt.finishedAt != null
          ? t("settings.esp_flash.history_finished_at", {
              value: formatEpochTimestamp(attempt.finishedAt),
            })
          : t("settings.esp_flash.history_started_at", {
              value: formatEpochTimestamp(attempt.startedAt),
            }),
        t(
          attempt.autoDetect
            ? "settings.esp_flash.history_auto_detect_used"
            : "settings.esp_flash.history_manual_target_used",
        ),
      ];
      if (attempt.exitCode != null) {
        meta.push(
          t("settings.esp_flash.history_exit_code", { code: attempt.exitCode }),
        );
      }
      return {
        state: attempt.state,
        stateText: t(`settings.esp_flash.state.${attempt.state}`),
        variant: stateVariant(attempt.state),
        port: attempt.selectedPort || t("settings.esp_flash.auto_detect"),
        meta: meta.join(" · "),
        error: attempt.error,
      };
    });
}
