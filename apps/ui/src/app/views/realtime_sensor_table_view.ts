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

function sameLocationOption(
  left: RealtimeSensorTableLocationOptionViewModel,
  right: RealtimeSensorTableLocationOptionViewModel,
): boolean {
  return left.code === right.code && left.label === right.label;
}

function sameLocationOptions(
  left: readonly RealtimeSensorTableLocationOptionViewModel[],
  right: readonly RealtimeSensorTableLocationOptionViewModel[],
): boolean {
  return left.length === right.length
    && left.every((option, index) => sameLocationOption(option, right[index]));
}

function sameSensorRow(
  left: RealtimeSensorTableRowViewModel,
  right: RealtimeSensorTableRowViewModel,
): boolean {
  return left.clientId === right.clientId
    && left.displayName === right.displayName
    && left.statusText === right.statusText
    && left.statusClass === right.statusClass
    && left.macAddress === right.macAddress
    && left.selectedLocationCode === right.selectedLocationCode
    && left.locationSelectLabel === right.locationSelectLabel
    && sameLocationOptions(left.locationOptions, right.locationOptions)
    && left.identifyLabel === right.identifyLabel
    && left.identifyDisabled === right.identifyDisabled
    && left.removeLabel === right.removeLabel;
}

function sameRowReferences(
  left: readonly RealtimeSensorTableRowViewModel[],
  right: readonly RealtimeSensorTableRowViewModel[],
): boolean {
  return left.length === right.length && left.every((row, index) => row === right[index]);
}

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

export function createRealtimeSensorTableRenderModelMemo(): (
  params: RealtimeSensorTableViewParams,
) => RealtimeSensorTableRenderModel {
  let previousModel: RealtimeSensorTableRenderModel | null = null;
  let previousRowsById = new Map<string, RealtimeSensorTableRowViewModel>();

  return (params: RealtimeSensorTableViewParams): RealtimeSensorTableRenderModel => {
    const nextModel = buildRealtimeSensorTableRenderModel(params);
    if (nextModel.kind === "empty") {
      previousRowsById = new Map();
      if (previousModel?.kind === "empty" && previousModel.emptyText === nextModel.emptyText) {
        return previousModel;
      }
      previousModel = nextModel;
      return nextModel;
    }

    const nextRows = nextModel.rows.map((row) => {
      const previousRow = previousRowsById.get(row.clientId);
      return previousRow && sameSensorRow(previousRow, row) ? previousRow : row;
    });
    previousRowsById = new Map(nextRows.map((row) => [row.clientId, row]));
    if (previousModel?.kind === "rows" && sameRowReferences(previousModel.rows, nextRows)) {
      return previousModel;
    }

    previousModel = {
      kind: "rows",
      rows: nextRows,
    };
    return previousModel;
  };
}
