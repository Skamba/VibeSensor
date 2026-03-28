import type { FeatureDepsBase } from "../feature_deps_base";
import { deriveCarSelectionState } from "../car_selection_state";
import type { RealtimeState, SettingsState, SpectrumState } from "../ui_app_state";
import type { LocationOption } from "../../api/types";
import type { AdaptedClient } from "../../server_payload";
import * as I18N from "../../i18n";
import {
  getClientLocations,
  getLoggingStatus,
  identifyClient as identifyClientApi,
  removeClient as removeClientApi,
  setClientLocation as setClientLocationApi,
  startLoggingRun,
  stopLoggingRun,
} from "../../api";
import { defaultLocationCodes } from "../../constants";
import {
  getRealtimeSensorTableClickAction,
  getRealtimeSensorTableLocationChange,
  renderRealtimeSensorOverview,
  renderRealtimeSensorTable,
} from "../views/realtime_sensor_table_view";
import { createPollingController } from "./polling_controller";
import { classifyDataFreshness } from "./data_freshness";

export interface RealtimeFeatureDeps extends FeatureDepsBase {
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  getLanguage: () => string;
  formatInt: (value: number) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
  sendSelection: () => void;
  onRecordingStatusChanged: () => Promise<void>;
}

export interface RealtimeFeature {
  bindHandlers(): void;
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  maybeRenderSensorsSettingsList(force?: boolean): void;
  updateClientSelection(): void;
  locationCodeForClient(client: AdaptedClient): string;
  renderStatus(clientRow?: AdaptedClient): void;
  renderLoggingStatus(): void;
  refreshLoggingStatus(): Promise<void>;
  startLogging(): Promise<void>;
  stopLogging(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

export function createRealtimeFeature(ctx: RealtimeFeatureDeps): RealtimeFeature {
  const { realtime, settings, spectrum, els, t, escapeHtml, formatInt, setPillState } = ctx;
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  const LOGGING_STATUS_IDLE_POLL_MS = 15_000;
  const LOGGING_STATUS_ACTIVE_POLL_MS = 2_000;
  const LOGGING_STATUS_ERROR_POLL_MS = 5_000;
  let handlersBound = false;
  let pendingLoggingAction: "starting" | "stopping" | null = null;
  let loggingElapsedTimer: ReturnType<typeof setInterval> | null = null;

  const SHORTHAND_LOCATION_MAP: Record<string, string> = {
    "front left": "front_left_wheel",
    "front right": "front_right_wheel",
    "rear left": "rear_left_wheel",
    "rear right": "rear_right_wheel",
    driver: "driver_seat",
  };

  function locationLabelForLang(lang: string, code: string): string {
    return I18N.get(lang, `location.${code}`, { code });
  }

  function locationLabel(code: string): string {
    return locationLabelForLang(ctx.getLanguage(), code);
  }

  function buildLocationOptions(codes: readonly string[]): LocationOption[] {
    return codes.map((code) => ({ code, label: locationLabel(code) }));
  }

  function applyLocationCodes(codes: string[]): void {
    realtime.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
    realtime.locationOptions = buildLocationOptions(realtime.locationCodes);
  }

  function locationCodeForClient(client: AdaptedClient): string {
    const explicitCode = String(client.location_code || "").trim();
    if (explicitCode && realtime.locationCodes.includes(explicitCode)) return explicitCode;
    const name = String(client.name || "").trim();
    if (!name) return "";
    const normalizedName = name.toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    for (const [token, code] of Object.entries(SHORTHAND_LOCATION_MAP)) {
      if (normalizedName.includes(token) && realtime.locationCodes.includes(code)) return code;
    }
    for (const code of realtime.locationCodes) {
      const labels = I18N.getForAllLangs(`location.${code}`);
      if (labels.some((label) => label === name)) return code;
    }
    const match = realtime.locationOptions.find((loc) => loc.label === name);
    return match ? match.code : "";
  }

  function clientDisplayName(client: AdaptedClient): string {
    return String(client.name || "").trim() || client.id;
  }

  function clientLocationText(client: AdaptedClient): string {
    const code = locationCodeForClient(client);
    if (!code) {
      return t("dashboard.sensor_unassigned");
    }
    const option = realtime.locationOptions.find((location) => location.code === code);
    return option?.label ?? locationLabel(code);
  }

  function connectedClients(): AdaptedClient[] {
    return realtime.clients.filter((client) => Boolean(client.connected));
  }

  function assignedClientCount(): number {
    return realtime.clients.filter((client) => locationCodeForClient(client)).length;
  }

  function strongestSignal(): { client: AdaptedClient; db: number } | null {
    let bestClient: AdaptedClient | null = null;
    let bestDb = Number.NEGATIVE_INFINITY;
    for (const client of connectedClients()) {
      const db = spectrum.spectra.clients[client.id]?.strength_metrics?.vibration_strength_db;
      if (typeof db !== "number" || !Number.isFinite(db)) continue;
      if (db > bestDb) {
        bestDb = db;
        bestClient = client;
      }
    }
    if (!bestClient) {
      return null;
    }
    return {
      client: bestClient,
      db: bestDb,
    };
  }

  function strongestSignalText(signal = strongestSignal()): string {
    if (!signal) {
      return t("dashboard.strongest_signal_none");
    }
    const primary = locationCodeForClient(signal.client)
      ? clientLocationText(signal.client)
      : clientDisplayName(signal.client);
    return `${primary} (${formatInt(signal.db)} dB)`;
  }

  function activeCarText(): string {
    const selection = deriveCarSelectionState(settings);
    if (selection.kind === "loading") {
      return t("dashboard.active_car_loading");
    }
    if (selection.kind !== "active") {
      return t("dashboard.active_car_none");
    }
    return selection.car.name;
  }

  function dataFreshnessText(): string {
    const connected = connectedClients();
    const ages = connected
      .map((client) => client.last_seen_age_ms)
      .filter((age): age is number => typeof age === "number" && Number.isFinite(age));
    if (!ages.length) {
      return t("dashboard.data_freshness_none");
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

  type LiveHealth = {
    variant: "muted" | "ok" | "warn" | "bad";
    text: string;
    summary: string;
  };

  type RecordingPanelState = {
    pillVariant: "muted" | "ok" | "warn" | "bad";
    pillText: string;
    phaseText: string;
    summaryText: string;
    runIdText: string;
    elapsedText: string;
    samplesText: string;
    showStart: boolean;
    showStop: boolean;
    startDisabled: boolean;
    stopDisabled: boolean;
  };

  function computeLiveHealth(): LiveHealth {
    if (realtime.loggingStatus.write_error) {
      return {
        variant: "bad",
        text: t("dashboard.health.write_error"),
        summary: realtime.loggingStatus.write_error,
      };
    }
    const connected = connectedClients();
    if (!connected.length) {
      return {
        variant: "muted",
        text: t("dashboard.health.no_signal"),
        summary: t("dashboard.logging.waiting"),
      };
    }
    const droppedCount = connected.filter((client) => (client.dropped_frames ?? 0) > 0).length;
    if (droppedCount > 0) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.frame_loss", { count: formatInt(droppedCount) }),
      };
    }
    const unassignedConnectedCount = connected.filter((client) => !locationCodeForClient(client)).length;
    if (unassignedConnectedCount > 0) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.unassigned", { count: formatInt(unassignedConnectedCount) }),
      };
    }
    const offlineCount = realtime.clients.filter((client) => !client.connected).length;
    if (offlineCount > 0) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.offline", { count: formatInt(offlineCount) }),
      };
    }
    const connectedCount = formatInt(connected.length);
    const assignedCount = formatInt(assignedClientCount());
    if (realtime.loggingStatus.enabled) {
      return {
        variant: "ok",
        text: t("dashboard.health.recording"),
        summary: t("dashboard.logging.running", { connected: connectedCount, assigned: assignedCount }),
      };
    }
    return {
      variant: "ok",
      text: t("dashboard.health.ready"),
      summary: t("dashboard.logging.ready", { connected: connectedCount, assigned: assignedCount }),
    };
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

  function renderLiveOverviewStats(): void {
    const signal = strongestSignal();
    const totalClients = realtime.clients.length;
    ctx.setStatValue(els.liveConnectedSensors, `${formatInt(connectedClients().length)} / ${formatInt(totalClients)}`);
    ctx.setStatValue(els.liveActiveCar, activeCarText());
    ctx.setStatValue(els.liveRecordingState, computeRecordingPanelState().phaseText);
    ctx.setStatValue(els.liveDataFreshness, dataFreshnessText());
    ctx.setStatValue(els.liveStrongestSignal, strongestSignalText(signal));
    els.liveStrongestSignal?.classList.toggle("stat--spotlight", Boolean(signal));
  }

  function renderLiveHealth(): void {
    const health = computeLiveHealth();
    setPillState(els.liveRunHealth, health.variant, health.text);
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

  function updateClientSelection(): void {
    const firstConnected = realtime.clients.find((c) => Boolean(c.connected));
    if (!realtime.selectedClientId && realtime.clients.length > 0) {
      realtime.selectedClientId = firstConnected ? firstConnected.id : realtime.clients[0].id;
    }
    if (realtime.selectedClientId && !realtime.clients.some((c) => c.id === realtime.selectedClientId)) {
      realtime.selectedClientId = firstConnected
        ? firstConnected.id
        : realtime.clients.length ? realtime.clients[0].id : null;
    }
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
    renderLiveOverviewStats();
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

  function syncLoggingElapsedTimer(): void {
    const shouldTick = handlersBound && Boolean(realtime.loggingStatus.enabled && realtime.loggingStatus.start_time_utc);
    if (!shouldTick) {
      clearLoggingElapsedTimer();
      return;
    }
    if (loggingElapsedTimer !== null) return;
    loggingElapsedTimer = setInterval(() => {
      ctx.setStatValue(els.loggingElapsed, formatElapsed(realtime.loggingStatus.start_time_utc));
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

  function computeRecordingPanelState(): RecordingPanelState {
    const status = realtime.loggingStatus;
    const on = Boolean(status.enabled);
    const hasActiveClients = realtime.clients.some((client) => Boolean(client?.connected));
    const connectedCount = formatInt(connectedClients().length);
    const assignedCount = formatInt(assignedClientCount());
    const liveHealth = computeLiveHealth();
    const runIdText = recordingRunIdText(status);
    const elapsedText = on ? formatElapsed(status.start_time_utc) : "--";
    const samplesText = formatInt(status.samples_written ?? 0);

    if (pendingLoggingAction === "starting") {
      return {
        pillVariant: "muted",
        pillText: t("dashboard.recording_phase.starting"),
        phaseText: t("dashboard.recording_phase.starting"),
        summaryText: t("dashboard.logging.starting"),
        runIdText,
        elapsedText: "--",
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: true,
        stopDisabled: true,
      };
    }

    if (pendingLoggingAction === "stopping") {
      return {
        pillVariant: "warn",
        pillText: t("dashboard.recording_phase.stopping"),
        phaseText: t("dashboard.recording_phase.stopping"),
        summaryText: t("dashboard.logging.stopping"),
        runIdText,
        elapsedText,
        samplesText,
        showStart: false,
        showStop: true,
        startDisabled: true,
        stopDisabled: true,
      };
    }

    if (on) {
      return {
        pillVariant: status.write_error ? "bad" : "ok",
        pillText: status.write_error || t("dashboard.recording_phase.recording"),
        phaseText: status.write_error ? t("dashboard.health.attention") : t("dashboard.recording_phase.recording"),
        summaryText: liveHealth.variant === "ok"
          ? t("dashboard.logging.running", { connected: connectedCount, assigned: assignedCount })
          : liveHealth.summary,
        runIdText,
        elapsedText,
        samplesText,
        showStart: false,
        showStop: true,
        startDisabled: true,
        stopDisabled: false,
      };
    }

    if (status.analysis_in_progress) {
      const runId = status.last_completed_run_id ?? t("status.unavailable");
      return {
        pillVariant: "warn",
        pillText: t("dashboard.recording_phase.processing"),
        phaseText: t("dashboard.recording_phase.processing"),
        summaryText: t("dashboard.logging.processing", { runId }),
        runIdText,
        elapsedText: "--",
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: !hasActiveClients,
        stopDisabled: true,
      };
    }

    if (status.last_completed_run_id) {
      return {
        pillVariant: "ok",
        pillText: t("dashboard.recording_phase.saved"),
        phaseText: t("dashboard.recording_phase.saved"),
        summaryText: t("dashboard.logging.saved", { runId: status.last_completed_run_id }),
        runIdText,
        elapsedText: "--",
        samplesText,
        showStart: true,
        showStop: false,
        startDisabled: !hasActiveClients,
        stopDisabled: true,
      };
    }

    return {
      pillVariant: hasActiveClients ? "muted" : liveHealth.variant,
      pillText: t("dashboard.recording_phase.ready"),
      phaseText: t("dashboard.recording_phase.ready"),
      summaryText: hasActiveClients
        ? t("dashboard.logging.ready", { connected: connectedCount, assigned: assignedCount })
        : liveHealth.summary,
      runIdText,
      elapsedText: "--",
      samplesText,
      showStart: true,
      showStop: false,
      startDisabled: !hasActiveClients,
      stopDisabled: true,
    };
  }

  function renderLoggingStatus(): void {
    const panelState = computeRecordingPanelState();
    renderLiveOverviewStats();
    setPillState(els.loggingStatus, panelState.pillVariant, panelState.pillText);
    ctx.setStatValue(els.loggingPhase, panelState.phaseText);
    ctx.setStatValue(els.loggingElapsed, panelState.elapsedText);
    ctx.setStatValue(els.loggingSamples, panelState.samplesText);
    if (els.loggingSummary) {
      els.loggingSummary.textContent = panelState.summaryText;
    }
    if (els.loggingRunId) {
      els.loggingRunId.hidden = panelState.runIdText === "";
      els.loggingRunId.textContent = panelState.runIdText;
    }
    if (els.startLoggingBtn) {
      els.startLoggingBtn.hidden = !panelState.showStart;
      els.startLoggingBtn.disabled = panelState.startDisabled;
    }
    if (els.stopLoggingBtn) {
      els.stopLoggingBtn.hidden = !panelState.showStop;
      els.stopLoggingBtn.disabled = panelState.stopDisabled;
    }
    syncLoggingElapsedTimer();
    renderLiveHealth();
  }

  async function refreshLoggingStatus(): Promise<void> {
    if (isDemoMode && pendingLoggingAction === null) {
      renderLoggingStatus();
      return;
    }
    try {
      realtime.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      pendingLoggingAction = null;
      clearLoggingElapsedTimer();
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
      if (els.loggingSummary) {
        els.loggingSummary.textContent = t("status.unavailable");
      }
      if (els.loggingRunId) {
        els.loggingRunId.hidden = true;
        els.loggingRunId.textContent = "";
      }
      ctx.setStatValue(els.loggingPhase, t("status.unavailable"));
      ctx.setStatValue(els.loggingElapsed, "--");
      ctx.setStatValue(els.loggingSamples, "--");
      if (els.startLoggingBtn) {
        els.startLoggingBtn.hidden = false;
        els.startLoggingBtn.disabled = true;
      }
      if (els.stopLoggingBtn) {
        els.stopLoggingBtn.hidden = true;
        els.stopLoggingBtn.disabled = true;
      }
    }
  }

  async function startLogging(): Promise<void> {
    if (pendingLoggingAction) return;
    pendingLoggingAction = "starting";
    renderLoggingStatus();
    try {
      realtime.loggingStatus = await startLoggingRun();
      await ctx.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      pendingLoggingAction = null;
      setPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
      if (els.loggingSummary) {
        els.loggingSummary.textContent = msg || t("status.unavailable");
      }
      return;
    }
    pendingLoggingAction = null;
    renderLoggingStatus();
  }

  async function stopLogging(): Promise<void> {
    if (pendingLoggingAction) return;
    pendingLoggingAction = "stopping";
    renderLoggingStatus();
    try {
      realtime.loggingStatus = await stopLoggingRun();
      await ctx.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      pendingLoggingAction = null;
      setPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
      if (els.loggingSummary) {
        els.loggingSummary.textContent = msg || t("status.unavailable");
      }
      return;
    }
    pendingLoggingAction = null;
    renderLoggingStatus();
  }

  const loggingStatusPolling = createPollingController({
    poll: async () => {
      await refreshLoggingStatus();
      return realtime.loggingStatus.enabled || realtime.loggingStatus.analysis_in_progress
        ? LOGGING_STATUS_ACTIVE_POLL_MS
        : LOGGING_STATUS_IDLE_POLL_MS;
    },
    onErrorDelayMs: LOGGING_STATUS_ERROR_POLL_MS,
  });

  async function refreshLocationOptions(): Promise<void> {
    try {
      const payload = await getClientLocations();
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row) => row.code).filter((code): code is string => typeof code === "string")
        : [];
      applyLocationCodes(codes);
    } catch (_err) {
      applyLocationCodes([]);
    }
    maybeRenderSensorsSettingsList(true);
    renderStatus();
    renderLoggingStatus();
  }

  async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
    if (!clientId) return;
    const existing = realtime.clients.find((c) => c.id === clientId);
    if (existing && locationCodeForClient(existing) === locationCode) return;
    try {
      await setClientLocationApi(clientId, locationCode);
    } catch (err) {
      ctx.showError(err instanceof Error ? err.message : t("actions.set_location_failed"));
      return;
    }
    const client = realtime.clients.find((c) => c.id === clientId);
    if (client) {
      client.location_code = locationCode;
      maybeRenderSensorsSettingsList();
      renderStatus();
      renderLoggingStatus();
    }
  }

  async function identifyClient(clientId: string): Promise<void> {
    if (!clientId) return;
    await identifyClientApi(clientId); // uses API default of 1500 ms
  }

  async function removeClient(clientId: string): Promise<void> {
    if (!clientId) return;
    const ok = window.confirm(t("actions.remove_client_confirm", { id: clientId }));
    if (!ok) return;
    try {
      await removeClientApi(clientId);
    } catch (err) {
      ctx.showError(err instanceof Error ? err.message : t("actions.remove_client_failed"));
      return;
    }
    const prevSelected = realtime.selectedClientId;
    realtime.clients = realtime.clients.filter((c) => c.id !== clientId);
    if (realtime.selectedClientId === clientId) realtime.selectedClientId = null;
    updateClientSelection();
    maybeRenderSensorsSettingsList();
    renderLoggingStatus();
    renderStatus();
    if (prevSelected !== realtime.selectedClientId) ctx.sendSelection();
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    if (!isDemoMode) {
      loggingStatusPolling.start();
    }
    syncLoggingElapsedTimer();
    els.startLoggingBtn?.addEventListener("click", () => void startLogging());
    els.stopLoggingBtn?.addEventListener("click", () => void stopLogging());
    els.sensorsSettingsBody?.addEventListener("change", (event) => {
      const change = getRealtimeSensorTableLocationChange(event.target);
      if (!change) {
        return;
      }
      void setClientLocation(change.clientId, change.locationCode);
    });
    els.sensorsSettingsBody?.addEventListener("click", (event) => {
      const action = getRealtimeSensorTableClickAction(event.target);
      if (!action) {
        return;
      }
      if (action.type === "identify") {
        void identifyClient(action.clientId);
        return;
      }
      void removeClient(action.clientId);
    });
  }

  return {
    bindHandlers,
    buildLocationOptions,
    maybeRenderSensorsSettingsList,
    updateClientSelection,
    locationCodeForClient,
    renderStatus,
    renderLoggingStatus,
    refreshLoggingStatus,
    startLogging,
    stopLogging,
    refreshLocationOptions,
  };
}
