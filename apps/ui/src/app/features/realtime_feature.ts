import type { FeatureDepsBase } from "../feature_deps_base";
import type { RealtimeState, SpectrumState } from "../ui_app_state";
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

export interface RealtimeFeatureDeps extends FeatureDepsBase {
  realtime: RealtimeState;
  spectrum: SpectrumState;
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
  const { realtime, spectrum, els, t, escapeHtml, formatInt, setPillState } = ctx;
  let handlersBound = false;

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

  function selectedClient(clientRow?: AdaptedClient): AdaptedClient | undefined {
    if (clientRow) {
      return clientRow;
    }
    return realtime.clients.find((client) => client.id === realtime.selectedClientId);
  }

  function strongestSignalText(): string {
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
      return t("dashboard.strongest_signal_none");
    }
    const primary = locationCodeForClient(bestClient) ? clientLocationText(bestClient) : clientDisplayName(bestClient);
    return `${primary} (${formatInt(bestDb)} dB)`;
  }

  function focusSensorText(clientRow?: AdaptedClient): string {
    const client = selectedClient(clientRow);
    if (!client) {
      return t("dashboard.focus_sensor_none");
    }
    const primary = locationCodeForClient(client) ? clientLocationText(client) : clientDisplayName(client);
    const statusText = client.connected ? t("status.online") : t("status.offline");
    return `${primary} (${statusText})`;
  }

  type LiveHealth = {
    variant: "muted" | "ok" | "warn" | "bad";
    text: string;
    summary: string;
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
    renderRealtimeSensorOverview(els.liveSensorRoster, {
      clients: realtime.clients,
      locationOptions: realtime.locationOptions,
      locationCodeForClient,
      t,
      escapeHtml,
    });
  }

  function renderLiveOverviewStats(clientRow?: AdaptedClient): void {
    const totalClients = realtime.clients.length;
    ctx.setStatValue(els.liveConnectedSensors, `${formatInt(connectedClients().length)} / ${formatInt(totalClients)}`);
    ctx.setStatValue(els.liveAssignedLocations, `${formatInt(assignedClientCount())} / ${formatInt(totalClients)}`);
    ctx.setStatValue(els.liveFocusSensor, focusSensorText(clientRow));
    ctx.setStatValue(els.liveStrongestSignal, strongestSignalText());
  }

  function renderLiveHealth(): void {
    const health = computeLiveHealth();
    setPillState(els.liveRunHealth, health.variant, health.text);
    setPillState(els.shellLiveStatus, health.variant, health.text);
    if (els.loggingSummary) {
      els.loggingSummary.textContent = health.summary;
    }
    if (els.loggingRunId) {
      const runId = realtime.loggingStatus.run_id;
      els.loggingRunId.hidden = !runId;
      els.loggingRunId.textContent = runId ? t("dashboard.logging.run_id", { runId }) : "";
    }
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
    const currentClient = selectedClient(clientRow);
    renderLiveOverviewStats(currentClient);
    if (!currentClient) {
      ctx.setStatValue(els.lastSeen, "--");
      ctx.setStatValue(els.dropped, "--");
      ctx.setStatValue(els.framesTotal, "--");
      return;
    }
    const age = currentClient.last_seen_age_ms ?? null;
    const ageValue = age === null ? "--" : t("status.age_ms_ago", { value: formatInt(Math.max(0, age)) });
    ctx.setStatValue(els.lastSeen, ageValue);
    ctx.setStatValue(els.dropped, formatInt(currentClient.dropped_frames ?? 0));
    ctx.setStatValue(els.framesTotal, formatInt(currentClient.frames_total ?? 0));
  }

  function renderLoggingStatus(): void {
    const status = realtime.loggingStatus;
    const on = Boolean(status.enabled);
    const hasActiveClients = realtime.clients.some((client) => Boolean(client?.connected));
    if (status.write_error) {
      setPillState(els.loggingStatus, "bad", status.write_error);
    } else {
      setPillState(els.loggingStatus, on ? "ok" : "muted", on ? t("status.running") : t("status.stopped"));
    }
    if (els.startLoggingBtn) els.startLoggingBtn.disabled = on || !hasActiveClients;
    if (els.stopLoggingBtn) els.stopLoggingBtn.disabled = !on;
    renderLiveHealth();
  }

  async function refreshLoggingStatus(): Promise<void> {
    try {
      realtime.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
      if (els.loggingSummary) {
        els.loggingSummary.textContent = t("status.unavailable");
      }
      if (els.loggingRunId) {
        els.loggingRunId.hidden = true;
        els.loggingRunId.textContent = "";
      }
    }
  }

  async function startLogging(): Promise<void> {
    try {
      realtime.loggingStatus = await startLoggingRun();
      renderLoggingStatus();
      await ctx.onRecordingStatusChanged();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
    }
  }

  async function stopLogging(): Promise<void> {
    try {
      realtime.loggingStatus = await stopLoggingRun();
      renderLoggingStatus();
      await ctx.onRecordingStatusChanged();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
    }
  }

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
