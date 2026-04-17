import { signal } from "./ui_signals";
import {
  createDeferredModelSignal,
  createModelActionPanelBindings,
} from "./views/view_model_binding";
import type { SpectrumPanelView } from "./runtime/spectrum_panel_view";
import {
  type UiPanelHostRegistry,
} from "./ui_panel_host_registry";
import { mountAnalysisPanel, type AnalysisPanelView } from "./views/analysis_panel";
import { mountCarsPanel, type CarsPanelView } from "./views/cars_panel";
import { mountEspFlashPanel, type EspFlashPanelView } from "./views/esp_flash_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import { mountInternetPanel, type InternetPanelView } from "./views/internet_panel";
import {
  mountRealtimeLoggingPanel,
  type RealtimeLoggingPanelActionHandlers,
  type RealtimeLoggingPanelBridge,
  type RealtimeLoggingPanelRenderModel,
} from "./views/realtime_logging_panel";
import {
  mountRealtimeLiveOverview,
  type RealtimeLiveOverviewBridge,
  type RealtimeLiveOverviewRenderModel,
} from "./views/realtime_live_overview";
import { mountSensorsPanel, type SensorsPanelView } from "./views/sensors_panel";
import type { SettingsShellView } from "./views/settings_shell";
import { mountSpeedSourcePanel, type SpeedSourcePanelView } from "./views/speed_source_panel";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import { mountUpdatePanel, type UpdatePanelView } from "./views/update_panel";

export interface UiMountedDashboardPanels {
  spectrum: SpectrumPanelView;
  liveOverview: RealtimeLiveOverviewBridge;
  logging: RealtimeLoggingPanelBridge;
}

export interface UiMountedSettingsPanels {
  cars: CarsPanelView;
  analysis: AnalysisPanelView;
  internet: InternetPanelView;
  update: UpdatePanelView;
  sensors: SensorsPanelView;
  speedSource: SpeedSourcePanelView;
  espFlash: EspFlashPanelView;
}

export interface UiMountedPanels {
  dashboard: UiMountedDashboardPanels;
  history: HistoryPanelView;
  settingsShell: SettingsShellView;
  settings: UiMountedSettingsPanels;
}

export type UiMountedLazyPanels = Pick<UiMountedPanels, "settingsShell" | "settings">;

export interface UiMountedLazyPanelHandles {
  settingsShell: SettingsShellView;
  settings: {
    analysis: Pick<AnalysisPanelView, "focusField" | "openGuidance">;
    cars: Pick<CarsPanelView["wizard"], "focus">;
    internet: Pick<InternetPanelView, "focusSsidInput">;
    speedSource: Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput" | "isObdConfigVisible"
    >;
  };
}

export function mountDashboardPanels(
  hosts: UiPanelHostRegistry,
): UiMountedDashboardPanels {
  const liveOverview: RealtimeLiveOverviewBridge = {
    model: createDeferredModelSignal<RealtimeLiveOverviewRenderModel>(),
    speedText: signal("--"),
  };
  const logging: RealtimeLoggingPanelBridge = createModelActionPanelBindings<
    RealtimeLoggingPanelRenderModel,
    RealtimeLoggingPanelActionHandlers
  >();
  mountRealtimeLiveOverview(hosts.dashboard.liveOverview, liveOverview);
  mountRealtimeLoggingPanel(hosts.dashboard.logging, logging);
  return {
    spectrum: mountSpectrumPanel(hosts.dashboard.spectrum),
    liveOverview,
    logging,
  };
}

export async function mountHistoryPanelLazy(
  hosts: UiPanelHostRegistry,
  view: HistoryPanelView,
): Promise<void> {
  const { mountHistoryPanel } = await import("./views/history_panel");
  mountHistoryPanel(hosts.history, view);
}

export async function mountSettingsPanelsLazy(
  hosts: UiPanelHostRegistry,
  panels: UiMountedLazyPanels,
): Promise<UiMountedLazyPanelHandles> {
  const settingsShellModulePromise = import("./views/settings_shell");
  const settingsPanelModulesPromise = Promise.all([
    import("./views/cars_panel"),
    import("./views/analysis_panel"),
    import("./views/internet_panel"),
    import("./views/update_panel"),
    import("./views/sensors_panel"),
    import("./views/speed_source_panel"),
    import("./views/esp_flash_panel"),
  ]);
  const { mountSettingsShell } = await settingsShellModulePromise;
  const settingsShellMount = mountSettingsShell(hosts.settingsShell);
  const settingsShell = settingsShellMount.view;
  const settingsHosts = settingsShellMount.panelHosts;
  const [
    { mountCarsPanel },
    { mountAnalysisPanel },
    { mountInternetPanel },
    { mountUpdatePanel },
    { mountSensorsPanel },
    { mountSpeedSourcePanel },
    { mountEspFlashPanel },
  ] = await settingsPanelModulesPromise;
  const cars = mountCarsPanel(settingsHosts.cars, panels.settings.cars);
  const analysis = mountAnalysisPanel(settingsHosts.analysis, panels.settings.analysis);
  const internet = mountInternetPanel(settingsHosts.internet, panels.settings.internet);
  mountUpdatePanel(settingsHosts.update, panels.settings.update);
  mountSensorsPanel(settingsHosts.sensors, panels.settings.sensors);
  const speedSource = mountSpeedSourcePanel(settingsHosts.speedSource, panels.settings.speedSource);
  mountEspFlashPanel(settingsHosts.espFlash, panels.settings.espFlash);
  return {
    settingsShell,
    settings: {
      cars,
      analysis,
      internet,
      speedSource,
    },
  };
}
