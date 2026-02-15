import * as I18N from "../i18n";
import { getClientLocations } from "../api";
import { defaultLocationCodes } from "../constants";
import { escapeHtml } from "../format";

type ClientSettingsDeps = {
  els: Record<string, any>;
  state: Record<string, any>;
  t: (key: string, vars?: Record<string, any>) => string;
  buildLocationOptions: (codes: string[]) => Array<{ code: string; label: string }>;
  onSetLocation: (clientId: string, locationCode: string) => Promise<void>;
  onIdentify: (clientId: string) => Promise<void>;
  onRemove: (clientId: string) => Promise<void>;
};

export function createClientsSettingsController({
  els,
  state,
  t,
  buildLocationOptions,
  onSetLocation,
  onIdentify,
  onRemove,
}: ClientSettingsDeps) {
  function locationCodeForClient(client: any) {
    const name = String(client?.name || "").trim();
    if (!name) return "";
    for (const code of state.locationCodes) {
      const labels = I18N.getForAllLangs(`location.${code}`);
      if (labels.some((label) => label === name)) return code;
    }
    const match = state.locationOptions.find((loc: any) => loc.label === name);
    return match ? match.code : "";
  }

  function locationOptionsMarkup(selectedCode: string) {
    const opts = [`<option value="">${escapeHtml(t("settings.select_location"))}</option>`];
    for (const loc of state.locationOptions) {
      const selectedAttr = loc.code === selectedCode ? " selected" : "";
      opts.push(
        `<option value="${escapeHtml(loc.code)}"${selectedAttr}>${escapeHtml(loc.label)}</option>`,
      );
    }
    return opts.join("");
  }

  function clientsSettingsSignature() {
    const clientPart = state.clients
      .map((client: any) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}`;
      })
      .join("||");
    const locationPart = state.locationOptions.map((loc: any) => `${loc.code}|${loc.label}`).join("||");
    return `${clientPart}##${locationPart}`;
  }

  function renderClientsSettingsList() {
    if (!els.clientsSettingsBody) return;
    if (!state.clients.length) {
      els.clientsSettingsBody.innerHTML = `<tr><td colspan="5">${escapeHtml(t("settings.no_clients"))}</td></tr>`;
      return;
    }
    els.clientsSettingsBody.innerHTML = state.clients
      .map((client: any) => {
        const selectedCode = locationCodeForClient(client);
        const connected = Boolean(client.connected);
        const statusText = connected ? t("status.online") : t("status.offline");
        const statusClass = connected ? "online" : "offline";
        const macAddress = client.mac_address || client.id;
        return `
      <tr data-client-id="${escapeHtml(client.id)}">
        <td>
          <strong>${escapeHtml(client.name || client.id)}</strong>
          <div class="subtle">${escapeHtml(client.id)}</div>
          <div class="status-pill ${statusClass}">${statusText}</div>
        </td>
        <td><code>${escapeHtml(macAddress)}</code></td>
        <td>
          <select class="row-location-select" data-client-id="${escapeHtml(client.id)}">
            ${locationOptionsMarkup(selectedCode)}
          </select>
        </td>
        <td><button class="btn btn--primary row-identify" data-client-id="${escapeHtml(client.id)}"${connected ? "" : " disabled"}>${escapeHtml(t("actions.identify"))}</button></td>
        <td><button class="btn btn--danger row-remove" data-client-id="${escapeHtml(client.id)}">${escapeHtml(t("actions.remove"))}</button></td>
      </tr>`;
      })
      .join("");

    els.clientsSettingsBody.querySelectorAll(".row-location-select").forEach((select: any) => {
      select.addEventListener("change", async () => {
        const clientId = select.getAttribute("data-client-id");
        if (!clientId) return;
        const locationCode = select.value || "";
        await onSetLocation(clientId, locationCode);
      });
    });

    els.clientsSettingsBody.querySelectorAll(".row-identify").forEach((btn: any) => {
      btn.addEventListener("click", async () => {
        if (btn.hasAttribute("disabled")) return;
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await onIdentify(clientId);
      });
    });

    els.clientsSettingsBody.querySelectorAll(".row-remove").forEach((btn: any) => {
      btn.addEventListener("click", async () => {
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await onRemove(clientId);
      });
    });
  }

  function maybeRenderClientsSettingsList(force = false) {
    const nextSig = clientsSettingsSignature();
    if (!force && nextSig === state.clientsSettingsSignature) return;
    state.clientsSettingsSignature = nextSig;
    renderClientsSettingsList();
  }

  async function refreshLocationOptions() {
    try {
      const payload = await getClientLocations();
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row: any) => row?.code).filter((code: unknown) => typeof code === "string")
        : [];
      state.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    } catch (_err) {
      state.locationCodes = defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    }
    maybeRenderClientsSettingsList(true);
  }

  return {
    locationCodeForClient,
    maybeRenderClientsSettingsList,
    refreshLocationOptions,
  };
}
