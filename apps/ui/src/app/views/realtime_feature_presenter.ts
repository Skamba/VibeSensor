import { deriveCarSelectionState } from "../car_selection_state";
import { classifyDataFreshness } from "../features/data_freshness";
import { createRealtimeSensorState } from "../features/realtime_sensor_state";
import type { RealtimeFeatureNavigationPorts } from "../features/realtime_feature";
import type {
  RealtimeState,
  SettingsState,
  SpectrumState,
} from "../ui_app_state";
import type { LocationOption } from "../../transport/http_models";
import type { AdaptedClient } from "../../transport/live_models";
import {
  buildRealtimeLoggingPanelViewModel,
  captureReadinessCheck,
  captureReadinessSummaryText,
  type RealtimeLoggingPanelViewModel,
  type RealtimeLoggingPendingAction,
} from "./realtime_logging_view_models";
import type {
  RealtimeLoggingPanelBridge,
  RealtimeLoggingPanelRenderModel,
} from "./realtime_logging_panel";
import { buildRealtimeSensorTableRenderModel } from "./realtime_sensor_table_view";
import type {
  RealtimeLiveOverviewBridge,
  RealtimeLiveOverviewRenderModel,
} from "./realtime_live_overview";
import type { SensorsPanelView } from "./sensors_panel";

export type RealtimeFeaturePendingLoggingAction = RealtimeLoggingPendingAction;

export interface RealtimeFeatureRenderState {
  handlersBound: boolean;
  pendingLoggingAction: RealtimeFeaturePendingLoggingAction;
}

export interface RealtimeFeaturePresenterDeps {
  sensorsPanel: SensorsPanelView;
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  getLanguage: () => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
  formatInt: (value: number) => string;
  chrome: {
    setShellLiveStatus: (variant: string, text: string) => void;
    liveOverview: RealtimeLiveOverviewBridge;
    loggingPanel: RealtimeLoggingPanelBridge;
  };
  navigation: RealtimeFeatureNavigationPorts;
}

export interface RealtimeFeaturePresenter {
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  locationCodeForClient(client: AdaptedClient): string;
  maybeRenderSensorsSettingsList(force?: boolean): void;
  renderStatus(clientRow?: AdaptedClient): void;
  renderLoggingStatus(state: RealtimeFeatureRenderState): void;
  renderLoggingUnavailable(): void;
  renderLoggingError(message: string): void;
  getIdleCaptureReadinessSignature(): string;
  openHistory(): void;
  openCars(options?: { openWizard?: boolean }): void;
  openSensorsSettings(): void;
  openSpeedSourceSettings(): void;
}

export function createRealtimeFeaturePresenter(
  ctx: RealtimeFeaturePresenterDeps,
): RealtimeFeaturePresenter {
  const {
    sensorsPanel,
    realtime,
    settings,
    spectrum,
    t,
    formatInt,
    chrome,
    navigation,
  } = ctx;

  let loggingElapsedTimer: ReturnType<typeof setInterval> | null = null;
  let lastCompletedElapsedText = "--";
  let renderedLoggingPanelModel: RealtimeLoggingPanelRenderModel | null = null;

  const sensorState = createRealtimeSensorState({
    realtime,
    settings,
    spectrum,
    getLanguage: ctx.getLanguage,
    t,
    formatInt,
  });
  const {
    activeCarDisplayState,
    assignedClientCount,
    buildLocationOptions,
    computeLiveHealth,
    connectedClients,
    locationCodeForClient,
    strongestSignal,
    strongestSignalText,
  } = sensorState;
  let renderedSensorsSettingsSignature = "";

  function dataFreshnessText(): string {
    const connected = connectedClients();
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
      referenceCheck &&
      referenceCheck.state !== "pass" &&
      [
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

  function computeCurrentLiveHealth() {
    return computeLiveHealth((readiness) =>
      captureReadinessSummaryText(readiness, {
        t,
        formatInt,
      }),
    );
  }

  function liveSensorOverviewLabel(client: AdaptedClient): string {
    const code = locationCodeForClient(client);
    if (!code) {
      return String(
        client.name || client.id || t("dashboard.sensor_unassigned"),
      ).trim();
    }
    const option = realtime.locationOptions.find(
      (location) => location.code === code,
    );
    return option?.label ?? code;
  }

  function buildLiveOverviewModel(
    phaseText: string,
  ): RealtimeLiveOverviewRenderModel {
    const signal = strongestSignal();
    const health = computeCurrentLiveHealth();
    const totalClients = realtime.clients.length;
    const activeCar = activeCarDisplayState();
    const setupBlockReason = selectionBlockReason();
    return {
      connectedSensorsText: `${formatInt(connectedClients().length)} / ${formatInt(totalClients)}`,
      activeCar: {
        text: activeCar.text,
        warning: setupBlockReason === null && activeCar.isWarning,
      },
      recordingStateText: phaseText,
      dataFreshnessText: dataFreshnessText(),
      strongestSignalText: strongestSignalText(signal),
      runHealth: {
        hidden: !health.showOverviewPill,
        text: health.text,
        variant: health.variant,
      },
      sensorCards: realtime.clients.map((client) => ({
        id: client.id,
        label: liveSensorOverviewLabel(client),
        connected: Boolean(client.connected),
        statusText: client.connected ? t("status.online") : t("status.offline"),
        strongest: signal?.client.id === client.id,
      })),
    };
  }

  function selectionBlockReason(): "no_cars" | "no_active" | null {
    const selection = deriveCarSelectionState(settings);
    if (selection.kind === "active") {
      return null;
    }
    return selection.kind === "no_cars" ? "no_cars" : "no_active";
  }

  function buildLoggingPanelViewModel(
    pendingLoggingAction: RealtimeFeaturePendingLoggingAction,
  ) {
    return buildRealtimeLoggingPanelViewModel({
      status: realtime.loggingStatus,
      pendingLoggingAction,
      selectionBlockReason: selectionBlockReason(),
      liveHealth: computeCurrentLiveHealth(),
      connectedCountText: formatInt(connectedClients().length),
      assignedCountText: formatInt(assignedClientCount()),
      runIdText: recordingRunIdText(realtime.loggingStatus),
      elapsedText: realtime.loggingStatus.enabled
        ? formatElapsed(realtime.loggingStatus.start_time_utc)
        : "--",
      samplesText: formatInt(realtime.loggingStatus.samples_written ?? 0),
      lastCompletedElapsedText,
      t,
      formatInt,
    });
  }

  function buildLoggingRenderModel(
    panelState: RealtimeLoggingPanelViewModel,
  ): RealtimeLoggingPanelRenderModel {
    return {
      pillVariant: panelState.pillVariant,
      pillText: panelState.pillText,
      showPill: panelState.showPill,
      summaryText: panelState.summaryText,
      summaryPanel: panelState.summaryPanel,
      runIdText: panelState.runIdText,
      phaseText: panelState.phaseText,
      elapsedText: panelState.elapsedText,
      samplesText: panelState.samplesText,
      checklist: panelState.checklist,
      showStart: panelState.showStart,
      showStop: panelState.showStop,
      startDisabled: panelState.startDisabled,
      stopDisabled: panelState.stopDisabled,
      setupMode: panelState.setupMode,
    };
  }

  function renderLoggingPanel(model: RealtimeLoggingPanelRenderModel): void {
    renderedLoggingPanelModel = model;
    chrome.loggingPanel.render(model);
  }

  function renderLiveOverview(phaseText: string): void {
    const model = buildLiveOverviewModel(phaseText);
    chrome.liveOverview.render(model);
    chrome.setShellLiveStatus(model.runHealth.variant, model.runHealth.text);
  }

  function sensorsSettingsSignature(): string {
    const clientPart = realtime.clients
      .map((client) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}|${client.location_code || ""}`;
      })
      .join("||");
    const locationPart = realtime.locationOptions
      .map((loc) => `${loc.code}|${loc.label}`)
      .join("||");
    return `${clientPart}##${locationPart}`;
  }

  function maybeRenderSensorsSettingsList(force = false): void {
    const nextSig = sensorsSettingsSignature();
    if (!force && nextSig === renderedSensorsSettingsSignature) return;
    renderedSensorsSettingsSignature = nextSig;
    renderSensorsSettingsList();
  }

  function renderSensorsSettingsList(): void {
    sensorsPanel.setModel({
      table: buildRealtimeSensorTableRenderModel({
        clients: realtime.clients,
        locationOptions: realtime.locationOptions,
        t,
      }),
    });
  }

  function renderStatus(clientRow?: AdaptedClient): void {
    void clientRow;
    renderLiveOverview(buildLoggingPanelViewModel(null).phaseText);
  }

  function clearLoggingElapsedTimer(): void {
    if (loggingElapsedTimer === null) return;
    clearInterval(loggingElapsedTimer);
    loggingElapsedTimer = null;
  }

  function formatElapsed(startTimeUtc: string | null | undefined): string {
    if (!startTimeUtc) return "--";
    const startMs = Date.parse(startTimeUtc);
    if (!Number.isFinite(startMs)) return "--";
    const elapsedSeconds = Math.max(
      0,
      Math.floor((Date.now() - startMs) / 1000),
    );
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function syncLoggingElapsedTimer(handlersBound: boolean): void {
    const shouldTick =
      handlersBound &&
      Boolean(
        realtime.loggingStatus.enabled && realtime.loggingStatus.start_time_utc,
      );
    if (!shouldTick) {
      clearLoggingElapsedTimer();
      return;
    }
    if (loggingElapsedTimer !== null) return;
    loggingElapsedTimer = setInterval(() => {
      if (renderedLoggingPanelModel === null) {
        return;
      }
      renderLoggingPanel({
        ...renderedLoggingPanelModel,
        elapsedText: formatElapsed(realtime.loggingStatus.start_time_utc),
      });
    }, 1_000);
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

  function activatePrimaryView(viewId: string): void {
    navigation.activatePrimaryView(viewId);
  }

  function activateSettingsTab(tabId: string): void {
    navigation.activateSettingsTab(tabId);
  }

  function openSettingsView(tabId: string): void {
    activatePrimaryView("settingsView");
    activateSettingsTab(tabId);
  }

  function openCars(options: { openWizard?: boolean } = {}): void {
    openSettingsView("carTab");
    if (options.openWizard) {
      navigation.openCarWizard();
    }
  }

  function getIdleCaptureReadinessSignature(): string {
    const clientsSignature = realtime.clients
      .map((client) =>
        [
          client.id,
          client.connected ? "1" : "0",
          locationCodeForClient(client),
        ].join(":"),
      )
      .sort()
      .join("|");
    return `${settings.activeCarId ?? ""}##${clientsSignature}`;
  }

  function renderLoggingStatus(state: RealtimeFeatureRenderState): void {
    const panelState = buildLoggingPanelViewModel(state.pendingLoggingAction);
    lastCompletedElapsedText = panelState.nextLastCompletedElapsedText;
    renderLiveOverview(panelState.phaseText);
    renderLoggingPanel(buildLoggingRenderModel(panelState));
    syncLoggingElapsedTimer(state.handlersBound);
    renderLiveOverview(panelState.phaseText);
  }

  function renderLoggingUnavailable(): void {
    clearLoggingElapsedTimer();
    renderLoggingPanel({
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
    });
  }

  function renderLoggingError(message: string): void {
    const errorText = message || t("status.unavailable");
    const baseModel = renderedLoggingPanelModel ?? {
      pillVariant: "bad" as const,
      pillText: errorText,
      showPill: true,
      summaryText: errorText,
      summaryPanel: null,
      runIdText: "",
      phaseText: "--",
      elapsedText: "--",
      samplesText: "--",
      checklist: null,
      showStart: true,
      showStop: false,
      startDisabled: true,
      stopDisabled: true,
      setupMode: false,
    };
    renderLoggingPanel({
      ...baseModel,
      pillVariant: "bad",
      pillText: errorText,
      showPill: true,
      summaryText: errorText,
      summaryPanel: null,
    });
  }

  function openHistory(): void {
    activatePrimaryView("historyView");
  }

  function openSensorsSettings(): void {
    openSettingsView("sensorsTab");
  }

  function openSpeedSourceSettings(): void {
    openSettingsView("speedSourceTab");
  }

  return {
    buildLocationOptions,
    locationCodeForClient,
    maybeRenderSensorsSettingsList,
    renderStatus,
    renderLoggingStatus,
    renderLoggingUnavailable,
    renderLoggingError,
    getIdleCaptureReadinessSignature,
    openHistory,
    openCars,
    openSensorsSettings,
    openSpeedSourceSettings,
  };
}
