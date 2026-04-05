import type { UiCarsDom } from "../dom/cars_dom";
import type { UiRealtimeDom } from "../dom/realtime_dom";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { UiShellDom } from "../dom/shell_dom";
import { deriveCarSelectionState } from "../car_selection_state";
import { classifyDataFreshness } from "../features/data_freshness";
import { createRealtimeSensorState } from "../features/realtime_sensor_state";
import type { RealtimeState, SettingsState, SpectrumState } from "../ui_app_state";
import type { LocationOption } from "../../transport/http_models";
import type { AdaptedClient } from "../../transport/live_models";
import {
  buildRealtimeLoggingPanelViewModel,
  captureReadinessCheck,
  captureReadinessSummaryText,
  type RealtimeLoggingPendingAction,
} from "./realtime_logging_view_models";
import {
  renderRealtimeCaptureReadinessChecklist,
  renderRealtimeLoggingSummary,
} from "./realtime_logging_view";
import {
  renderRealtimeSensorOverview,
  renderRealtimeSensorTable,
} from "./realtime_sensor_table_view";

export type RealtimeFeaturePendingLoggingAction = RealtimeLoggingPendingAction;

export interface RealtimeFeatureRenderState {
  handlersBound: boolean;
  pendingLoggingAction: RealtimeFeaturePendingLoggingAction;
}

export interface RealtimeFeaturePresenterDeps {
  dom: UiRealtimeDom;
  shellDom: Pick<UiShellDom, "menuButtons">;
  settingsDom: Pick<UiSettingsDom, "settingsTabs">;
  carsDom: Pick<UiCarsDom, "addCarBtn">;
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  getLanguage: () => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  formatInt: (value: number) => string;
  chrome: {
    setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
    setStatValue: (container: HTMLElement | null, value: string | number) => void;
  };
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
    dom: els,
    shellDom,
    settingsDom,
    carsDom,
    realtime,
    settings,
    spectrum,
    t,
    escapeHtml,
    formatInt,
    chrome,
  } = ctx;
  const { setPillState, setStatValue } = chrome;

  let loggingElapsedTimer: ReturnType<typeof setInterval> | null = null;
  let lastCompletedElapsedText = "--";
  let renderedLoggingSummarySignature: string | null = null;

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

  function renderActiveCarStat(): void {
    const container = els.liveActiveCar;
    const valueEl = container?.querySelector<HTMLElement>("[data-value]");
    if (!container || !valueEl) {
      return;
    }
    const state = activeCarDisplayState();
    container.classList.toggle("stat--warn", state.isWarning);
    valueEl.classList.toggle("stat__value--warn", state.isWarning);
    valueEl.classList.toggle("stat__value--with-icon", state.isWarning);
    valueEl.replaceChildren();
    if (state.isWarning) {
      const iconEl = document.createElement("span");
      iconEl.className = "stat__value-icon stat__value-icon--warn";
      iconEl.setAttribute("aria-hidden", "true");
      iconEl.textContent = "!";
      const textEl = document.createElement("span");
      textEl.textContent = state.text;
      valueEl.append(iconEl, textEl);
      return;
    }
    valueEl.textContent = state.text;
  }

  function dataFreshnessText(): string {
    const connected = connectedClients();
    const ages = connected
      .map((client) => client.last_seen_age_ms)
      .filter((age): age is number => typeof age === "number" && Number.isFinite(age));
    if (!ages.length) {
      return t("dashboard.data_freshness_none");
    }
    const captureReadiness = realtime.loggingStatus.capture_readiness ?? null;
    const referenceCheck = captureReadinessCheck(captureReadiness, "reference_ready");
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

  function setDashboardPillState(
    el: HTMLElement | null,
    variant: "muted" | "ok" | "warn" | "bad",
    text: string,
    { hidden = false }: { hidden?: boolean } = {},
  ): void {
    setPillState(el, variant, text);
    if (el) {
      el.hidden = hidden;
    }
  }

  function computeCurrentLiveHealth() {
    return computeLiveHealth((readiness) => captureReadinessSummaryText(readiness, {
      t,
      formatInt,
    }));
  }

  function renderLiveSensorRoster(): void {
    if (!els.liveSensorRoster) return;
    const signal = strongestSignal();
    renderRealtimeSensorOverview(els.liveSensorRoster, {
      clients: realtime.clients,
      locationOptions: realtime.locationOptions,
      locationCodeForClient,
      strongestClientId: signal?.client.id ?? null,
      t,
      escapeHtml,
    });
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
      elapsedText: realtime.loggingStatus.enabled ? formatElapsed(realtime.loggingStatus.start_time_utc) : "--",
      samplesText: formatInt(realtime.loggingStatus.samples_written ?? 0),
      lastCompletedElapsedText,
      t,
      formatInt,
    });
  }

  function renderLiveOverviewStats(phaseText: string): void {
    const signal = strongestSignal();
    const totalClients = realtime.clients.length;
    setStatValue(els.liveConnectedSensors, `${formatInt(connectedClients().length)} / ${formatInt(totalClients)}`);
    renderActiveCarStat();
    setStatValue(els.liveRecordingState, phaseText);
    setStatValue(els.liveDataFreshness, dataFreshnessText());
    setStatValue(els.liveStrongestSignal, strongestSignalText(signal));
    els.liveStrongestSignal?.classList.remove("stat--spotlight");
  }

  function renderLiveHealth(): void {
    const health = computeCurrentLiveHealth();
    setDashboardPillState(els.liveRunHealth, health.variant, health.text, { hidden: !health.showOverviewPill });
    setPillState(els.shellLiveStatus, health.variant, health.text);
  }

  function sensorsSettingsSignature(): string {
    const clientPart = realtime.clients
      .map((client) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}|${client.location_code || ""}`;
      })
      .join("||");
    const locationPart = realtime.locationOptions.map((loc) => `${loc.code}|${loc.label}`).join("||");
    return `${clientPart}##${locationPart}`;
  }

  function maybeRenderSensorsSettingsList(force = false): void {
    const nextSig = sensorsSettingsSignature();
    if (!force && nextSig === realtime.sensorsSettingsSignature) return;
    realtime.sensorsSettingsSignature = nextSig;
    renderSensorsSettingsList();
    renderLiveSensorRoster();
  }

  function renderSensorsSettingsList(): void {
    if (!els.sensorsSettingsBody) return;
    renderRealtimeSensorTable(els.sensorsSettingsBody, {
      clients: realtime.clients,
      locationOptions: realtime.locationOptions,
      locationCodeForClient,
      t,
      escapeHtml,
    });
  }

  function renderStatus(clientRow?: AdaptedClient): void {
    void clientRow;
    renderLiveOverviewStats(buildLoggingPanelViewModel(null).phaseText);
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
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function syncLoggingElapsedTimer(handlersBound: boolean): void {
    const shouldTick = handlersBound && Boolean(realtime.loggingStatus.enabled && realtime.loggingStatus.start_time_utc);
    if (!shouldTick) {
      clearLoggingElapsedTimer();
      return;
    }
    if (loggingElapsedTimer !== null) return;
    loggingElapsedTimer = setInterval(() => {
      setStatValue(els.loggingElapsed, formatElapsed(realtime.loggingStatus.start_time_utc));
    }, 1_000);
  }

  function recordingRunIdText(status = realtime.loggingStatus): string {
    if (status.enabled && status.run_id) {
      return t("dashboard.logging.run_id", { runId: status.run_id });
    }
    if (status.last_completed_run_id) {
      return t("dashboard.logging.last_run_id", { runId: status.last_completed_run_id });
    }
    return "";
  }

  function activatePrimaryView(viewId: string): void {
    shellDom.menuButtons.find((button) => button.dataset.view === viewId)?.click();
  }

  function activateSettingsTab(tabId: string): void {
    settingsDom.settingsTabs.find((button) => button.getAttribute("data-settings-tab") === tabId)?.click();
  }

  function openSettingsView(tabId: string): void {
    activatePrimaryView("settingsView");
    activateSettingsTab(tabId);
  }

  function openCars(options: { openWizard?: boolean } = {}): void {
    openSettingsView("carTab");
    if (options.openWizard) {
      carsDom.addCarBtn.click();
    }
  }

  function getIdleCaptureReadinessSignature(): string {
    const clientsSignature = realtime.clients
      .map((client) => [
        client.id,
        client.connected ? "1" : "0",
        locationCodeForClient(client),
      ].join(":"))
      .sort()
      .join("|");
    return `${settings.activeCarId ?? ""}##${clientsSignature}`;
  }

  function renderLoggingStatus(state: RealtimeFeatureRenderState): void {
    const panelState = buildLoggingPanelViewModel(state.pendingLoggingAction);
    lastCompletedElapsedText = panelState.nextLastCompletedElapsedText;
    const dashboardGrid = els.loggingSummary?.closest<HTMLElement>(".dashboard-grid");
    dashboardGrid?.classList.toggle("dashboard-grid--setup", panelState.setupMode);
    renderLiveOverviewStats(panelState.phaseText);
    setDashboardPillState(els.loggingStatus, panelState.pillVariant, panelState.pillText, {
      hidden: !panelState.showPill,
    });
    setStatValue(els.loggingPhase, panelState.phaseText);
    setStatValue(els.loggingElapsed, panelState.elapsedText);
    setStatValue(els.loggingSamples, panelState.samplesText);
    if (els.loggingPhase) {
      els.loggingPhase.hidden = true;
    }
    renderedLoggingSummarySignature = renderRealtimeLoggingSummary(
      els.loggingSummary,
      panelState.summaryText,
      panelState.summaryPanel,
      renderedLoggingSummarySignature,
    );
    renderRealtimeCaptureReadinessChecklist(els.loggingChecklist, panelState.checklist);
    if (els.loggingRunId) {
      els.loggingRunId.hidden = panelState.runIdText === "";
      els.loggingRunId.textContent = panelState.runIdText;
    }
    const loggingRow = els.loggingStatus?.parentElement;
    if (loggingRow) {
      loggingRow.hidden = !panelState.showPill && panelState.runIdText === "";
    }
    if (els.startLoggingBtn) {
      els.startLoggingBtn.hidden = !panelState.showStart;
      els.startLoggingBtn.disabled = panelState.startDisabled;
    }
    if (els.stopLoggingBtn) {
      els.stopLoggingBtn.hidden = !panelState.showStop;
      els.stopLoggingBtn.disabled = panelState.stopDisabled;
    }
    syncLoggingElapsedTimer(state.handlersBound);
    renderLiveHealth();
  }

  function renderLoggingUnavailable(): void {
    clearLoggingElapsedTimer();
    setDashboardPillState(els.loggingStatus, "bad", t("status.unavailable"));
    renderedLoggingSummarySignature = renderRealtimeLoggingSummary(
      els.loggingSummary,
      t("status.unavailable"),
      null,
      renderedLoggingSummarySignature,
    );
    renderRealtimeCaptureReadinessChecklist(els.loggingChecklist, null);
    if (els.loggingRunId) {
      els.loggingRunId.hidden = true;
      els.loggingRunId.textContent = "";
    }
    setStatValue(els.loggingPhase, t("status.unavailable"));
    setStatValue(els.loggingElapsed, "--");
    setStatValue(els.loggingSamples, "--");
    if (els.loggingPhase) {
      els.loggingPhase.hidden = true;
    }
    const loggingRow = els.loggingStatus?.parentElement;
    if (loggingRow) {
      loggingRow.hidden = false;
    }
    if (els.startLoggingBtn) {
      els.startLoggingBtn.hidden = false;
      els.startLoggingBtn.disabled = true;
    }
    if (els.stopLoggingBtn) {
      els.stopLoggingBtn.hidden = true;
      els.stopLoggingBtn.disabled = true;
    }
    const dashboardGrid = els.loggingSummary?.closest<HTMLElement>(".dashboard-grid");
    dashboardGrid?.classList.remove("dashboard-grid--setup");
  }

  function renderLoggingError(message: string): void {
    setDashboardPillState(els.loggingStatus, "bad", message || t("status.unavailable"));
    renderedLoggingSummarySignature = renderRealtimeLoggingSummary(
      els.loggingSummary,
      message || t("status.unavailable"),
      null,
      renderedLoggingSummarySignature,
    );
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
