import { getSettingsObdStatus, getSpeedSourceStatus } from "../../api";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "../../config";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import { DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL } from "../views/speed_source_panel_defaults";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";
import {
  buildSpeedSourceDiagnosticsRenderModel,
  type SettingsSpeedSourcePresenterDeps,
} from "../views/settings_speed_source_presenter";
import { createPollingController } from "./polling_controller";

interface SettingsGpsStatusModulePorts {
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  syncSpeedSourceSelectionUi: () => void;
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
  bindHandlers(): void;
  dispose(): void;
  markStartupReady(): void;
}

export function createSettingsGpsStatusModule(
  ctx: SettingsGpsStatusModuleDeps,
): SettingsGpsStatusModule {
  const { panel, settings } = ctx;
  const handlersBound = signal(false);
  const startupReady = signal(false);
  const presenterDeps: SettingsSpeedSourcePresenterDeps = {
    fmt: ctx.formatting.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t: ctx.services.t,
  };
  const diagnosticsModel = signal(DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL);
  panel.diagnostics.value = diagnosticsModel;
  const pollingEnabled = computed(() =>
    handlersBound.value
    && startupReady.value
    && (
      ctx.ports.activeViewId.value === "dashboardView"
      || (
        ctx.ports.activeViewId.value === "settingsView"
        && ctx.ports.activeSettingsTabId.value === "speedSourceTab"
      )
    )
  );

  const polling = createPollingController({
    enabled: pollingEnabled,
    poll: async () => {
      const shouldLoadObdStatus =
        settings.speedSource.value === "obd2" || settings.obdDeviceMac.value != null;
      const [status, obdStatus] = await Promise.all([
        getSpeedSourceStatus(),
        shouldLoadObdStatus ? getSettingsObdStatus() : Promise.resolve(null),
      ]);
      batch(() => {
        settings.gpsFallbackActive.value = status.fallback_active;
        settings.gpsEffectiveSpeedKph.value = status.effective_speed_kmh;
        settings.resolvedSpeedSource.value = status.speed_source;
        diagnosticsModel.value = buildSpeedSourceDiagnosticsRenderModel(
          status,
          obdStatus,
          presenterDeps,
        );
      });
      ctx.ports.syncSpeedSourceSelectionUi();
      return status.connection_state === "connected"
        ? GPS_POLL_FAST_MS
        : GPS_POLL_SLOW_MS;
    },
    onErrorDelayMs: GPS_POLL_SLOW_MS,
  });

  return {
    bindHandlers(): void {
      handlersBound.value = true;
    },
    dispose(): void {
      polling.dispose();
    },
    markStartupReady(): void {
      startupReady.value = true;
    },
  };
}
