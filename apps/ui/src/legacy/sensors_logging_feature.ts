import * as I18N from "../i18n";
import {
  getClientLocations,
  getLoggingStatus,
  identifyClient as identifyClientApi,
  removeClient as removeClientApi,
  setClientLocation as setClientLocationApi,
  startLoggingRun,
  stopLoggingRun,
} from "../api";
import { defaultLocationCodes } from "../constants";

export function createSensorsLoggingFeature(ctx) {
  const { state, els, t, escapeHtml, formatInt, setPillState, renderMatrix } = ctx;

  function locationLabelForLang(lang, code) {
    return I18N.get(lang, `location.${code}`, { code });
  }

  function locationLabel(code) {
    return locationLabelForLang(state.lang, code);
  }

  function buildLocationOptions(codes) {
    return codes.map((code) => ({ code, label: locationLabel(code) }));
  }

  function locationCodeForClient(client) {
    const explicitCode = String(client?.location_code || client?.locationCode || "").trim();
    if (explicitCode && state.locationCodes.includes(explicitCode)) return explicitCode;
    const name = String(client?.name || "").trim();
    if (!name) return "";
    const normalizedName = name.toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    const shorthandMap = {
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

  function locationOptionsMarkup(selectedCode) {
    const opts = [`<option value="">${escapeHtml(t("settings.select_location"))}</option>`];
    for (const loc of state.locationOptions) {
      const selectedAttr = loc.code === selectedCode ? " selected" : "";
      opts.push(`<option value="${escapeHtml(loc.code)}"${selectedAttr}>${escapeHtml(loc.label)}</option>`);
    }
    return opts.join("");
  }

  function sensorsSettingsSignature() {
    const clientPart = state.clients
      .map((client) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}`;
      })
      .join("||");
    const locationPart = state.locationOptions.map((loc) => `${loc.code}|${loc.label}`).join("||");
    return `${clientPart}##${locationPart}`;
  }

  function maybeRenderSensorsSettingsList(force = false) {
    const nextSig = sensorsSettingsSignature();
    if (!force && nextSig === state.sensorsSettingsSignature) return;
    state.sensorsSettingsSignature = nextSig;
    renderSensorsSettingsList();
  }

  function updateClientSelection() {
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

  function renderSensorsSettingsList() {
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

    els.sensorsSettingsBody.querySelectorAll(".row-location-select").forEach((select) => {
      select.addEventListener("change", async () => {
        const clientId = select.getAttribute("data-client-id");
        if (!clientId) return;
        const locationCode = select.value || "";
        await setClientLocation(clientId, locationCode);
      });
    });

    els.sensorsSettingsBody.querySelectorAll(".row-identify").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (btn.hasAttribute("disabled")) return;
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

  function renderStatus(clientRow) {
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

  function renderLoggingStatus() {
    const status = state.loggingStatus || { enabled: false, current_file: null };
    const on = Boolean(status.enabled);
    const hasActiveClients = state.clients.some((client) => Boolean(client?.connected));
    setPillState(els.loggingStatus, on ? "ok" : "muted", on ? t("status.running") : t("status.stopped"));
    els.currentLogFile.textContent = t("status.current_file", { value: status.current_file || "--" });
    if (els.startLoggingBtn) els.startLoggingBtn.disabled = !hasActiveClients;
    if (els.stopLoggingBtn) els.stopLoggingBtn.disabled = !hasActiveClients;
  }

  async function refreshLoggingStatus() {
    try {
      state.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
    }
  }

  function resetLiveVibrationCounts() {
    state.eventMatrix = ctx.createEmptyMatrix();
    renderMatrix();
  }

  async function startLogging() {
    try {
      state.loggingStatus = await startLoggingRun();
      resetLiveVibrationCounts();
      renderLoggingStatus();
      await ctx.refreshHistory();
    } catch (_err) {}
  }

  async function stopLogging() {
    try {
      state.loggingStatus = await stopLoggingRun();
      renderLoggingStatus();
      await ctx.refreshHistory();
    } catch (_err) {}
  }

  async function refreshLocationOptions() {
    try {
      const payload = await getClientLocations();
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row) => row?.code).filter((code) => typeof code === "string")
        : [];
      state.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    } catch (_err) {
      state.locationCodes = defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    }
    maybeRenderSensorsSettingsList(true);
  }

  async function setClientLocation(clientId, locationCode) {
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

  async function identifyClient(clientId) {
    if (!clientId) return;
    await identifyClientApi(clientId, 1500);
  }

  async function removeClient(clientId) {
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
    setClientLocation,
    identifyClient,
    removeClient,
  };
}
