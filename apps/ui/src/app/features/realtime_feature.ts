import type { FeatureDepsBase } from "../feature_deps_base";
import type { RealtimeState } from "../ui_app_state";
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
  renderRealtimeSensorTable,
} from "../views/realtime_sensor_table_view";

export interface RealtimeFeatureDeps extends FeatureDepsBase {
  realtime: RealtimeState;
  getLanguage: () => string;
  formatInt: (value: number) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
  sendSelection: () => void;
  refreshHistory: () => Promise<void>;
}

export interface RealtimeFeature {
  bindHandlers(): void;
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  maybeRenderSensorsSettingsList(force?: boolean): void;
  updateClientSelection(): void;
  locationCodeForClient(client: AdaptedClient): string;
  renderStatus(clientRow: AdaptedClient | undefined): void;
  renderLoggingStatus(): void;
  refreshLoggingStatus(): Promise<void>;
  startLogging(): Promise<void>;
  stopLogging(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

export function createRealtimeFeature(ctx: RealtimeFeatureDeps): RealtimeFeature {
  const { realtime, els, t, escapeHtml, formatInt, setPillState } = ctx;
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

  function renderStatus(clientRow: AdaptedClient | undefined): void {
    if (!clientRow) {
      ctx.setStatValue(els.lastSeen, "--");
      ctx.setStatValue(els.dropped, "--");
      ctx.setStatValue(els.framesTotal, "--");
      return;
    }
    const age = clientRow.last_seen_age_ms ?? null;
    const ageValue = age === null ? "--" : t("status.age_ms_ago", { value: formatInt(Math.max(0, age)) });
    ctx.setStatValue(els.lastSeen, ageValue);
    ctx.setStatValue(els.dropped, formatInt(clientRow.dropped_frames ?? 0));
    ctx.setStatValue(els.framesTotal, formatInt(clientRow.frames_total ?? 0));
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
  }

  async function refreshLoggingStatus(): Promise<void> {
    try {
      realtime.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
    }
  }

  async function startLogging(): Promise<void> {
    try {
      realtime.loggingStatus = await startLoggingRun();
      renderLoggingStatus();
      await ctx.refreshHistory();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPillState(els.loggingStatus, "bad", msg || t("status.unavailable"));
    }
  }

  async function stopLogging(): Promise<void> {
    try {
      realtime.loggingStatus = await stopLoggingRun();
      renderLoggingStatus();
      await ctx.refreshHistory();
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
      realtime.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
      realtime.locationOptions = buildLocationOptions(realtime.locationCodes);
    } catch (_err) {
      realtime.locationCodes = defaultLocationCodes.slice();
      realtime.locationOptions = buildLocationOptions(realtime.locationCodes);
    }
    maybeRenderSensorsSettingsList(true);
  }

  async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
    if (!clientId) return;
    const existing = realtime.clients.find((c) => c.id === clientId);
    if (existing && locationCodeForClient(existing) === locationCode) return;
    try {
      await setClientLocationApi(clientId, locationCode);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : t("actions.set_location_failed"));
      return;
    }
    const client = realtime.clients.find((c) => c.id === clientId);
    if (client) {
      client.location_code = locationCode;
      maybeRenderSensorsSettingsList();
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
      window.alert(err instanceof Error ? err.message : t("actions.remove_client_failed"));
      return;
    }
    const prevSelected = realtime.selectedClientId;
    realtime.clients = realtime.clients.filter((c) => c.id !== clientId);
    if (realtime.selectedClientId === clientId) realtime.selectedClientId = null;
    updateClientSelection();
    maybeRenderSensorsSettingsList();
    renderLoggingStatus();
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
