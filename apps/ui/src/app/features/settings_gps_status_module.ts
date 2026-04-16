import { getSettingsObdStatus, getSpeedSourceStatus } from "../../api";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "../../config";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";
import {
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
  getActiveSettingsTabId: () => string;
  activeViewId: ReadonlySignal<string>;
  syncSpeedSourceSelectionUi: () => void;
  renderSpeedReadout: () => void;
  subscribeSettingsTabChanges(listener: (tabId: string) => void): () => void;
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
  markStartupReady(): void;
}

export function createSettingsGpsStatusModule(
  ctx: SettingsGpsStatusModuleDeps,
): SettingsGpsStatusModule {
  const { panel, settings } = ctx;
  const handlersBound = signal(false);
  const startupReady = signal(false);
  const activeSettingsTabId = signal(ctx.ports.getActiveSettingsTabId());
  const presenterDeps: SettingsSpeedSourcePresenterDeps = {
    fmt: ctx.formatting.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t: ctx.services.t,
  };
  const diagnosticsModel = signal(DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL);
  panel.bindDiagnostics(diagnosticsModel);
  const pollingEnabled = computed(() =>
    handlersBound.value
    && startupReady.value
    && (
      ctx.ports.activeViewId.value === "dashboardView"
      || (
        ctx.ports.activeViewId.value === "settingsView"
        && activeSettingsTabId.value === "speedSourceTab"
      )
    )
  );

  ctx.ports.subscribeSettingsTabChanges((tabId) => {
    activeSettingsTabId.value = tabId;
  });

  createPollingController({
    enabled: pollingEnabled,
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
      diagnosticsModel.value = buildSpeedSourceDiagnosticsRenderModel(status, obdStatus, presenterDeps);
      ctx.ports.syncSpeedSourceSelectionUi();
      ctx.ports.renderSpeedReadout();
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
    markStartupReady(): void {
      startupReady.value = true;
    },
  };
}
