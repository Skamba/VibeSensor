import type {
  ObdDevicePayload,
  ObdStatusPayload,
  SpeedSourceStatusPayload,
} from "../../api/types";
import {
  deriveDisplayedSpeedSourceMode,
  isManualLikeSpeedSource,
  resolveEffectiveSpeedSource,
  type DisplayedSpeedSourceMode,
  type SpeedSourceStateSnapshot,
} from "../speed_source_state";
import type {
  SpeedSourceChoiceCardRenderModel,
  SpeedSourceDiagnosticsRenderModel,
  SpeedSourceObdDeviceBadgeRenderModel,
  SpeedSourceObdDeviceRenderModel,
  SpeedSourcePanelRenderModel,
} from "./speed_source_panel";
import type { SettingsFeedbackMessage } from "./settings_feedback";

export interface SettingsSpeedSourceSettingsSnapshot
  extends SpeedSourceStateSnapshot {
  gpsFallbackActive: boolean;
  gpsEffectiveSpeedKph: number | null;
  obdDeviceMac: string | null;
  obdDeviceName: string | null;
}

export interface SettingsSpeedSourceRenderState {
  diagnosticsOpen: boolean;
  draftDirty: boolean;
  manualSpeedFeedback: SettingsFeedbackMessage | null;
  manualSpeedInputValue: string;
  obdScanStatusMessage: string | null;
  obdSelectionError: boolean;
  pairInFlightMac: string | null;
  saveFeedback: SettingsFeedbackMessage | null;
  scannedDevices: readonly ObdDevicePayload[];
  scanInFlight: boolean;
  selectedMode: DisplayedSpeedSourceMode;
  settings: SettingsSpeedSourceSettingsSnapshot;
  staleTimeoutFeedback: SettingsFeedbackMessage | null;
  staleTimeoutInputValue: string;
}

export interface SettingsSpeedSourcePresenterDeps {
  fmt: (value: number, digits?: number) => string;
  getSpeedUnit: () => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

const CONNECTION_STATE_I18N: Record<string, string> = {
  connected: "settings.speed.state_connected",
  disabled: "settings.speed.state_disabled",
  disconnected: "settings.speed.state_disconnected",
  stale: "settings.speed.state_stale",
};

const OBD_POLL_MODE_I18N: Record<string, string> = {
  rpm_only: "settings.speed.obd_mode_rpm_only",
  rpm_only_backoff: "settings.speed.obd_mode_rpm_only_backoff",
  rpm_priority: "settings.speed.obd_mode_rpm_priority",
  rpm_priority_backoff: "settings.speed.obd_mode_rpm_priority_backoff",
};

function selectedSpeedUnitLabel(
  deps: Pick<SettingsSpeedSourcePresenterDeps, "getSpeedUnit" | "t">,
): string {
  return deps.getSpeedUnit() === "mps"
    ? deps.t("speed.unit.mps")
    : deps.t("speed.unit.kmh");
}

function speedKphInSelectedUnit(
  speedKmh: number | null,
  deps: Pick<SettingsSpeedSourcePresenterDeps, "getSpeedUnit">,
): number | null {
  if (speedKmh === null || !Number.isFinite(speedKmh)) {
    return null;
  }
  return deps.getSpeedUnit() === "mps" ? speedKmh / 3.6 : speedKmh;
}

function formatSpeedValue(
  speedKmh: number | null,
  deps: Pick<SettingsSpeedSourcePresenterDeps, "fmt" | "getSpeedUnit" | "t">,
): string {
  const speed = speedKphInSelectedUnit(speedKmh, deps);
  return speed != null
    ? `${deps.fmt(speed, 1)} ${selectedSpeedUnitLabel(deps)}`
    : "--";
}

function formatConfiguredObdDevice(
  settings: Pick<
    SettingsSpeedSourceSettingsSnapshot,
    "obdDeviceMac" | "obdDeviceName"
  >,
  t: SettingsSpeedSourcePresenterDeps["t"],
): string {
  if (settings.obdDeviceName && settings.obdDeviceMac) {
    return `${settings.obdDeviceName} (${settings.obdDeviceMac})`;
  }
  return (
    settings.obdDeviceName ??
    settings.obdDeviceMac ??
    t("settings.speed.obd_not_configured")
  );
}

function activeSourceLabel(
  settings: SettingsSpeedSourceRenderState["settings"],
  t: SettingsSpeedSourcePresenterDeps["t"],
): string {
  const effectiveSource = resolveEffectiveSpeedSource(settings);
  if (effectiveSource === "fallback_manual") {
    return t("settings.speed.current_source_fallback_manual");
  }
  if (effectiveSource === "manual") {
    return t("settings.speed.current_source_manual_override");
  }
  if (effectiveSource === "gps" || effectiveSource == null) {
    return t("settings.speed.gps");
  }
  if (effectiveSource === "obd2") {
    return t("dashboard.rotational.source.obd2");
  }
  return effectiveSource;
}

function activeEffectiveSpeedKph(
  settings: SettingsSpeedSourceRenderState["settings"],
): number | null {
  return isManualLikeSpeedSource(resolveEffectiveSpeedSource(settings))
    ? settings.manualSpeedKph
    : settings.gpsEffectiveSpeedKph;
}

function buildChoiceState(
  t: SettingsSpeedSourcePresenterDeps["t"],
  {
    active,
    pending,
    error,
  }: { active: boolean; pending: boolean; error: boolean },
): SpeedSourceChoiceCardRenderModel {
  return {
    badgeText: pending
      ? t("settings.speed.choice_pending")
      : active
        ? t("settings.speed.choice_active")
        : null,
    selected: active,
    state: error ? "error" : pending ? "draft" : active ? "active" : null,
  };
}

function looksLikeMacAlias(rawValue: string | null | undefined): boolean {
  const value = rawValue?.trim();
  return value != null && /^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(value);
}

function hasHumanReadableDeviceName(device: ObdDevicePayload): boolean {
  const value = device.name?.trim();
  return Boolean(value) && !looksLikeMacAlias(value);
}

function obdDevicePrimaryLabel(device: ObdDevicePayload): string {
  return device.name?.trim() || device.mac_address;
}

function obdDeviceSecondaryLabel(device: ObdDevicePayload): string | null {
  return hasHumanReadableDeviceName(device) ? device.mac_address : null;
}

function createBadge(
  labelText: string,
  active = false,
): SpeedSourceObdDeviceBadgeRenderModel {
  return {
    active,
    labelText,
  };
}

function buildObdDeviceModel(
  device: ObdDevicePayload,
  state: SettingsSpeedSourceRenderState,
  t: SettingsSpeedSourcePresenterDeps["t"],
): SpeedSourceObdDeviceRenderModel {
  const badges: SpeedSourceObdDeviceBadgeRenderModel[] = [];
  if (device.mac_address === state.settings.obdDeviceMac) {
    badges.push(createBadge(t("settings.speed.obd_configured_badge"), true));
  }
  if (device.paired) {
    badges.push(createBadge(t("settings.speed.obd_paired_badge")));
  }
  if (device.trusted) {
    badges.push(createBadge(t("settings.speed.obd_trusted_badge")));
  }
  if (device.connected) {
    badges.push(createBadge(t("settings.speed.obd_connected_badge"), true));
  }

  const actionLabel =
    state.pairInFlightMac === device.mac_address
      ? t("settings.speed.obd_pairing")
      : device.paired && device.trusted
        ? t("settings.speed.obd_use")
        : t("settings.speed.obd_pair_and_use");
  const secondaryLabel = obdDeviceSecondaryLabel(device);

  return {
    actionDisabled: state.scanInFlight || state.pairInFlightMac !== null,
    actionLabelText: actionLabel,
    badges,
    macAddress: device.mac_address,
    primaryText: obdDevicePrimaryLabel(device),
    secondaryText: secondaryLabel,
  };
}

function connectionStateLabel(
  connectionState: string,
  t: SettingsSpeedSourcePresenterDeps["t"],
): string {
  const key = CONNECTION_STATE_I18N[connectionState];
  return key ? t(key) : connectionState;
}

function boolLabel(
  value: boolean,
  t: SettingsSpeedSourcePresenterDeps["t"],
): string {
  return value
    ? t("settings.speed.fallback_yes")
    : t("settings.speed.fallback_no");
}

function formatAgeSeconds(
  ageSeconds: number | null,
  t: SettingsSpeedSourcePresenterDeps["t"],
): string | null {
  return ageSeconds != null
    ? t("settings.speed.last_update_value", {
        value: {
          number: ageSeconds,
          options: { minimumFractionDigits: 1, maximumFractionDigits: 1 },
        },
      })
    : null;
}

function formatCadenceFromTarget(
  intervalMs: number | null,
  deps: SettingsSpeedSourcePresenterDeps,
): string | null {
  if (intervalMs == null || intervalMs <= 0) {
    return null;
  }
  return `${deps.fmt(1000 / intervalMs, 1)} Hz (${deps.fmt(intervalMs, 0)} ms)`;
}

function formatCadenceHz(
  hz: number | null,
  deps: SettingsSpeedSourcePresenterDeps,
): string | null {
  return hz != null ? `${deps.fmt(hz, 1)} Hz` : null;
}

function formatMilliseconds(
  ms: number | null,
  deps: SettingsSpeedSourcePresenterDeps,
): string | null {
  return ms != null ? `${deps.fmt(ms, 0)} ms` : null;
}

function obdPollModeLabel(
  mode: string | null,
  t: SettingsSpeedSourcePresenterDeps["t"],
): string | null {
  if (mode == null) {
    return null;
  }
  const key = OBD_POLL_MODE_I18N[mode];
  return key ? t(key) : mode;
}

export function buildSettingsSpeedSourcePanelModel(
  state: SettingsSpeedSourceRenderState,
  deps: SettingsSpeedSourcePresenterDeps,
): SpeedSourcePanelRenderModel {
  const displayedMode = deriveDisplayedSpeedSourceMode(state.settings);
  const hasPendingSelection =
    state.draftDirty && state.selectedMode !== displayedMode;

  return {
    choiceCards: {
      gps: buildChoiceState(deps.t, {
        active: displayedMode === "gps",
        pending: hasPendingSelection && state.selectedMode === "gps",
        error: false,
      }),
      manual: buildChoiceState(deps.t, {
        active: displayedMode === "manual",
        pending: hasPendingSelection && state.selectedMode === "manual",
        error: false,
      }),
      obd2: buildChoiceState(deps.t, {
        active: displayedMode === "obd2",
        pending: hasPendingSelection && state.selectedMode === "obd2",
        error: state.obdSelectionError,
      }),
    },
    diagnosticsShouldOpen:
      state.diagnosticsOpen
      || resolveEffectiveSpeedSource(state.settings) !== state.settings.speedSource,
    manualConfigVisible: state.selectedMode === "manual",
    manualSpeedFeedback: state.manualSpeedFeedback,
    manualSpeedInputValue: state.manualSpeedInputValue,
    obdConfigVisible: state.selectedMode === "obd2",
    obdConfiguredDeviceText: formatConfiguredObdDevice(state.settings, deps.t),
    obdDevices: state.scannedDevices.map((device) =>
      buildObdDeviceModel(device, state, deps.t)
    ),
    obdScanStatusText:
      state.obdScanStatusMessage ?? deps.t("settings.speed.obd_scan_idle"),
    obdSelectionInvalid: state.obdSelectionError,
    scanObdDevicesDisabled:
      state.scanInFlight || state.pairInFlightMac !== null,
    saveFeedback: state.saveFeedback,
    selectedMode: state.selectedMode,
    showGpsFallbackPanel: state.selectedMode !== "manual",
    staleTimeoutFeedback: state.staleTimeoutFeedback,
    staleTimeoutInputValue: state.staleTimeoutInputValue,
    summary: {
      currentSourceText: activeSourceLabel(state.settings, deps.t),
      effectiveSpeedText: formatSpeedValue(
        activeEffectiveSpeedKph(state.settings),
        deps,
      ),
      fallbackActiveText: boolLabel(state.settings.gpsFallbackActive, deps.t),
    },
  };
}

export function buildSpeedSourceDiagnosticsRenderModel(
  status: SpeedSourceStatusPayload,
  obdStatus: ObdStatusPayload | null,
  deps: SettingsSpeedSourcePresenterDeps,
): SpeedSourceDiagnosticsRenderModel {
  return {
    gps: {
      deviceText: status.device ?? "--",
      effectiveSpeedText: formatSpeedValue(status.effective_speed_kmh, deps),
      fallbackText: boolLabel(status.fallback_active, deps.t),
      lastErrorText: status.last_error ?? "--",
      lastUpdateText:
        formatAgeSeconds(status.last_update_age_s, deps.t)
        ?? deps.t("settings.speed.last_update_never"),
      rawSpeedText: formatSpeedValue(status.raw_speed_kmh, deps),
      reconnectText:
        status.reconnect_delay_s != null
          ? `${deps.fmt(status.reconnect_delay_s, 1)}s`
          : "--",
      stateText: connectionStateLabel(status.connection_state, deps.t),
    },
    obd: obdStatus
      ? {
          backoffText: boolLabel(obdStatus.backoff_active, deps.t),
          configuredDeviceText: formatConfiguredObdDevice(
            {
              obdDeviceMac: obdStatus.configured_device_mac ?? null,
              obdDeviceName: obdStatus.configured_device_name ?? null,
            },
            deps.t,
          ),
          connectedText: boolLabel(obdStatus.connected, deps.t),
          debugHintText: obdStatus.debug_hint ?? "--",
          effectiveCadenceText:
            formatCadenceHz(obdStatus.rpm_effective_hz, deps) ?? "--",
          errorsText: String(obdStatus.error_count),
          lastRpmText:
            obdStatus.last_rpm != null ? deps.fmt(obdStatus.last_rpm, 0) : "--",
          modeText: obdPollModeLabel(obdStatus.poll_mode, deps.t) ?? "--",
          pairingText: boolLabel(obdStatus.paired, deps.t),
          rawResponseText: obdStatus.last_raw_response ?? "--",
          requestRttText:
            formatMilliseconds(obdStatus.request_rtt_ms, deps) ?? "--",
          rfcommChannelText:
            obdStatus.rfcomm_channel != null
              ? String(obdStatus.rfcomm_channel)
              : "--",
          rpmAgeText:
            formatAgeSeconds(obdStatus.rpm_sample_age_s, deps.t) ?? "--",
          targetCadenceText:
            formatCadenceFromTarget(obdStatus.rpm_target_interval_ms, deps)
            ?? "--",
          timeoutsText: String(obdStatus.timeout_count),
          trustedText: boolLabel(obdStatus.trusted, deps.t),
          visible: true,
        }
      : {
          backoffText: "--",
          configuredDeviceText: "--",
          connectedText: "--",
          debugHintText: "--",
          effectiveCadenceText: "--",
          errorsText: "--",
          lastRpmText: "--",
          modeText: "--",
          pairingText: "--",
          rawResponseText: "--",
          requestRttText: "--",
          rfcommChannelText: "--",
          rpmAgeText: "--",
          targetCadenceText: "--",
          timeoutsText: "--",
          trustedText: "--",
          visible: false,
        },
  };
}
