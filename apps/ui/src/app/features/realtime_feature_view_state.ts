import { classifyDataFreshness } from "./data_freshness";
import { createRealtimeSensorState } from "./realtime_sensor_state";
import type {
  RealtimeFeatureWorkflowLoggingError,
  RealtimeFeatureWorkflowSignals,
} from "./realtime_feature_workflow";
import type {
  RealtimeState,
  SettingsState,
  ShellState,
  SpectrumState,
} from "../ui_app_state";
import { trackAppStateSlice } from "../ui_app_state";
import { computed, effect, signal, type ReadonlySignal } from "../ui_signals";
import type { AdaptedClient } from "../../transport/live_models";
import {
  buildRealtimeLoggingPanelViewModel,
  captureReadinessCheck,
  captureReadinessSummaryText,
} from "../views/realtime_logging_view_models";
import type { RealtimeLiveOverviewRenderModel } from "../views/realtime_live_overview";
import type { RealtimeLoggingPanelRenderModel } from "../views/realtime_logging_panel";
import { buildRealtimeSensorTableRenderModel } from "../views/realtime_sensor_table_view";
import type { SensorsPanelRenderModel } from "../views/sensors_panel";

interface RealtimeFeatureViewStateDeps {
  state: {
    realtime: RealtimeState;
    settings: SettingsState;
    shell: Pick<ShellState, "lang">;
    spectrum: SpectrumState;
  };
  services: {
    t: (key: string, vars?: Record<string, unknown>) => string;
  };
  formatting: {
    formatInt: (value: number) => string;
  };
  workflow: RealtimeFeatureWorkflowSignals;
}

export interface RealtimeFeatureViewState {
  readonly idleCaptureReadinessSignature: ReadonlySignal<string>;
  readonly liveOverviewModel: ReadonlySignal<RealtimeLiveOverviewRenderModel>;
  readonly loggingPanelModel: ReadonlySignal<RealtimeLoggingPanelRenderModel>;
  readonly sensorsPanelModel: ReadonlySignal<SensorsPanelRenderModel>;
}

interface LoggingElapsedTickInputs {
  handlersBound: boolean;
  loggingEnabled: boolean;
  loggingStartTimeUtc: string | null;
}

function formatElapsed(
  startTimeUtc: string | null | undefined,
  nowMs: number,
): string {
  if (!startTimeUtc) return "--";
  const startMs = Date.parse(startTimeUtc);
  if (!Number.isFinite(startMs)) return "--";
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - startMs) / 1000));
  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function buildLoggingRenderModel(model: ReturnType<typeof buildRealtimeLoggingPanelViewModel>) {
  return {
    pillVariant: model.pillVariant,
    pillText: model.pillText,
    showPill: model.showPill,
    summaryText: model.summaryText,
    summaryPanel: model.summaryPanel,
    runIdText: model.runIdText,
    phaseText: model.phaseText,
    elapsedText: model.elapsedText,
    samplesText: model.samplesText,
    checklist: model.checklist,
    showStart: model.showStart,
    showStop: model.showStop,
    startDisabled: model.startDisabled,
    stopDisabled: model.stopDisabled,
    setupMode: model.setupMode,
  } satisfies RealtimeLoggingPanelRenderModel;
}

function buildLoggingUnavailableModel(
  t: (key: string, vars?: Record<string, unknown>) => string,
): RealtimeLoggingPanelRenderModel {
  return {
    pillVariant: "bad",
    pillText: t("status.unavailable"),
    showPill: true,
    summaryText: t("status.unavailable"),
    summaryPanel: null,
    runIdText: "",
    phaseText: t("status.unavailable"),
    elapsedText: "--",
    samplesText: "--",
    checklist: null,
    showStart: true,
    showStop: false,
    startDisabled: true,
    stopDisabled: true,
    setupMode: false,
  };
}

function buildLoggingErrorModel(
  error: RealtimeFeatureWorkflowLoggingError,
  baseModel: RealtimeLoggingPanelRenderModel,
  t: (key: string, vars?: Record<string, unknown>) => string,
): RealtimeLoggingPanelRenderModel {
  if (error.kind === "unavailable") {
    return buildLoggingUnavailableModel(t);
  }
  const errorText = error.message || t("status.unavailable");
  return {
    ...baseModel,
    pillVariant: "bad",
    pillText: errorText,
    showPill: true,
    summaryText: errorText,
    summaryPanel: null,
  };
}

export function createRealtimeFeatureViewState(
  deps: RealtimeFeatureViewStateDeps,
): RealtimeFeatureViewState {
  const {
    state: { realtime, settings, shell, spectrum },
    services: { t },
    formatting: { formatInt },
    workflow,
  } = deps;
  const sensorState = createRealtimeSensorState({
    realtime,
    settings,
    shell,
    spectrum,
    captureReadinessSummaryText: (readiness) =>
      captureReadinessSummaryText(readiness, {
        t,
        formatInt,
      }),
    t,
    formatInt,
  });
  const elapsedNowMs = signal(Date.now());
  const lastCompletedElapsedText = signal("--");
  const loggingElapsedTickInputs = signal<LoggingElapsedTickInputs>({
    handlersBound: workflow.handlersBound.value,
    loggingEnabled: realtime.loggingStatus.enabled,
    loggingStartTimeUtc: realtime.loggingStatus.start_time_utc ?? null,
  });
  let loggingElapsedTimer: ReturnType<typeof setInterval> | null = null;

  function clearLoggingElapsedTimer(): void {
    if (loggingElapsedTimer === null) {
      return;
    }
    clearInterval(loggingElapsedTimer);
    loggingElapsedTimer = null;
  }

  effect(() => {
    const handlersBound = workflow.handlersBound.value;
    trackAppStateSlice(realtime);
    const nextTickInputs = {
      handlersBound,
      loggingEnabled: realtime.loggingStatus.enabled,
      loggingStartTimeUtc: realtime.loggingStatus.start_time_utc ?? null,
    } satisfies LoggingElapsedTickInputs;
    const currentTickInputs = loggingElapsedTickInputs.value;
    if (
      currentTickInputs.handlersBound === nextTickInputs.handlersBound
      && currentTickInputs.loggingEnabled === nextTickInputs.loggingEnabled
      && currentTickInputs.loggingStartTimeUtc === nextTickInputs.loggingStartTimeUtc
    ) {
      return;
    }
    loggingElapsedTickInputs.value = nextTickInputs;
  });

  effect(() => {
    const {
      handlersBound,
      loggingEnabled,
      loggingStartTimeUtc,
    } = loggingElapsedTickInputs.value;
    const shouldTick =
      handlersBound && Boolean(loggingEnabled && loggingStartTimeUtc);
    if (!shouldTick) {
      clearLoggingElapsedTimer();
      return;
    }
    elapsedNowMs.value = Date.now();
    clearLoggingElapsedTimer();
    loggingElapsedTimer = setInterval(() => {
      elapsedNowMs.value = Date.now();
    }, 1_000);
    return () => {
      clearLoggingElapsedTimer();
    };
  });

  effect(() => {
    trackAppStateSlice(realtime);
    if (realtime.loggingStatus.enabled) {
      lastCompletedElapsedText.value = formatElapsed(
        realtime.loggingStatus.start_time_utc,
        elapsedNowMs.value,
      );
      return;
    }
    if (
      !realtime.loggingStatus.analysis_in_progress
      && !realtime.loggingStatus.last_completed_run_id
    ) {
      lastCompletedElapsedText.value = "--";
    }
  });

  function selectionBlockReason(): "no_cars" | "no_active" | null {
    const selection = sensorState.activeCarSelection.value;
    if (selection.kind === "active") {
      return null;
    }
    return selection.kind === "no_cars" ? "no_cars" : "no_active";
  }

  function recordingRunIdText(status = realtime.loggingStatus): string {
    if (status.enabled && status.run_id) {
      return t("dashboard.logging.run_id", { runId: status.run_id });
    }
    if (status.last_completed_run_id) {
      return t("dashboard.logging.last_run_id", {
        runId: status.last_completed_run_id,
      });
    }
    return "";
  }

  function dataFreshnessText(): string {
    const connected = sensorState.connectedClients.value;
    const ages = connected
      .map((client) => client.last_seen_age_ms)
      .filter(
        (age): age is number => typeof age === "number" && Number.isFinite(age),
      );
    if (!ages.length) {
      return t("dashboard.data_freshness_none");
    }
    const captureReadiness = realtime.loggingStatus.capture_readiness ?? null;
    const referenceCheck = captureReadinessCheck(
      captureReadiness,
      "reference_ready",
    );
    const referenceReason = referenceCheck?.reason_key ?? "";
    if (
      referenceCheck
      && referenceCheck.state !== "pass"
      && [
        "speed_source_missing",
        "speed_source_not_live",
        "speed_source_fallback_active",
        "speed_sample_missing",
        "speed_sample_stale",
      ].includes(referenceReason)
    ) {
      return t("dashboard.data_freshness_sensors_only");
    }
    const ageMs = Math.max(...ages.map((age) => Math.max(0, age)));
    const ageText = t("status.age_ms_ago", { value: formatInt(ageMs) });
    const freshness = classifyDataFreshness(ageMs, connected);
    if (freshness === "fresh") {
      return t("dashboard.data_freshness_fresh", { age: ageText });
    }
    if (freshness === "delayed") {
      return t("dashboard.data_freshness_delayed", { age: ageText });
    }
    return t("dashboard.data_freshness_stale", { age: ageText });
  }

  function liveSensorOverviewLabel(client: AdaptedClient): string {
    const code = sensorState.locationCodeForClient(client);
    if (!code) {
      return String(
        client.name || client.id || t("dashboard.sensor_unassigned"),
      ).trim();
    }
    const option = sensorState.locationOptions.value.find(
      (location) => location.code === code,
    );
    return option?.label ?? code;
  }

  const loggingPanelBaseModel = computed(() => {
    trackAppStateSlice(realtime);
    trackAppStateSlice(shell);
    const elapsedText = realtime.loggingStatus.enabled
      ? formatElapsed(realtime.loggingStatus.start_time_utc, elapsedNowMs.value)
      : lastCompletedElapsedText.value;
    return buildRealtimeLoggingPanelViewModel({
      status: realtime.loggingStatus,
      pendingLoggingAction: workflow.pendingLoggingAction.value,
      selectionBlockReason: selectionBlockReason(),
      liveHealth: sensorState.liveHealth.value,
      connectedCountText: formatInt(sensorState.connectedClients.value.length),
      assignedCountText: formatInt(sensorState.assignedClientCount.value),
      runIdText: recordingRunIdText(realtime.loggingStatus),
      elapsedText,
      samplesText: formatInt(realtime.loggingStatus.samples_written ?? 0),
      lastCompletedElapsedText: lastCompletedElapsedText.value,
      t,
      formatInt,
    });
  });

  const liveOverviewModel = computed<RealtimeLiveOverviewRenderModel>(() => {
    trackAppStateSlice(realtime);
    trackAppStateSlice(shell);
    const signal = sensorState.strongestSignal.value;
    const activeCar = sensorState.activeCarDisplayState.value;
    const setupBlock = selectionBlockReason();
    return {
      connectedSensorsText: `${formatInt(sensorState.connectedClients.value.length)} / ${formatInt(realtime.clients.length)}`,
      activeCar: {
        text: activeCar.text,
        warning: setupBlock === null && activeCar.isWarning,
      },
      recordingStateText: loggingPanelBaseModel.value.phaseText,
      dataFreshnessText: dataFreshnessText(),
      strongestSignalText: sensorState.strongestSignalText.value,
      runHealth: {
        hidden: !sensorState.liveHealth.value.showOverviewPill,
        text: sensorState.liveHealth.value.text,
        variant: sensorState.liveHealth.value.variant,
      },
      sensorCards: realtime.clients.map((client) => ({
        id: client.id,
        label: liveSensorOverviewLabel(client),
        connected: Boolean(client.connected),
        statusText: client.connected ? t("status.online") : t("status.offline"),
        strongest: signal?.client.id === client.id,
      })),
    };
  });

  const loggingPanelModel = computed<RealtimeLoggingPanelRenderModel>(() => {
    trackAppStateSlice(shell);
    const baseModel = buildLoggingRenderModel(loggingPanelBaseModel.value);
    const loggingError = workflow.loggingError.value;
    if (loggingError === null) {
      return baseModel;
    }
    return buildLoggingErrorModel(loggingError, baseModel, t);
  });

  const sensorsPanelModel = computed<SensorsPanelRenderModel>(() => {
    trackAppStateSlice(realtime);
    trackAppStateSlice(shell);
    return {
      table: buildRealtimeSensorTableRenderModel({
        clients: realtime.clients,
        locationOptions: sensorState.locationOptions.value,
        t,
      }),
    };
  });

  const idleCaptureReadinessSignature = computed(() => {
    trackAppStateSlice(realtime);
    trackAppStateSlice(settings);
    trackAppStateSlice(shell);
    const clientsSignature = realtime.clients
      .map((client) =>
        [
          client.id,
          client.connected ? "1" : "0",
          sensorState.locationCodeForClient(client),
        ].join(":"),
      )
      .sort()
      .join("|");
    return `${settings.activeCarId ?? ""}##${clientsSignature}`;
  });

  return {
    idleCaptureReadinessSignature,
    liveOverviewModel,
    loggingPanelModel,
    sensorsPanelModel,
  };
}
