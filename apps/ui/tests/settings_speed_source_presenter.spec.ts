import { expect, test } from "vitest";
import type {
  ObdDevicePayload,
  ObdStatusPayload,
  SpeedSourceStatusPayload,
} from "../src/api/types";
import {
  buildSettingsSpeedSourcePanelModel,
  buildSpeedSourceDiagnosticsRenderModel,
  type SettingsSpeedSourcePresenterDeps,
  type SettingsSpeedSourceRenderState,
} from "../src/app/views/settings_speed_source_presenter";

function createPresenterDeps(
  speedUnit: "kmh" | "mps" = "kmh",
): SettingsSpeedSourcePresenterDeps {
  return {
    fmt(value, digits = 0) {
      return Number(value).toFixed(digits);
    },
    getSpeedUnit() {
      return speedUnit;
    },
    t(key, vars) {
      switch (key) {
        case "dashboard.rotational.source.obd2":
          return "OBD2";
        case "settings.speed.choice_active":
          return "Active";
        case "settings.speed.choice_pending":
          return "Pending save";
        case "settings.speed.current_source_fallback_manual":
          return "Manual fallback";
        case "settings.speed.current_source_manual_override":
          return "Manual override";
        case "settings.speed.fallback_no":
          return "No";
        case "settings.speed.fallback_yes":
          return "Yes";
        case "settings.speed.gps":
          return "GPS";
        case "settings.speed.last_update_never":
          return "Never";
        case "settings.speed.last_update_value":
          return `${Number(
            (vars?.value as { number: number } | undefined)?.number ?? 0,
          ).toFixed(1)}s ago`;
        case "settings.speed.obd_configured_badge":
          return "Configured";
        case "settings.speed.obd_connected_badge":
          return "Connected";
        case "settings.speed.obd_not_configured":
          return "Not configured";
        case "settings.speed.obd_pair_and_use":
          return "Pair and use";
        case "settings.speed.obd_pairing":
          return "Pairing adapter...";
        case "settings.speed.obd_paired_badge":
          return "Paired";
        case "settings.speed.obd_scan_idle":
          return "Scan to discover nearby Bluetooth OBD adapters.";
        case "settings.speed.obd_trusted_badge":
          return "Trusted";
        case "settings.speed.obd_use":
          return "Use adapter";
        case "settings.speed.obd_mode_rpm_only_backoff":
          return "RPM priority only (backed off)";
        case "settings.speed.state_connected":
          return "Connected";
        case "speed.unit.kmh":
          return "km/h";
        case "speed.unit.mps":
          return "m/s";
        default:
          return key;
      }
    },
  };
}

function makeObdDevice(
  overrides: Partial<ObdDevicePayload> = {},
): ObdDevicePayload {
  return {
    connected: false,
    mac_address: "00:22:d9:00:1b:b1",
    name: "OBDLink CX",
    paired: false,
    rfcomm_channel: null,
    trusted: false,
    ...overrides,
  };
}

function makeRenderState(
  overrides: Partial<SettingsSpeedSourceRenderState> = {},
): SettingsSpeedSourceRenderState {
  return {
    diagnosticsOpen: false,
    draftDirty: false,
    manualSpeedFeedback: null,
    manualSpeedInputValue: "",
    obdScanStatusMessage: null,
    obdSelectionError: false,
    pairInFlightMac: null,
    saveFeedback: null,
    scannedDevices: [],
    scanInFlight: false,
    selectedMode: "gps",
    settings: {
      gpsFallbackActive: false,
      gpsEffectiveSpeedKph: 72,
      manualSpeedKph: null,
      obdDeviceMac: null,
      obdDeviceName: null,
      resolvedSpeedSource: "gps",
      speedSource: "gps",
    },
    staleTimeoutFeedback: null,
    staleTimeoutInputValue: "5",
    ...overrides,
  };
}

test("speed-source panel model keeps the active GPS card while a manual draft is pending save", () => {
  const state = makeRenderState({
    diagnosticsOpen: true,
    draftDirty: true,
    manualSpeedFeedback: {
      body: "Enter a manual speed between 0.1 and 500 km/h.",
      compact: true,
      tone: "error",
    },
    manualSpeedInputValue: "45",
    saveFeedback: {
      body: "GPS remains active right now. No changes were saved.",
      title: "Save failed",
      tone: "error",
    },
    selectedMode: "manual",
  });

  const model = buildSettingsSpeedSourcePanelModel(
    state,
    createPresenterDeps(),
  );

  expect(model.selectedMode).toBe("manual");
  expect(model.choiceCards.gps).toEqual({
    badgeText: "Active",
    selected: true,
    state: "active",
  });
  expect(model.choiceCards.manual).toEqual({
    badgeText: "Pending save",
    selected: false,
    state: "draft",
  });
  expect(model.manualConfigVisible).toBe(true);
  expect(model.showGpsFallbackPanel).toBe(false);
  expect(model.diagnosticsShouldOpen).toBe(true);
  expect(model.summary).toEqual({
    currentSourceText: "GPS",
    effectiveSpeedText: "72.0 km/h",
    fallbackActiveText: "No",
  });
  expect(model.manualSpeedFeedback?.body).toBe(
    "Enter a manual speed between 0.1 and 500 km/h.",
  );
});

test("speed-source presenter builds OBD device rows and diagnostics render models", () => {
  const configuredDevice = makeObdDevice({
    connected: true,
    paired: true,
    trusted: true,
  });
  const aliasOnlyDevice = makeObdDevice({
    mac_address: "53:40:ac:57:11:77",
    name: "53-40-AC-57-11-77",
  });

  const panelModel = buildSettingsSpeedSourcePanelModel(
    makeRenderState({
      obdScanStatusMessage: "2 adapter(s) found.",
      scannedDevices: [configuredDevice, aliasOnlyDevice],
      selectedMode: "obd2",
      settings: {
        gpsFallbackActive: false,
        gpsEffectiveSpeedKph: 81,
        manualSpeedKph: null,
        obdDeviceMac: configuredDevice.mac_address,
        obdDeviceName: configuredDevice.name,
        resolvedSpeedSource: "obd2",
        speedSource: "obd2",
      },
    }),
    createPresenterDeps(),
  );

  expect(panelModel.obdConfiguredDeviceText).toBe(
    "OBDLink CX (00:22:d9:00:1b:b1)",
  );
  expect(panelModel.obdDevices[0]).toEqual({
    actionDisabled: false,
    actionLabelText: "Use adapter",
    badges: [
      { active: true, labelText: "Configured" },
      { active: false, labelText: "Paired" },
      { active: false, labelText: "Trusted" },
      { active: true, labelText: "Connected" },
    ],
    macAddress: "00:22:d9:00:1b:b1",
    primaryText: "OBDLink CX",
    secondaryText: "00:22:d9:00:1b:b1",
  });
  expect(panelModel.obdDevices[1].secondaryText).toBeNull();

  const speedStatus: SpeedSourceStatusPayload = {
    connection_state: "connected",
    device: "gpsd",
    effective_speed_kmh: 45,
    fallback_active: true,
    gps_enabled: true,
    last_error: null,
    last_update_age_s: 0.3,
    raw_speed_kmh: 36,
    reconnect_delay_s: 1.5,
    speed_source: "obd2",
  };
  const obdStatus: ObdStatusPayload = {
    backoff_active: true,
    configured_device_mac: configuredDevice.mac_address,
    configured_device_name: configuredDevice.name,
    connected: true,
    debug_hint: "Check power",
    error_count: 2,
    last_raw_response: "41 0C 1B 58",
    last_rpm: 2200,
    paired: true,
    poll_mode: "rpm_only_backoff",
    request_rtt_ms: 61.4,
    rfcomm_channel: 1,
    rpm_effective_hz: 13.3,
    rpm_sample_age_s: 0.1,
    rpm_target_interval_ms: 75,
    timeout_count: 1,
    trusted: true,
  };

  const diagnostics = buildSpeedSourceDiagnosticsRenderModel(
    speedStatus,
    obdStatus,
    createPresenterDeps("mps"),
  );

  expect(diagnostics.gps).toMatchObject({
    deviceText: "gpsd",
    effectiveSpeedText: "12.5 m/s",
    fallbackText: "Yes",
    lastUpdateText: "0.3s ago",
    rawSpeedText: "10.0 m/s",
    reconnectText: "1.5s",
    stateText: "Connected",
  });
  expect(diagnostics.obd).toMatchObject({
    backoffText: "Yes",
    configuredDeviceText: "OBDLink CX (00:22:d9:00:1b:b1)",
    effectiveCadenceText: "13.3 Hz",
    modeText: "RPM priority only (backed off)",
    requestRttText: "61 ms",
    targetCadenceText: "13.3 Hz (75 ms)",
    visible: true,
  });
});
