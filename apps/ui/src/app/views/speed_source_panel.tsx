import { h } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";

export interface SettingsSpeedSourcePanelDom {
  speedSourceRadios: HTMLInputElement[];
  speedSourceCurrentSource: HTMLElement | null;
  speedSourceEffectiveSpeed: HTMLElement | null;
  speedSourceChoiceGps: HTMLElement | null;
  speedSourceChoiceObd: HTMLElement | null;
  speedSourceChoiceManual: HTMLElement | null;
  manualSpeedConfig: HTMLElement | null;
  manualSpeedInput: HTMLInputElement | null;
  manualSpeedFeedback: HTMLElement | null;
  obdSpeedConfig: HTMLElement | null;
  obdConfiguredDevice: HTMLElement | null;
  scanObdDevicesBtn: HTMLButtonElement | null;
  obdDeviceScanStatus: HTMLElement | null;
  obdDeviceList: HTMLElement | null;
  saveSpeedSourceBtn: HTMLButtonElement | null;
  speedSourceSaveFeedback: HTMLElement | null;
  speedSourceDiagnostics: HTMLDetailsElement | null;
  gpsFallbackPanel: HTMLElement | null;
  staleTimeoutInput: HTMLInputElement | null;
  staleTimeoutFeedback: HTMLElement | null;
  gpsStatusPanel: HTMLElement | null;
  gpsStatusState: HTMLElement | null;
  gpsStatusDevice: HTMLElement | null;
  gpsStatusLastUpdate: HTMLElement | null;
  gpsStatusRawSpeed: HTMLElement | null;
  gpsStatusEffectiveSpeed: HTMLElement | null;
  gpsStatusLastError: HTMLElement | null;
  gpsStatusReconnect: HTMLElement | null;
  gpsStatusFallback: HTMLElement | null;
  obdStatusPanel: HTMLElement | null;
  obdStatusConfiguredDevice: HTMLElement | null;
  obdStatusPairing: HTMLElement | null;
  obdStatusTrusted: HTMLElement | null;
  obdStatusConnected: HTMLElement | null;
  obdStatusRfcommChannel: HTMLElement | null;
  obdStatusLastRpm: HTMLElement | null;
  obdStatusRpmAge: HTMLElement | null;
  obdStatusTargetCadence: HTMLElement | null;
  obdStatusEffectiveCadence: HTMLElement | null;
  obdStatusRequestRtt: HTMLElement | null;
  obdStatusTimeouts: HTMLElement | null;
  obdStatusErrors: HTMLElement | null;
  obdStatusMode: HTMLElement | null;
  obdStatusBackoff: HTMLElement | null;
  obdStatusRawResponse: HTMLElement | null;
  obdStatusDebugHint: HTMLElement | null;
}

export interface SpeedSourcePanelView {
  readonly dom: SettingsSpeedSourcePanelDom;
}

function SpeedSourcePanel() {
  return (
    <>
      <div class="panel card">
        <strong data-i18n="settings.speed.title">Speed Source</strong>
        <div class="subtle" data-i18n="settings.speed.hint">
          Select how vehicle speed is determined. Live sources can fall back to
          the configured manual speed when data goes stale.
        </div>
        <div class="speed-source-summary">
          <div
            class="speed-source-summary__eyebrow"
            data-i18n="settings.speed.summary_title"
          >
            Active right now
          </div>
          <div
            class="subtle speed-source-summary__caption"
            data-i18n="settings.speed.summary_caption"
          >
            This source is currently driving the app. Changes below take effect
            after save.
          </div>
          <div class="speed-source-summary__stats">
            <div class="speed-source-summary__stat">
              <div
                class="speed-source-summary__label"
                data-i18n="settings.speed.current_source"
              >
                Current source
              </div>
              <div
                id="speedSourceCurrentSource"
                class="speed-source-summary__value"
              >
                --
              </div>
            </div>
            <div class="speed-source-summary__stat">
              <div
                class="speed-source-summary__label"
                data-i18n="settings.speed.effective_speed"
              >
                Effective speed
              </div>
              <div
                id="speedSourceEffectiveSpeed"
                class="speed-source-summary__value"
              >
                --
              </div>
            </div>
          </div>
        </div>
        <div class="speed-source-choice-grid">
          <label
            id="speedSourceChoiceGps"
            class="speed-source-choice"
            data-speed-source-choice="gps"
          >
            <input
              class="speed-source-choice__radio"
              type="radio"
              name="speedSourceRadio"
              value="gps"
              checked
            />
            <span
              class="speed-source-choice__title"
              data-i18n="settings.speed.gps"
            >
              GPS
            </span>
            <span
              class="speed-source-choice__caption"
              data-i18n="settings.speed.gps_caption"
            >
              Use live GPS speed when it is healthy and available.
            </span>
          </label>
          <label
            id="speedSourceChoiceObd"
            class="speed-source-choice"
            data-speed-source-choice="obd2"
          >
            <input
              class="speed-source-choice__radio"
              type="radio"
              name="speedSourceRadio"
              value="obd2"
            />
            <span
              class="speed-source-choice__title"
              data-i18n="settings.speed.obd"
            >
              OBD-II
            </span>
            <span
              class="speed-source-choice__caption"
              data-i18n="settings.speed.obd_caption"
            >
              Use a paired Bluetooth OBD adapter on the Pi for live vehicle
              speed and RPM.
            </span>
          </label>
          <label
            id="speedSourceChoiceManual"
            class="speed-source-choice"
            data-speed-source-choice="manual"
          >
            <input
              class="speed-source-choice__radio"
              type="radio"
              name="speedSourceRadio"
              value="manual"
            />
            <span
              class="speed-source-choice__title"
              data-i18n="settings.speed.manual"
            >
              Manual
            </span>
            <span
              class="speed-source-choice__caption"
              data-i18n="settings.speed.manual_caption"
            >
              Use a fixed speed when you need a deliberate override.
            </span>
          </label>
        </div>
        <div id="manualSpeedConfig" class="speed-source-config" hidden>
          <div class="subtle" data-i18n="settings.speed.manual_intro">
            Set a fixed speed for manual mode and as the live-source fallback
            when GPS or OBD-II data goes stale.
          </div>
          <div class="manual-speed-row">
            <label
              htmlFor="manualSpeedInput"
              data-i18n="settings.speed.manual_label"
            >
              Manual Speed (km/h)
            </label>
            <input id="manualSpeedInput" type="number" step="0.1" min="0" />
          </div>
          <div
            id="manualSpeedFeedback"
            class="settings-feedback-slot settings-feedback-slot--compact"
            hidden
          ></div>
        </div>
        <div id="obdSpeedConfig" class="speed-source-config" hidden>
          <div class="subtle" data-i18n="settings.speed.obd_intro">
            Pair a Bluetooth OBD adapter with the Pi, then save OBD-II as the
            selected live source.
          </div>
          <div class="speed-source-obd-toolbar">
            <div class="speed-source-obd-toolbar__summary">
              <div
                class="speed-source-summary__label"
                data-i18n="settings.speed.obd_configured_device"
              >
                Configured adapter
              </div>
              <div id="obdConfiguredDevice" class="speed-source-summary__value">
                --
              </div>
            </div>
            <button
              id="scanObdDevicesBtn"
              class="btn btn--secondary"
              type="button"
              data-i18n="settings.speed.obd_scan"
            >
              Scan for adapters
            </button>
          </div>
          <div
            id="obdDeviceScanStatus"
            class="subtle"
            data-i18n="settings.speed.obd_scan_idle"
          >
            Scan to discover nearby Bluetooth OBD adapters.
          </div>
          <div id="obdDeviceList" class="speed-source-device-list"></div>
        </div>
        <div id="gpsFallbackPanel" class="speed-source-config" hidden>
          <div class="subtle" data-i18n="settings.speed.gps_intro">
            Choose how long stale live-source data can remain usable before the
            manual fallback takes over.
          </div>
          <div class="manual-speed-row">
            <label
              htmlFor="staleTimeoutInput"
              data-i18n="settings.speed.stale_timeout_label"
            >
              Stale timeout (s)
            </label>
            <input
              id="staleTimeoutInput"
              type="number"
              step="1"
              min="3"
              max="120"
              value="10"
            />
          </div>
          <div
            id="staleTimeoutFeedback"
            class="settings-feedback-slot settings-feedback-slot--compact"
            hidden
          ></div>
        </div>
        <div id="speedSourceSaveFeedback" class="settings-feedback-slot" hidden></div>
        <div class="settings-actions">
          <button
            id="saveSpeedSourceBtn"
            class="btn btn--primary"
            data-i18n="settings.speed.save"
          >
            Save Speed Source
          </button>
        </div>
      </div>

      <details
        id="speedSourceDiagnostics"
        class="settings-help-disclosure speed-source-diagnostics"
      >
        <summary class="settings-help-disclosure__summary">
          <span class="settings-help-disclosure__heading">
            <span
              class="settings-help-disclosure__title"
              data-i18n="settings.speed.status_title"
            >
              Live source status
            </span>
            <span
              class="settings-help-disclosure__caption"
              data-i18n="settings.speed.status_caption"
            >
              Connection, freshness, effective speed, fallback diagnostics, and
              Bluetooth OBD detail when configured.
            </span>
          </span>
        </summary>
        <div class="settings-help-disclosure__body">
          <table class="kv-table" id="gpsStatusPanel">
            <tbody>
              <tr>
                <td data-i18n="settings.speed.connection_state">Connection</td>
                <td id="gpsStatusState">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.device">Device</td>
                <td id="gpsStatusDevice">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.last_update">Last update</td>
                <td id="gpsStatusLastUpdate">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.raw_speed">Raw speed</td>
                <td id="gpsStatusRawSpeed">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.effective_speed">
                  Effective speed
                </td>
                <td id="gpsStatusEffectiveSpeed">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.last_error">Last error</td>
                <td id="gpsStatusLastError">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.reconnect_in">Reconnect in</td>
                <td id="gpsStatusReconnect">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.fallback_active">Fallback active</td>
                <td id="gpsStatusFallback">--</td>
              </tr>
            </tbody>
          </table>
          <table class="kv-table" id="obdStatusPanel" hidden>
            <tbody>
              <tr>
                <td data-i18n="settings.speed.obd_configured_device">
                  Configured adapter
                </td>
                <td id="obdStatusConfiguredDevice">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_paired">Paired</td>
                <td id="obdStatusPairing">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_trusted">Trusted</td>
                <td id="obdStatusTrusted">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_connected">
                  Bluetooth connected
                </td>
                <td id="obdStatusConnected">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_rfcomm_channel">
                  RFCOMM channel
                </td>
                <td id="obdStatusRfcommChannel">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_last_rpm">Last RPM</td>
                <td id="obdStatusLastRpm">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_rpm_age">RPM age</td>
                <td id="obdStatusRpmAge">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_target_cadence">
                  Target cadence
                </td>
                <td id="obdStatusTargetCadence">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_effective_cadence">
                  Effective cadence
                </td>
                <td id="obdStatusEffectiveCadence">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_request_rtt">Avg request RTT</td>
                <td id="obdStatusRequestRtt">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_timeouts">Timeouts</td>
                <td id="obdStatusTimeouts">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_errors">Errors</td>
                <td id="obdStatusErrors">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_mode">Monitor mode</td>
                <td id="obdStatusMode">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_backoff_active">
                  Backoff active
                </td>
                <td id="obdStatusBackoff">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_raw_response">
                  Last raw response
                </td>
                <td id="obdStatusRawResponse">--</td>
              </tr>
              <tr>
                <td data-i18n="settings.speed.obd_debug_hint">Debug hint</td>
                <td id="obdStatusDebugHint">--</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

function createSpeedSourcePanelDom(host: HTMLElement): SettingsSpeedSourcePanelDom {
  const queryById = <T extends HTMLElement>(id: string): T | null =>
    host.querySelector<T>(`#${id}`);

  return {
    speedSourceRadios: Array.from(
      host.querySelectorAll<HTMLInputElement>('input[name="speedSourceRadio"]'),
    ),
    speedSourceCurrentSource: queryById<HTMLElement>("speedSourceCurrentSource"),
    speedSourceEffectiveSpeed: queryById<HTMLElement>("speedSourceEffectiveSpeed"),
    speedSourceChoiceGps: queryById<HTMLElement>("speedSourceChoiceGps"),
    speedSourceChoiceObd: queryById<HTMLElement>("speedSourceChoiceObd"),
    speedSourceChoiceManual: queryById<HTMLElement>("speedSourceChoiceManual"),
    manualSpeedConfig: queryById<HTMLElement>("manualSpeedConfig"),
    manualSpeedInput: queryById<HTMLInputElement>("manualSpeedInput"),
    manualSpeedFeedback: queryById<HTMLElement>("manualSpeedFeedback"),
    obdSpeedConfig: queryById<HTMLElement>("obdSpeedConfig"),
    obdConfiguredDevice: queryById<HTMLElement>("obdConfiguredDevice"),
    scanObdDevicesBtn: queryById<HTMLButtonElement>("scanObdDevicesBtn"),
    obdDeviceScanStatus: queryById<HTMLElement>("obdDeviceScanStatus"),
    obdDeviceList: queryById<HTMLElement>("obdDeviceList"),
    saveSpeedSourceBtn: queryById<HTMLButtonElement>("saveSpeedSourceBtn"),
    speedSourceSaveFeedback: queryById<HTMLElement>("speedSourceSaveFeedback"),
    speedSourceDiagnostics: queryById<HTMLDetailsElement>("speedSourceDiagnostics"),
    gpsFallbackPanel: queryById<HTMLElement>("gpsFallbackPanel"),
    staleTimeoutInput: queryById<HTMLInputElement>("staleTimeoutInput"),
    staleTimeoutFeedback: queryById<HTMLElement>("staleTimeoutFeedback"),
    gpsStatusPanel: queryById<HTMLElement>("gpsStatusPanel"),
    gpsStatusState: queryById<HTMLElement>("gpsStatusState"),
    gpsStatusDevice: queryById<HTMLElement>("gpsStatusDevice"),
    gpsStatusLastUpdate: queryById<HTMLElement>("gpsStatusLastUpdate"),
    gpsStatusRawSpeed: queryById<HTMLElement>("gpsStatusRawSpeed"),
    gpsStatusEffectiveSpeed: queryById<HTMLElement>("gpsStatusEffectiveSpeed"),
    gpsStatusLastError: queryById<HTMLElement>("gpsStatusLastError"),
    gpsStatusReconnect: queryById<HTMLElement>("gpsStatusReconnect"),
    gpsStatusFallback: queryById<HTMLElement>("gpsStatusFallback"),
    obdStatusPanel: queryById<HTMLElement>("obdStatusPanel"),
    obdStatusConfiguredDevice: queryById<HTMLElement>("obdStatusConfiguredDevice"),
    obdStatusPairing: queryById<HTMLElement>("obdStatusPairing"),
    obdStatusTrusted: queryById<HTMLElement>("obdStatusTrusted"),
    obdStatusConnected: queryById<HTMLElement>("obdStatusConnected"),
    obdStatusRfcommChannel: queryById<HTMLElement>("obdStatusRfcommChannel"),
    obdStatusLastRpm: queryById<HTMLElement>("obdStatusLastRpm"),
    obdStatusRpmAge: queryById<HTMLElement>("obdStatusRpmAge"),
    obdStatusTargetCadence: queryById<HTMLElement>("obdStatusTargetCadence"),
    obdStatusEffectiveCadence: queryById<HTMLElement>("obdStatusEffectiveCadence"),
    obdStatusRequestRtt: queryById<HTMLElement>("obdStatusRequestRtt"),
    obdStatusTimeouts: queryById<HTMLElement>("obdStatusTimeouts"),
    obdStatusErrors: queryById<HTMLElement>("obdStatusErrors"),
    obdStatusMode: queryById<HTMLElement>("obdStatusMode"),
    obdStatusBackoff: queryById<HTMLElement>("obdStatusBackoff"),
    obdStatusRawResponse: queryById<HTMLElement>("obdStatusRawResponse"),
    obdStatusDebugHint: queryById<HTMLElement>("obdStatusDebugHint"),
  };
}

export function mountSpeedSourcePanel(host: HTMLElement): SpeedSourcePanelView {
  createUiPreactMount(host).render(<SpeedSourcePanel />);
  return {
    dom: createSpeedSourcePanelDom(host),
  };
}
