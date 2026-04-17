import { getUiText as t } from "../ui_i18n";
import type {
  SpeedSourceDiagnosticsRenderModel,
  SpeedSourceGpsStatusRenderModel,
  SpeedSourceObdStatusRenderModel,
} from "./speed_source_panel";

const GPS_STATUS_ROWS = [
  {
    fallbackLabel: "Connection",
    id: "gpsStatusState",
    labelKey: "settings.speed.connection_state",
    valueKey: "stateText",
  },
  {
    fallbackLabel: "Device",
    id: "gpsStatusDevice",
    labelKey: "settings.speed.device",
    valueKey: "deviceText",
  },
  {
    fallbackLabel: "Last update",
    id: "gpsStatusLastUpdate",
    labelKey: "settings.speed.last_update",
    valueKey: "lastUpdateText",
  },
  {
    fallbackLabel: "Raw speed",
    id: "gpsStatusRawSpeed",
    labelKey: "settings.speed.raw_speed",
    valueKey: "rawSpeedText",
  },
  {
    fallbackLabel: "Effective speed",
    id: "gpsStatusEffectiveSpeed",
    labelKey: "settings.speed.effective_speed",
    valueKey: "effectiveSpeedText",
  },
  {
    fallbackLabel: "Last error",
    id: "gpsStatusLastError",
    labelKey: "settings.speed.last_error",
    valueKey: "lastErrorText",
  },
  {
    fallbackLabel: "Reconnect in",
    id: "gpsStatusReconnect",
    labelKey: "settings.speed.reconnect_in",
    valueKey: "reconnectText",
  },
  {
    fallbackLabel: "Fallback active",
    id: "gpsStatusFallback",
    labelKey: "settings.speed.fallback_active",
    valueKey: "fallbackText",
  },
] as const satisfies readonly {
  fallbackLabel: string;
  id: string;
  labelKey: string;
  valueKey: keyof SpeedSourceGpsStatusRenderModel;
}[];

const OBD_STATUS_ROWS = [
  {
    fallbackLabel: "Configured adapter",
    id: "obdStatusConfiguredDevice",
    labelKey: "settings.speed.obd_configured_device",
    valueKey: "configuredDeviceText",
  },
  {
    fallbackLabel: "Paired",
    id: "obdStatusPairing",
    labelKey: "settings.speed.obd_paired",
    valueKey: "pairingText",
  },
  {
    fallbackLabel: "Trusted",
    id: "obdStatusTrusted",
    labelKey: "settings.speed.obd_trusted",
    valueKey: "trustedText",
  },
  {
    fallbackLabel: "Bluetooth connected",
    id: "obdStatusConnected",
    labelKey: "settings.speed.obd_connected",
    valueKey: "connectedText",
  },
  {
    fallbackLabel: "RFCOMM channel",
    id: "obdStatusRfcommChannel",
    labelKey: "settings.speed.obd_rfcomm_channel",
    valueKey: "rfcommChannelText",
  },
  {
    fallbackLabel: "Last RPM",
    id: "obdStatusLastRpm",
    labelKey: "settings.speed.obd_last_rpm",
    valueKey: "lastRpmText",
  },
  {
    fallbackLabel: "RPM age",
    id: "obdStatusRpmAge",
    labelKey: "settings.speed.obd_rpm_age",
    valueKey: "rpmAgeText",
  },
  {
    fallbackLabel: "Target cadence",
    id: "obdStatusTargetCadence",
    labelKey: "settings.speed.obd_target_cadence",
    valueKey: "targetCadenceText",
  },
  {
    fallbackLabel: "Effective cadence",
    id: "obdStatusEffectiveCadence",
    labelKey: "settings.speed.obd_effective_cadence",
    valueKey: "effectiveCadenceText",
  },
  {
    fallbackLabel: "Avg request RTT",
    id: "obdStatusRequestRtt",
    labelKey: "settings.speed.obd_request_rtt",
    valueKey: "requestRttText",
  },
  {
    fallbackLabel: "Timeouts",
    id: "obdStatusTimeouts",
    labelKey: "settings.speed.obd_timeouts",
    valueKey: "timeoutsText",
  },
  {
    fallbackLabel: "Errors",
    id: "obdStatusErrors",
    labelKey: "settings.speed.obd_errors",
    valueKey: "errorsText",
  },
  {
    fallbackLabel: "Monitor mode",
    id: "obdStatusMode",
    labelKey: "settings.speed.obd_mode",
    valueKey: "modeText",
  },
  {
    fallbackLabel: "Backoff active",
    id: "obdStatusBackoff",
    labelKey: "settings.speed.obd_backoff_active",
    valueKey: "backoffText",
  },
  {
    fallbackLabel: "Last raw response",
    id: "obdStatusRawResponse",
    labelKey: "settings.speed.obd_raw_response",
    valueKey: "rawResponseText",
  },
  {
    fallbackLabel: "Debug hint",
    id: "obdStatusDebugHint",
    labelKey: "settings.speed.obd_debug_hint",
    valueKey: "debugHintText",
  },
] as const satisfies readonly {
  fallbackLabel: string;
  id: string;
  labelKey: string;
  valueKey: Exclude<keyof SpeedSourceObdStatusRenderModel, "visible">;
}[];

export function SpeedSourceDiagnosticsPanel(props: {
  diagnostics: SpeedSourceDiagnosticsRenderModel;
  diagnosticsDisclosureOpen: boolean;
  onDiagnosticsToggle: (event: Event) => void;
}) {
  const { diagnostics, diagnosticsDisclosureOpen, onDiagnosticsToggle } = props;
  return (
    <details
      id="speedSourceDiagnostics"
      class="settings-help-disclosure speed-source-diagnostics"
      open={diagnosticsDisclosureOpen}
      onToggle={onDiagnosticsToggle}
    >
      <summary class="settings-help-disclosure__summary">
        <span class="settings-help-disclosure__heading">
          <span class="settings-help-disclosure__title">
            {t("settings.speed.status_title", "Live source status")}
          </span>
          <span class="settings-help-disclosure__caption">
            {t(
              "settings.speed.status_caption",
              "Connection, freshness, effective speed, fallback diagnostics, and Bluetooth OBD detail when configured.",
            )}
          </span>
        </span>
      </summary>
      <div class="settings-help-disclosure__body">
        <table class="kv-table" id="gpsStatusPanel">
          <tbody>
            {GPS_STATUS_ROWS.map((row) => (
              <tr key={row.id}>
                <td>{t(row.labelKey, row.fallbackLabel)}</td>
                <td id={row.id}>{diagnostics.gps[row.valueKey]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table
          class="kv-table"
          id="obdStatusPanel"
          hidden={!diagnostics.obd.visible}
        >
          <tbody>
            {OBD_STATUS_ROWS.map((row) => (
              <tr key={row.id}>
                <td>{t(row.labelKey, row.fallbackLabel)}</td>
                <td id={row.id}>{diagnostics.obd[row.valueKey]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
