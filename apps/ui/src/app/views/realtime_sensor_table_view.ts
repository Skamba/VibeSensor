import type { LocationOption } from "../../api/types";
import type { AdaptedClient } from "../../transport/live_models";

export interface RealtimeSensorTableViewParams {
  clients: AdaptedClient[];
  locationOptions: LocationOption[];
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface RealtimeSensorTableClickAction {
  type: "identify" | "remove";
  clientId: string;
}

export interface RealtimeSensorTableLocationChange {
  clientId: string;
  locationCode: string;
}

export interface RealtimeSensorTableLocationOptionViewModel {
  code: string;
  label: string;
}

export interface RealtimeSensorTableRowViewModel {
  clientId: string;
  displayName: string;
  statusText: string;
  statusClass: "online" | "offline";
  macAddress: string;
  selectedLocationCode: string;
  locationSelectLabel: string;
  locationOptions: RealtimeSensorTableLocationOptionViewModel[];
  identifyLabel: string;
  identifyDisabled: boolean;
  removeLabel: string;
}

export type RealtimeSensorTableRenderModel =
  | {
      kind: "empty";
      emptyText: string;
    }
  | {
      kind: "rows";
      rows: RealtimeSensorTableRowViewModel[];
    };

export function buildRealtimeSensorTableRenderModel(
  params: RealtimeSensorTableViewParams,
): RealtimeSensorTableRenderModel {
  const { clients, locationOptions, t } = params;
  if (!clients.length) {
    return {
      kind: "empty",
      emptyText: t("settings.sensors.no_sensors"),
    };
  }

  return {
    kind: "rows",
    rows: clients.map((client) => {
      const connected = Boolean(client.connected);
      return {
        clientId: client.id,
        displayName: String(client.name || client.id),
        statusText: connected ? t("status.online") : t("status.offline"),
        statusClass: connected ? "online" : "offline",
        macAddress: String(client.mac_address || client.id),
        selectedLocationCode: String(client.location_code || "").trim(),
        locationSelectLabel: t("settings.select_location"),
        locationOptions: locationOptions.map((location) => ({
          code: location.code,
          label: location.label,
        })),
        identifyLabel: t("actions.identify"),
        identifyDisabled: !connected,
        removeLabel: t("actions.remove"),
      };
    }),
  };
}
