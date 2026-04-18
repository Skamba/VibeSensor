import type { JSX } from "preact";

import { render } from "preact";
import { getUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import type {
  RealtimeSensorTableClickAction,
  RealtimeSensorTableLocationChange,
  RealtimeSensorTableRenderModel,
  RealtimeSensorTableRowViewModel,
} from "./realtime_sensor_table_view";
import { type DeferredModelSignal } from "./view_model_binding";

export interface SensorsPanelRenderModel {
  table: RealtimeSensorTableRenderModel | null;
}

export interface SensorsPanelActionHandlers {
  onSensorLocationChange(change: RealtimeSensorTableLocationChange): void;
  onSensorTableAction(action: RealtimeSensorTableClickAction): void;
}

export interface SensorsPanelView {
  actions: Signal<SensorsPanelActionHandlers | null>;
  model: DeferredModelSignal<SensorsPanelRenderModel>;
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
  emptyText: string;
  table: RealtimeSensorTableRenderModel | null;
}) {
  const { actions, emptyText, table } = props;
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
  model: ReadonlySignal<ReadonlySignal<SensorsPanelRenderModel> | null>;
}) {
  const actions = useComputed(() => props.actions.value);
  const labels = useComputed(() => ({
    actionsLabel: getUiText("settings.sensors.actions", "Actions"),
    emptyText: getUiText("settings.sensors.no_sensors", "No sensors detected yet."),
    hintText: getUiText(
      "settings.sensors.hint",
      "Manage sensor names and locations. Default name is the MAC address.",
    ),
    locationLabel: getUiText("settings.sensors.location", "Location"),
    nameLabel: getUiText("settings.sensors.name", "Name"),
    titleText: getUiText("settings.sensors.title", "Sensors"),
  }));
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_SENSORS_PANEL_MODEL);
  const { table } = useSignalProperties(model, SENSORS_PANEL_MODEL_KEYS);
  const labelTexts = labels.value;
  return (
    <div class="panel card">
      <strong>
        {labelTexts.titleText}
      </strong>
      <div class="subtle">
        {labelTexts.hintText}
      </div>
      <div class="settings-table-wrap">
        <table class="clients-table settings-entity-table settings-entity-table--sensors">
          <thead>
            <tr>
                <th>
                 {labelTexts.nameLabel}
                </th>
                <th>
                 {labelTexts.locationLabel}
                </th>
                <th>
                 {labelTexts.actionsLabel}
                </th>
              </tr>
            </thead>
            <tbody id="sensorsSettingsBody">
             <SensorsTableBody
               actions={actions.value}
               emptyText={labelTexts.emptyText}
               table={table.value}
             />
            </tbody>
          </table>
        </div>
      </div>
  );
}

export function mountSensorsPanel(host: HTMLElement, view: SensorsPanelView): void {
  render(<SensorsPanel actions={view.actions} model={view.model} />, host);
}
