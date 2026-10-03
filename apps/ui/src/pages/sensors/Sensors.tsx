import { memo } from "preact/compat";

import { t } from "../../i18n";
import { clients, locationChoices } from "../../live_store";
import type { LocationOption } from "../../sensor_locations";
import { identify, remove, setLocation } from "./sensors_store";

/**
 * Memoized so live updates (several per second) leave unchanged rows alone;
 * re-rendering would reset a location the user just picked before it saves.
 */
const SensorRow = memo(function SensorRow(props: {
  id: string;
  name: string;
  mac: string;
  connected: boolean;
  locationCode: string;
  options: readonly LocationOption[];
}) {
  const { id, connected } = props;
  return (
    <tr data-client-id={id}>
      <td>
        <div class="settings-sensor-row__identity">
          <div class="settings-sensor-row__heading">
            <strong>{props.name}</strong>
            <span
              class="status-pill settings-entity-status"
              data-status={connected ? "online" : "offline"}
            >
              {t(connected ? "status.online" : "status.offline")}
            </span>
          </div>
          <div class="settings-sensor-row__meta">
            <code>{props.mac}</code>
          </div>
        </div>
      </td>
      <td class="settings-sensor-row__location">
        <select
          class="row-location-select"
          data-client-id={id}
          value={props.locationCode}
          onChange={(event) => void setLocation(id, event.currentTarget.value)}
        >
          <option value="">{t("settings.select_location")}</option>
          {props.options.map((location) => (
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
            data-client-id={id}
            type="button"
            disabled={!connected}
            onClick={() => void identify(id)}
          >
            {t("actions.identify")}
          </button>
          <button
            class="btn btn--danger-quiet row-remove"
            data-client-id={id}
            type="button"
            onClick={() => void remove(id)}
          >
            {t("actions.remove")}
          </button>
        </div>
      </td>
    </tr>
  );
});

/** Settings > Sensors: name, location, identify, and remove per sensor. */
export function Sensors() {
  const list = clients.value;
  return (
    <div class="panel card">
      <strong>{t("settings.sensors.title")}</strong>
      <div class="subtle">{t("settings.sensors.hint")}</div>
      <div class="settings-table-wrap">
        <table class="clients-table settings-entity-table settings-entity-table--sensors">
          <thead>
            <tr>
              <th>{t("settings.sensors.name")}</th>
              <th>{t("settings.sensors.location")}</th>
              <th>{t("settings.sensors.actions")}</th>
            </tr>
          </thead>
          <tbody id="sensorsSettingsBody">
            {list.length === 0 ? (
              <tr>
                <td colSpan={3}>{t("settings.sensors.no_sensors")}</td>
              </tr>
            ) : (
              list.map((client) => (
                <SensorRow
                  key={client.id}
                  id={client.id}
                  name={String(client.name || client.id)}
                  mac={String(client.mac_address || client.id)}
                  connected={Boolean(client.connected)}
                  locationCode={String(client.location_code || "").trim()}
                  options={locationChoices.value}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
