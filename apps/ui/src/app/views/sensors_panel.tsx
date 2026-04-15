import type { JSX } from "preact";

import { render } from "preact";
import { useUiTranslation } from "../ui_i18n";
import { signal, type ReadonlySignal } from "../ui_signals";
import type {
  RealtimeSensorTableClickAction,
  RealtimeSensorTableLocationChange,
  RealtimeSensorTableRenderModel,
  RealtimeSensorTableRowViewModel,
} from "./realtime_sensor_table_view";

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

type SensorsPanelBridgeState = {
  actions: SensorsPanelActionHandlers | null;
  model: ReadonlySignal<SensorsPanelRenderModel> | null;
};

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
  const t = useUiTranslation();
  if (table === null || table.kind === "empty") {
    return (
      <tr>
        <td colSpan={3}>
          {table?.emptyText ?? t("settings.sensors.no_sensors", "No sensors detected yet.")}
        </td>
      </tr>
    );
  }
  return table.rows.map((row) => (
    <SensorsTableRow key={row.clientId} actions={actions} row={row} />
  ));
}

function SensorsPanel(props: { state: ReadonlySignal<SensorsPanelBridgeState> }) {
  const state = props.state.value;
  const model = state.model?.value ?? { table: null };
  const t = useUiTranslation();
  return (
    <div class="panel card">
      <strong>
        {t("settings.sensors.title", "Sensors")}
      </strong>
      <div class="subtle">
        {t(
          "settings.sensors.hint",
          "Manage sensor names and locations. Default name is the MAC address.",
        )}
      </div>
      <div class="settings-table-wrap">
        <table class="clients-table settings-entity-table settings-entity-table--sensors">
          <thead>
            <tr>
              <th>
                {t("settings.sensors.name", "Name")}
              </th>
              <th>
                {t("settings.sensors.location", "Location")}
              </th>
              <th>
                {t("settings.sensors.actions", "Actions")}
              </th>
            </tr>
          </thead>
          <tbody id="sensorsSettingsBody">
            <SensorsTableBody actions={state.actions} table={model.table} />
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function mountSensorsPanel(host: HTMLElement): SensorsPanelView {
  const state = signal<SensorsPanelBridgeState>({
    actions: null,
    model: null,
  });
  render(<SensorsPanel state={state} />, host);
  return {
    bindModel(model) {
      state.value = { ...state.value, model };
    },
    bindActions(handlers) {
      state.value = { ...state.value, actions: handlers };
    },
  };
}
