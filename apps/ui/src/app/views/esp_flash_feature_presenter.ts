import { formatEpochTimestamp } from "../../format";
import type {
  EspFlashHistoryAttemptModel,
  EspFlashHistoryPanelModel,
  EspFlashLogPanelModel,
  EspFlashPanelRenderModel,
} from "./esp_flash_panel";
import { buildJourneyPanelModel } from "./esp_flash_journey_presenter";
import {
  buildActionSummary,
  buildReadinessPanelModel,
  buildStatusBannerModel,
  currentAttemptSummaries,
  safeEspFlashState,
  statusVariantForEspFlashState,
  type EspFlashFeatureRenderState,
} from "./esp_flash_readiness_presenter";
import { computed, type ReadonlySignal } from "../ui_signals";

export type { EspFlashFeatureRenderState } from "./esp_flash_readiness_presenter";

export interface EspFlashFeaturePresenterDeps {
  renderState: ReadonlySignal<EspFlashFeatureRenderState>;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface EspFlashFeaturePresenter {
  readonly model: ReadonlySignal<EspFlashPanelRenderModel>;
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
  const items: EspFlashHistoryAttemptModel[] = attempts
    .slice(0, 5)
    .map((attempt) => {
      const safeState = safeEspFlashState(attempt.state);
      const portText =
        attempt.selectedPort || t("settings.esp_flash.auto_detect");
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
          variant: statusVariantForEspFlashState(safeState),
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
  const model = computed(() =>
    buildEspFlashPanelRenderModel(ctx.renderState.value, { t: ctx.t }),
  );
  return {
    model,
  };
}
