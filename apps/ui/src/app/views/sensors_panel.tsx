import { h } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";

export interface SensorsPanelDom {
  sensorsSettingsBody: HTMLElement | null;
}

export interface SensorsPanelView {
  readonly dom: SensorsPanelDom;
}

function SensorsPanel() {
  return (
    <div class="panel card">
      <strong data-i18n="settings.sensors.title">Sensors</strong>
      <div class="subtle" data-i18n="settings.sensors.hint">
        Manage sensor names and locations. Default name is the MAC address.
      </div>
      <table class="clients-table">
        <thead>
          <tr>
            <th data-i18n="settings.sensors.name">Name</th>
            <th data-i18n="settings.sensors.mac">MAC Address</th>
            <th data-i18n="settings.sensors.location">Location</th>
            <th data-i18n="settings.sensors.identify">Identify</th>
            <th data-i18n="settings.sensors.remove">Remove</th>
          </tr>
        </thead>
        <tbody id="sensorsSettingsBody">
          <tr>
            <td colSpan={5}>No sensors detected yet.</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function createSensorsPanelDom(host: HTMLElement): SensorsPanelDom {
  return {
    sensorsSettingsBody: host.querySelector<HTMLElement>("#sensorsSettingsBody"),
  };
}

export function mountSensorsPanel(host: HTMLElement): SensorsPanelView {
  createUiPreactMount(host).render(<SensorsPanel />);
  return {
    dom: createSensorsPanelDom(host),
  };
}
