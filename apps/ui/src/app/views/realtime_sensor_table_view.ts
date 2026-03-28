import type { LocationOption } from "../../api/types";
import type { AdaptedClient } from "../../server_payload";
import { closestFromTarget, renderTableEmptyRow } from "./dom_helpers";

export interface RealtimeSensorTableViewParams {
  clients: AdaptedClient[];
  locationOptions: LocationOption[];
  locationCodeForClient: (client: AdaptedClient) => string;
  strongestClientId?: string | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
}

function locationLabelForClient(
  client: AdaptedClient,
  params: RealtimeSensorTableViewParams,
): string {
  const code = params.locationCodeForClient(client);
  if (!code) {
    return params.t("dashboard.sensor_unassigned");
  }
  const option = params.locationOptions.find((location) => location.code === code);
  return option?.label ?? code;
}

export interface RealtimeSensorTableClickAction {
  type: "identify" | "remove";
  clientId: string;
}

export interface RealtimeSensorTableLocationChange {
  clientId: string;
  locationCode: string;
}

function locationOptionsMarkup(
  locationOptions: LocationOption[],
  selectedCode: string,
  t: (key: string, vars?: Record<string, unknown>) => string,
  escapeHtml: (value: unknown) => string,
): string {
  const opts = [`<option value="">${escapeHtml(t("settings.select_location"))}</option>`];
  for (const loc of locationOptions) {
    const selectedAttr = loc.code === selectedCode ? " selected" : "";
    opts.push(`<option value="${escapeHtml(loc.code)}"${selectedAttr}>${escapeHtml(loc.label)}</option>`);
  }
  return opts.join("");
}

export function renderRealtimeSensorTable(
  container: HTMLElement,
  params: RealtimeSensorTableViewParams,
): void {
  const { clients, locationOptions, locationCodeForClient, t, escapeHtml } = params;
  if (!clients.length) {
    container.innerHTML = renderTableEmptyRow(
      escapeHtml(t("settings.sensors.no_sensors")),
      5,
    );
    return;
  }

  container.innerHTML = clients
    .map((client) => {
      const selectedCode = locationCodeForClient(client);
      const connected = Boolean(client.connected);
      const statusText = connected ? t("status.online") : t("status.offline");
      const statusClass = connected ? "online" : "offline";
      const macAddress = client.mac_address || client.id;
      return `<tr data-client-id="${escapeHtml(client.id)}"><td><strong>${escapeHtml(client.name || client.id)}</strong><div class="subtle">${escapeHtml(client.id)}</div><div class="status-pill ${statusClass}">${statusText}</div></td><td><code>${escapeHtml(macAddress)}</code></td><td><select class="row-location-select" data-client-id="${escapeHtml(client.id)}">${locationOptionsMarkup(locationOptions, selectedCode, t, escapeHtml)}</select></td><td><button class="btn btn--primary row-identify" data-client-id="${escapeHtml(client.id)}"${connected ? "" : " disabled"}>${escapeHtml(t("actions.identify"))}</button></td><td><button class="btn btn--danger row-remove" data-client-id="${escapeHtml(client.id)}">${escapeHtml(t("actions.remove"))}</button></td></tr>`;
    })
    .join("");
}

export function renderRealtimeSensorOverview(
  container: HTMLElement,
  params: RealtimeSensorTableViewParams,
): void {
  const { clients, t, escapeHtml } = params;
  if (!clients.length) {
    container.innerHTML = `<div class="subtle">${escapeHtml(t("settings.sensors.no_sensors"))}</div>`;
    return;
  }

  container.innerHTML = clients
    .map((client) => {
      const connected = Boolean(client.connected);
      const statusText = connected ? t("status.online") : t("status.offline");
      const statusClass = connected ? "online" : "offline";
      const strongestClass = params.strongestClientId === client.id ? " live-sensor-card--strongest" : "";
      const primaryLabel = escapeHtml(client.name || client.id);
      const locationLabel = escapeHtml(locationLabelForClient(client, params));
      return `<article class="live-sensor-card${strongestClass}"><div class="live-sensor-card__header"><strong>${primaryLabel}</strong><span class="live-sensor-card__status-dot live-sensor-card__status-dot--${statusClass}" role="img" aria-label="${escapeHtml(statusText)}" title="${escapeHtml(statusText)}"></span></div><div class="live-sensor-card__meta">${locationLabel}</div><div class="live-sensor-card__subtle"><code>${escapeHtml(client.id)}</code></div></article>`;
    })
    .join("");
}

export function getRealtimeSensorTableClickAction(
  target: EventTarget | null,
): RealtimeSensorTableClickAction | null {
  const button = closestFromTarget<HTMLButtonElement>(target, ".row-identify, .row-remove");
  if (!button) {
    return null;
  }
  const clientId = button.getAttribute("data-client-id");
  if (!clientId) {
    return null;
  }
  return {
    type: button.classList.contains("row-identify") ? "identify" : "remove",
    clientId,
  };
}

export function getRealtimeSensorTableLocationChange(
  target: EventTarget | null,
): RealtimeSensorTableLocationChange | null {
  if (!(target instanceof HTMLSelectElement) || !target.classList.contains("row-location-select")) {
    return null;
  }
  const clientId = target.getAttribute("data-client-id");
  if (!clientId) {
    return null;
  }
  return {
    clientId,
    locationCode: target.value || "",
  };
}
