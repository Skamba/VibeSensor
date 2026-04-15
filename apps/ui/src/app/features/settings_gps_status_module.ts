import { getSettingsObdStatus, getSpeedSourceStatus } from "../../api";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "../../config";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";
import {
  buildSpeedSourceDiagnosticsRenderModel,
  type SettingsSpeedSourcePresenterDeps,
} from "../views/settings_speed_source_presenter";
import { createPollingController } from "./polling_controller";

interface SettingsGpsStatusModulePorts {
  syncSpeedSourceSelectionUi: () => void;
  renderSpeedReadout: () => void;
}

export interface SettingsGpsStatusModuleDeps {
  panel: SpeedSourcePanelView;
  settings: SettingsState;
  services: Pick<FeatureServices, "t">;
  formatting: Pick<FeatureFormatting, "fmt">;
  getSpeedUnit: () => string;
  ports: SettingsGpsStatusModulePorts;
}

export interface SettingsGpsStatusModule {
  startGpsStatusPolling(): void;
  stopGpsStatusPolling(): void;
}

export function createSettingsGpsStatusModule(
  ctx: SettingsGpsStatusModuleDeps,
): SettingsGpsStatusModule {
  const { panel, settings } = ctx;
  const presenterDeps: SettingsSpeedSourcePresenterDeps = {
    fmt: ctx.formatting.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t: ctx.services.t,
  };

  const polling = createPollingController({
    poll: async () => {
      const shouldLoadObdStatus =
        settings.speedSource === "obd2" || settings.obdDeviceMac != null;
      const [status, obdStatus] = await Promise.all([
        getSpeedSourceStatus(),
        shouldLoadObdStatus ? getSettingsObdStatus() : Promise.resolve(null),
      ]);
      settings.gpsFallbackActive = status.fallback_active;
      settings.gpsEffectiveSpeedKph = status.effective_speed_kmh;
      settings.resolvedSpeedSource = status.speed_source;
      panel.setDiagnostics(
        buildSpeedSourceDiagnosticsRenderModel(status, obdStatus, presenterDeps),
      );
      ctx.ports.syncSpeedSourceSelectionUi();
      ctx.ports.renderSpeedReadout();
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
