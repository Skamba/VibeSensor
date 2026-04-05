import type { ObdStatusPayload, SpeedSourceStatusPayload } from "../../transport/http_models";
import { getSettingsObdStatus, getSpeedSourceStatus } from "../../api";
import {
  GPS_POLL_FAST_MS,
  GPS_POLL_SLOW_MS,
} from "../../config";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";
import { createPollingController } from "./polling_controller";

const CONNECTION_STATE_I18N: Record<string, string> = {
  disabled: "settings.speed.state_disabled",
  disconnected: "settings.speed.state_disconnected",
  connected: "settings.speed.state_connected",
  stale: "settings.speed.state_stale",
};

const OBD_POLL_MODE_I18N: Record<string, string> = {
  rpm_priority: "settings.speed.obd_mode_rpm_priority",
  rpm_priority_backoff: "settings.speed.obd_mode_rpm_priority_backoff",
  rpm_only: "settings.speed.obd_mode_rpm_only",
  rpm_only_backoff: "settings.speed.obd_mode_rpm_only_backoff",
};

export interface SettingsGpsStatusModuleDeps extends FeatureDepsBase {
  dom: UiSettingsDom;
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  syncSpeedSourceSelectionUi: () => void;
  renderSpeedReadout: () => void;
}

export interface SettingsGpsStatusModule {
  startGpsStatusPolling(): void;
  stopGpsStatusPolling(): void;
}

export function createSettingsGpsStatusModule(ctx: SettingsGpsStatusModuleDeps): SettingsGpsStatusModule {
  const { settings, dom: els, t, fmt } = ctx;

  function connectionStateLabel(connectionState: string): string {
    const key = CONNECTION_STATE_I18N[connectionState];
    return key ? t(key) : connectionState;
  }

  function speedKmhInSelectedUnit(speedKmh: number | null): number | null {
    if (speedKmh === null || !Number.isFinite(speedKmh)) return null;
    return ctx.getSpeedUnit() === "mps" ? speedKmh / 3.6 : speedKmh;
  }

  function selectedSpeedUnitLabel(): string {
    return ctx.getSpeedUnit() === "mps" ? t("speed.unit.mps") : t("speed.unit.kmh");
  }

  function formatSpeedValue(speedKmh: number | null, unitLabel: string): string | null {
    const speed = speedKmhInSelectedUnit(speedKmh);
    return speed != null ? `${fmt(speed, 1)} ${unitLabel}` : null;
  }

  function boolLabel(value: boolean): string {
    return value ? t("settings.speed.fallback_yes") : t("settings.speed.fallback_no");
  }

  function formatAgeSeconds(ageSeconds: number | null): string | null {
    return ageSeconds != null
      ? t("settings.speed.last_update_value", {
        value: {
          number: ageSeconds,
          options: { minimumFractionDigits: 1, maximumFractionDigits: 1 },
        },
      })
      : null;
  }

  function formatCadenceFromTarget(intervalMs: number | null): string | null {
    if (intervalMs == null || intervalMs <= 0) return null;
    return `${fmt(1000 / intervalMs, 1)} Hz (${fmt(intervalMs, 0)} ms)`;
  }

  function formatCadenceHz(hz: number | null): string | null {
    return hz != null ? `${fmt(hz, 1)} Hz` : null;
  }

  function formatMilliseconds(ms: number | null): string | null {
    return ms != null ? `${fmt(ms, 0)} ms` : null;
  }

  function obdPollModeLabel(mode: string | null): string | null {
    if (mode == null) return null;
    const key = OBD_POLL_MODE_I18N[mode];
    return key ? t(key) : mode;
  }

  function renderGpsStatus(status: SpeedSourceStatusPayload): void {
    const unitLabel = selectedSpeedUnitLabel();
    if (els.gpsStatusState) els.gpsStatusState.textContent = connectionStateLabel(status.connection_state);
    if (els.gpsStatusDevice) els.gpsStatusDevice.textContent = status.device ?? "--";
    if (els.gpsStatusLastUpdate) {
      els.gpsStatusLastUpdate.textContent = status.last_update_age_s != null
        ? t("settings.speed.last_update_value", {
          value: {
            number: status.last_update_age_s,
            options: { minimumFractionDigits: 1, maximumFractionDigits: 1 },
          },
        })
        : t("settings.speed.last_update_never");
    }
    if (els.gpsStatusRawSpeed) {
      els.gpsStatusRawSpeed.textContent = formatSpeedValue(status.raw_speed_kmh, unitLabel) ?? "--";
    }
    if (els.gpsStatusEffectiveSpeed) {
      els.gpsStatusEffectiveSpeed.textContent = formatSpeedValue(status.effective_speed_kmh, unitLabel) ?? "--";
    }
    if (els.gpsStatusLastError) {
      els.gpsStatusLastError.textContent = status.last_error ?? "--";
    }
    if (els.gpsStatusReconnect) {
      els.gpsStatusReconnect.textContent = status.reconnect_delay_s != null ? `${fmt(status.reconnect_delay_s, 1)}s` : "--";
    }
    if (els.gpsStatusFallback) {
      els.gpsStatusFallback.textContent = status.fallback_active ? t("settings.speed.fallback_yes") : t("settings.speed.fallback_no");
    }
  }

  function formatConfiguredDevice(status: ObdStatusPayload): string {
    if (status.configured_device_name && status.configured_device_mac) {
      return `${status.configured_device_name} (${status.configured_device_mac})`;
    }
    return status.configured_device_name ?? status.configured_device_mac ?? t("settings.speed.obd_not_configured");
  }

  function renderObdStatus(status: ObdStatusPayload | null): void {
    if (els.obdStatusPanel) {
      els.obdStatusPanel.hidden = status === null;
    }
    if (status === null) {
      if (els.obdStatusConfiguredDevice) els.obdStatusConfiguredDevice.textContent = "--";
      if (els.obdStatusPairing) els.obdStatusPairing.textContent = "--";
      if (els.obdStatusTrusted) els.obdStatusTrusted.textContent = "--";
      if (els.obdStatusConnected) els.obdStatusConnected.textContent = "--";
      if (els.obdStatusRfcommChannel) els.obdStatusRfcommChannel.textContent = "--";
      if (els.obdStatusLastRpm) els.obdStatusLastRpm.textContent = "--";
      if (els.obdStatusRpmAge) els.obdStatusRpmAge.textContent = "--";
      if (els.obdStatusTargetCadence) els.obdStatusTargetCadence.textContent = "--";
      if (els.obdStatusEffectiveCadence) els.obdStatusEffectiveCadence.textContent = "--";
      if (els.obdStatusRequestRtt) els.obdStatusRequestRtt.textContent = "--";
      if (els.obdStatusTimeouts) els.obdStatusTimeouts.textContent = "--";
      if (els.obdStatusErrors) els.obdStatusErrors.textContent = "--";
      if (els.obdStatusMode) els.obdStatusMode.textContent = "--";
      if (els.obdStatusBackoff) els.obdStatusBackoff.textContent = "--";
      if (els.obdStatusRawResponse) els.obdStatusRawResponse.textContent = "--";
      if (els.obdStatusDebugHint) els.obdStatusDebugHint.textContent = "--";
      return;
    }
    if (els.obdStatusConfiguredDevice) {
      els.obdStatusConfiguredDevice.textContent = formatConfiguredDevice(status);
    }
    if (els.obdStatusPairing) {
      els.obdStatusPairing.textContent = boolLabel(status.paired);
    }
    if (els.obdStatusTrusted) {
      els.obdStatusTrusted.textContent = boolLabel(status.trusted);
    }
    if (els.obdStatusConnected) {
      els.obdStatusConnected.textContent = boolLabel(status.connected);
    }
    if (els.obdStatusRfcommChannel) {
      els.obdStatusRfcommChannel.textContent = status.rfcomm_channel != null ? String(status.rfcomm_channel) : "--";
    }
    if (els.obdStatusLastRpm) {
      els.obdStatusLastRpm.textContent = status.last_rpm != null ? fmt(status.last_rpm, 0) : "--";
    }
    if (els.obdStatusRpmAge) {
      els.obdStatusRpmAge.textContent = formatAgeSeconds(status.rpm_sample_age_s) ?? "--";
    }
    if (els.obdStatusTargetCadence) {
      els.obdStatusTargetCadence.textContent = formatCadenceFromTarget(status.rpm_target_interval_ms) ?? "--";
    }
    if (els.obdStatusEffectiveCadence) {
      els.obdStatusEffectiveCadence.textContent = formatCadenceHz(status.rpm_effective_hz) ?? "--";
    }
    if (els.obdStatusRequestRtt) {
      els.obdStatusRequestRtt.textContent = formatMilliseconds(status.request_rtt_ms) ?? "--";
    }
    if (els.obdStatusTimeouts) {
      els.obdStatusTimeouts.textContent = String(status.timeout_count);
    }
    if (els.obdStatusErrors) {
      els.obdStatusErrors.textContent = String(status.error_count);
    }
    if (els.obdStatusMode) {
      els.obdStatusMode.textContent = obdPollModeLabel(status.poll_mode) ?? "--";
    }
    if (els.obdStatusBackoff) {
      els.obdStatusBackoff.textContent = boolLabel(status.backoff_active);
    }
    if (els.obdStatusRawResponse) {
      els.obdStatusRawResponse.textContent = status.last_raw_response ?? "--";
    }
    if (els.obdStatusDebugHint) {
      els.obdStatusDebugHint.textContent = status.debug_hint ?? "--";
    }
  }

  const polling = createPollingController({
    poll: async () => {
      const shouldLoadObdStatus = settings.speedSource === "obd2" || settings.obdDeviceMac != null;
      const [status, obdStatus] = await Promise.all([
        getSpeedSourceStatus(),
        shouldLoadObdStatus ? getSettingsObdStatus() : Promise.resolve(null),
      ]);
      settings.gpsFallbackActive = status.fallback_active;
      settings.gpsEffectiveSpeedKph = status.effective_speed_kmh;
      settings.resolvedSpeedSource = status.speed_source;
      renderGpsStatus(status);
      renderObdStatus(obdStatus);
      ctx.syncSpeedSourceSelectionUi();
      ctx.renderSpeedReadout();
      return status.connection_state === "connected"
        ? GPS_POLL_FAST_MS
        : GPS_POLL_SLOW_MS;
    },
    onErrorDelayMs: GPS_POLL_SLOW_MS,
  });

  function startGpsStatusPolling(): void {
    polling.start();
  }

  function stopGpsStatusPolling(): void {
    polling.stop();
  }

  return {
    startGpsStatusPolling,
    stopGpsStatusPolling,
  };
}
