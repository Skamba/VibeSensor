import type { SpeedSourceStatusPayload } from "../../api/types";
import { getSpeedSourceStatus } from "../../api";
import {
  GPS_POLL_FAST_MS,
  GPS_POLL_SLOW_MS,
} from "../../config";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";
import { createPollingController } from "./polling_controller";

const CONNECTION_STATE_I18N: Record<string, string> = {
  disabled: "settings.speed.state_disabled",
  disconnected: "settings.speed.state_disconnected",
  connected: "settings.speed.state_connected",
  stale: "settings.speed.state_stale",
};

export interface SettingsGpsStatusModuleDeps extends FeatureDepsBase {
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
  const { settings, els, t, fmt } = ctx;

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

  const polling = createPollingController({
    poll: async () => {
      const status = await getSpeedSourceStatus();
      settings.gpsFallbackActive = status.fallback_active;
      settings.gpsEffectiveSpeedKph = status.effective_speed_kmh;
      settings.resolvedSpeedSource = status.speed_source;
      renderGpsStatus(status);
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
