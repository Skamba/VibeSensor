import type { UiDomElements } from "../dom/ui_dom_registry";
import type { AppState, ClientRow, LocationOption } from "../state/ui_app_state";
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

export interface RealtimeFeatureDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, any>) => string;
  escapeHtml: (value: unknown) => string;
  formatInt: (value: number) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
  createEmptyMatrix: () => Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>>;
  renderMatrix: () => void;
  sendSelection: () => void;
  refreshHistory: () => Promise<void>;
}

export interface RealtimeFeature {
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  maybeRenderSensorsSettingsList(force?: boolean): void;
  updateClientSelection(): void;
  locationCodeForClient(client: ClientRow): string;
  renderStatus(clientRow: ClientRow | undefined): void;
  renderLoggingStatus(): void;
  refreshLoggingStatus(): Promise<void>;
  startLogging(): Promise<void>;
  stopLogging(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

export function createRealtimeFeature(ctx: RealtimeFeatureDeps): RealtimeFeature {
  const { state, els, t, escapeHtml, formatInt, setPillState, renderMatrix } = ctx;

  function locationLabelForLang(lang: string, code: string): string {
    return I18N.get(lang, `location.${code}`, { code });
  }

  function locationLabel(code: string): string {
    return locationLabelForLang(state.lang, code);
  }

  function buildLocationOptions(codes: readonly string[]): LocationOption[] {
    return codes.map((code) => ({ code, label: locationLabel(code) }));
  }

  function locationCodeForClient(client: ClientRow): string {
    const explicitCode = String(client?.location_code || "").trim();
    if (explicitCode && state.locationCodes.includes(explicitCode)) return explicitCode;
    const name = String(client?.name || "").trim();
    if (!name) return "";
    const normalizedName = name.toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    const shorthandMap: Record<string, string> = {
      "front left": "front_left_wheel",
      "front right": "front_right_wheel",
      "rear left": "rear_left_wheel",
      "rear right": "rear_right_wheel",
      driver: "driver_seat",
    };
    for (const [token, code] of Object.entries(shorthandMap)) {
      if (normalizedName.includes(token) && state.locationCodes.includes(code)) return code;
    }
    for (const code of state.locationCodes) {
      const labels = I18N.getForAllLangs(`location.${code}`);
      if (labels.some((label) => label === name)) return code;
    }
    const match = state.locationOptions.find((loc) => loc.label === name);
    return match ? match.code : "";
  }

  function locationOptionsMarkup(selectedCode: string): string {
    const opts = [`<option value="">${escapeHtml(t("settings.select_location"))}</option>`];
    for (const loc of state.locationOptions) {
      const selectedAttr = loc.code === selectedCode ? " selected" : "";
      opts.push(`<option value="${escapeHtml(loc.code)}"${selectedAttr}>${escapeHtml(loc.label)}</option>`);
    }
    return opts.join("");
  }

  function sensorsSettingsSignature(): string {
    const clientPart = state.clients
      .map((client) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}`;
      })
      .join("||");
    const locationPart = state.locationOptions.map((loc) => `${loc.code}|${loc.label}`).join("||");
    return `${clientPart}##${locationPart}`;
  }

  function maybeRenderSensorsSettingsList(force = false): void {
    const nextSig = sensorsSettingsSignature();
    if (!force && nextSig === state.sensorsSettingsSignature) return;
    state.sensorsSettingsSignature = nextSig;
    renderSensorsSettingsList();
  }

  function updateClientSelection(): void {
    const current = state.selectedClientId;
    const firstConnected = state.clients.find((c) => Boolean(c.connected));
    if (!state.selectedClientId && state.clients.length > 0) {
      state.selectedClientId = firstConnected ? firstConnected.id : state.clients[0].id;
    }
    if (current && state.clients.some((c) => c.id === current)) state.selectedClientId = current;
    if (state.selectedClientId && !state.clients.some((c) => c.id === state.selectedClientId)) {
      state.selectedClientId = firstConnected ? firstConnected.id : state.clients.length ? state.clients[0].id : null;
    }
  }

  function renderSensorsSettingsList(): void {
    if (!els.sensorsSettingsBody) return;
    if (!state.clients.length) {
      els.sensorsSettingsBody.innerHTML = `<tr><td colspan="5">${escapeHtml(t("settings.sensors.no_sensors"))}</td></tr>`;
      return;
    }
    els.sensorsSettingsBody.innerHTML = state.clients
      .map((client) => {
        const selectedCode = locationCodeForClient(client);
        const connected = Boolean(client.connected);
        const statusText = connected ? t("status.online") : t("status.offline");
        const statusClass = connected ? "online" : "offline";
        const macAddress = client.mac_address || client.id;
        return `<tr data-client-id="${escapeHtml(client.id)}"><td><strong>${escapeHtml(client.name || client.id)}</strong><div class="subtle">${escapeHtml(client.id)}</div><div class="status-pill ${statusClass}">${statusText}</div></td><td><code>${escapeHtml(macAddress)}</code></td><td><select class="row-location-select" data-client-id="${escapeHtml(client.id)}">${locationOptionsMarkup(selectedCode)}</select></td><td><button class="btn btn--primary row-identify" data-client-id="${escapeHtml(client.id)}"${connected ? "" : " disabled"}>${escapeHtml(t("actions.identify"))}</button></td><td><button class="btn btn--danger row-remove" data-client-id="${escapeHtml(client.id)}">${escapeHtml(t("actions.remove"))}</button></td></tr>`;
      })
      .join("");

    els.sensorsSettingsBody.querySelectorAll(".row-location-select").forEach((selectNode) => {
      const select = selectNode as HTMLSelectElement;
      select.addEventListener("change", async () => {
        const clientId = select.getAttribute("data-client-id");
        if (!clientId) return;
        const locationCode = select.value || "";
        await setClientLocation(clientId, locationCode);
      });
    });

    els.sensorsSettingsBody.querySelectorAll(".row-identify").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if ((btn as HTMLButtonElement).disabled) return;
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await identifyClient(clientId);
      });
    });

    els.sensorsSettingsBody.querySelectorAll(".row-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await removeClient(clientId);
      });
    });
  }

  function renderStatus(clientRow: ClientRow | undefined): void {
    if (!clientRow) {
      ctx.setStatValue(els.lastSeen, "--");
      ctx.setStatValue(els.dropped, "--");
      ctx.setStatValue(els.framesTotal, "--");
      return;
    }
    const age = clientRow.last_seen_age_ms ?? null;
    const ageSuffix = state.lang === "nl" ? "ms geleden" : "ms ago";
    const ageValue = age === null ? "--" : `${formatInt(Math.max(0, age))} ${ageSuffix}`;
    ctx.setStatValue(els.lastSeen, ageValue);
    ctx.setStatValue(els.dropped, formatInt(clientRow.dropped_frames ?? 0));
    ctx.setStatValue(els.framesTotal, formatInt(clientRow.frames_total ?? 0));
  }

  function renderLoggingStatus(): void {
    const status = state.loggingStatus || { enabled: false, current_file: null };
    const on = Boolean(status.enabled);
    const hasActiveClients = state.clients.some((client) => Boolean(client?.connected));
    setPillState(els.loggingStatus, on ? "ok" : "muted", on ? t("status.running") : t("status.stopped"));
    if (els.currentLogFile) els.currentLogFile.textContent = t("status.current_file", { value: status.current_file || "--" });
    if (els.startLoggingBtn) els.startLoggingBtn.disabled = !hasActiveClients;
    if (els.stopLoggingBtn) els.stopLoggingBtn.disabled = !hasActiveClients;
  }

  async function refreshLoggingStatus(): Promise<void> {
    try {
      state.loggingStatus = await getLoggingStatus() as AppState["loggingStatus"];
      renderLoggingStatus();
    } catch (_err) {
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
    }
  }

  function resetLiveVibrationCounts(): void {
    state.eventMatrix = ctx.createEmptyMatrix();
    renderMatrix();
  }

  async function startLogging(): Promise<void> {
    try {
      state.loggingStatus = await startLoggingRun() as AppState["loggingStatus"];
      resetLiveVibrationCounts();
      renderLoggingStatus();
      await ctx.refreshHistory();
    } catch (_err) { /* ignore */ }
  }

  async function stopLogging(): Promise<void> {
    try {
      state.loggingStatus = await stopLoggingRun() as AppState["loggingStatus"];
      renderLoggingStatus();
      await ctx.refreshHistory();
    } catch (_err) { /* ignore */ }
  }

  async function refreshLocationOptions(): Promise<void> {
    try {
      const payload = await getClientLocations() as Record<string, any>;
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row: Record<string, any>) => row?.code).filter((code): code is string => typeof code === "string")
        : [];
      state.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    } catch (_err) {
      state.locationCodes = defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    }
    maybeRenderSensorsSettingsList(true);
  }

  async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
    if (!clientId || !locationCode) return;
    const existing = state.clients.find((c) => c.id === clientId);
    if (existing && locationCodeForClient(existing) === locationCode) return;
    try {
      await setClientLocationApi(clientId, locationCode);
    } catch (err) {
      window.alert(err?.message || t("actions.set_location_failed"));
      return;
    }
    const selected = state.locationOptions.find((loc) => loc.code === locationCode);
    if (selected) {
      const client = state.clients.find((c) => c.id === clientId);
      if (client) client.name = selected.label;
      maybeRenderSensorsSettingsList();
    }
  }

  async function identifyClient(clientId: string): Promise<void> {
    if (!clientId) return;
    await identifyClientApi(clientId, 1500);
  }

  async function removeClient(clientId: string): Promise<void> {
    if (!clientId) return;
    const ok = window.confirm(t("actions.remove_client_confirm", { id: clientId }));
    if (!ok) return;
    try {
      await removeClientApi(clientId);
    } catch (err) {
      window.alert(err?.message || t("actions.remove_client_failed"));
      return;
    }
    const prevSelected = state.selectedClientId;
    state.clients = state.clients.filter((c) => c.id !== clientId);
    if (state.selectedClientId === clientId) state.selectedClientId = null;
    updateClientSelection();
    maybeRenderSensorsSettingsList();
    renderLoggingStatus();
    if (prevSelected !== state.selectedClientId) ctx.sendSelection();
  }

  return {
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
