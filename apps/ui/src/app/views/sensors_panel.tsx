import type { JSX } from "preact";

import { render } from "preact";
import { useUiText } from "../ui_i18n";
import {
  signal,
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import type {
  RealtimeSensorTableClickAction,
  RealtimeSensorTableLocationChange,
  RealtimeSensorTableRenderModel,
  RealtimeSensorTableRowViewModel,
} from "./realtime_sensor_table_view";
import { createBoundViewModel } from "./view_model_binding";

export interface SensorsPanelRenderModel {
  table: RealtimeSensorTableRenderModel | null;
}

export interface SensorsPanelActionHandlers {
  onSensorLocationChange(change: RealtimeSensorTableLocationChange): void;
  onSensorTableAction(action: RealtimeSensorTableClickAction): void;
}

export interface SensorsPanelView {
  bindModel(model: ReadonlySignal<SensorsPanelRenderModel>): void;
  bindActions(handlers: SensorsPanelActionHandlers): void;
}

const DEFAULT_SENSORS_PANEL_MODEL: SensorsPanelRenderModel = {
  table: null,
};

const SENSORS_PANEL_MODEL_KEYS = ["table"] as const;

function handleSensorAction(
  event: JSX.TargetedMouseEvent<HTMLButtonElement>,
  actions: SensorsPanelActionHandlers | null,
  action: RealtimeSensorTableClickAction["type"],
  clientId: string,
): void {
  event.preventDefault();
  actions?.onSensorTableAction({ type: action, clientId });
}

function SensorsTableRow(props: {
  actions: SensorsPanelActionHandlers | null;
  row: RealtimeSensorTableRowViewModel;
}) {
  const { actions, row } = props;
  return (
    <tr data-client-id={row.clientId}>
      <td>
        <div class="settings-sensor-row__identity">
          <div class="settings-sensor-row__heading">
            <strong>{row.displayName}</strong>
            <span class={`status-pill settings-entity-status ${row.statusClass}`}>{row.statusText}</span>
          </div>
          <div class="settings-sensor-row__meta">
            <code>{row.macAddress}</code>
          </div>
        </div>
      </td>
      <td class="settings-sensor-row__location">
        <select
          class="row-location-select"
          data-client-id={row.clientId}
          value={row.selectedLocationCode}
          onChange={(event) =>
            actions?.onSensorLocationChange({
              clientId: row.clientId,
              locationCode: event.currentTarget.value || "",
            })}
        >
          <option value="">{row.locationSelectLabel}</option>
          {row.locationOptions.map((location) => (
            <option key={location.code} value={location.code}>
              {location.label}
            </option>
          ))}
        </select>
      </td>
      <td>
        <div class="settings-sensor-row__actions">
          <button
            class="btn row-identify"
            data-client-id={row.clientId}
            type="button"
            disabled={row.identifyDisabled}
            onClick={(event) => handleSensorAction(event, actions, "identify", row.clientId)}
          >
            {row.identifyLabel}
          </button>
          <button
            class="btn btn--danger-quiet row-remove"
            data-client-id={row.clientId}
            type="button"
            onClick={(event) => handleSensorAction(event, actions, "remove", row.clientId)}
          >
            {row.removeLabel}
          </button>
        </div>
      </td>
    </tr>
  );
}

function SensorsTableBody(props: {
  actions: SensorsPanelActionHandlers | null;
  table: RealtimeSensorTableRenderModel | null;
}) {
  const { actions, table } = props;
  const emptyText = useUiText("settings.sensors.no_sensors", "No sensors detected yet.");
  if (table === null || table.kind === "empty") {
    return (
      <tr>
        <td colSpan={3}>
          {table?.emptyText ?? emptyText}
        </td>
      </tr>
    );
  }
  return table.rows.map((row) => (
    <SensorsTableRow key={row.clientId} actions={actions} row={row} />
  ));
}

function SensorsPanel(props: {
  actions: ReadonlySignal<SensorsPanelActionHandlers | null>;
  model: ReadonlySignal<SensorsPanelRenderModel>;
}) {
  const titleText = useUiText("settings.sensors.title", "Sensors");
  const hintText = useUiText(
    "settings.sensors.hint",
    "Manage sensor names and locations. Default name is the MAC address.",
  );
  const nameLabel = useUiText("settings.sensors.name", "Name");
  const locationLabel = useUiText("settings.sensors.location", "Location");
  const actionsLabel = useUiText("settings.sensors.actions", "Actions");
  const { table } = useSignalProperties(props.model, SENSORS_PANEL_MODEL_KEYS);
  return (
    <div class="panel card">
      <strong>
        {titleText}
      </strong>
      <div class="subtle">
        {hintText}
      </div>
      <div class="settings-table-wrap">
        <table class="clients-table settings-entity-table settings-entity-table--sensors">
          <thead>
            <tr>
              <th>
                {nameLabel}
              </th>
              <th>
                {locationLabel}
              </th>
              <th>
                {actionsLabel}
              </th>
            </tr>
          </thead>
          <tbody id="sensorsSettingsBody">
            <SensorsTableBody actions={props.actions.value} table={table.value} />
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function mountSensorsPanel(host: HTMLElement): SensorsPanelView {
  const actions = signal<SensorsPanelActionHandlers | null>(null);
  const modelBinding = createBoundViewModel(DEFAULT_SENSORS_PANEL_MODEL);
  render(<SensorsPanel actions={actions} model={modelBinding.model} />, host);
  return {
    bindModel(model) {
      modelBinding.bind(model);
    },
    bindActions(handlers) {
      actions.value = handlers;
    },
  };
}
