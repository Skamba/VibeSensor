import type { SpectrumPanelView } from "./runtime/spectrum_panel_view";
import {
  type UiPanelHostRegistry,
} from "./ui_panel_host_registry";
import type { AnalysisPanelView } from "./views/analysis_panel";
import type { CarsPanelView } from "./views/cars_panel";
import type { EspFlashPanelView } from "./views/esp_flash_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import type { InternetPanelView } from "./views/internet_panel";
import {
  mountRealtimeLoggingPanel,
  type RealtimeLoggingPanelBridge,
} from "./views/realtime_logging_panel";
import {
  mountRealtimeLiveOverview,
  type RealtimeLiveOverviewBridge,
} from "./views/realtime_live_overview";
import type { SensorsPanelView } from "./views/sensors_panel";
import type { SettingsShellView } from "./views/settings_shell";
import type { SpeedSourcePanelView } from "./views/speed_source_panel";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import type { UpdatePanelView } from "./views/update_panel";

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

export function mountDashboardPanels(
  hosts: UiPanelHostRegistry,
): UiMountedDashboardPanels {
  return {
    spectrum: mountSpectrumPanel(hosts.dashboard.spectrum),
    liveOverview: mountRealtimeLiveOverview(hosts.dashboard.liveOverview),
    logging: mountRealtimeLoggingPanel(hosts.dashboard.logging),
  };
}

export async function mountHistoryPanelLazy(
  hosts: UiPanelHostRegistry,
): Promise<HistoryPanelView> {
  const { mountHistoryPanel } = await import("./views/history_panel");
  return mountHistoryPanel(hosts.history);
}

export async function mountSettingsPanelsLazy(
  hosts: UiPanelHostRegistry,
): Promise<UiMountedLazyPanels> {
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
  const settingsShell = mountSettingsShell(hosts.settingsShell);
  const settingsHosts = hosts.resolveSettingsPanels();
  const [
    { mountCarsPanel },
    { mountAnalysisPanel },
    { mountInternetPanel },
    { mountUpdatePanel },
    { mountSensorsPanel },
    { mountSpeedSourcePanel },
    { mountEspFlashPanel },
  ] = await settingsPanelModulesPromise;
  return {
    settingsShell,
    settings: {
      cars: mountCarsPanel(settingsHosts.cars),
      analysis: mountAnalysisPanel(settingsHosts.analysis),
      internet: mountInternetPanel(settingsHosts.internet),
      update: mountUpdatePanel(settingsHosts.update),
      sensors: mountSensorsPanel(settingsHosts.sensors),
      speedSource: mountSpeedSourcePanel(settingsHosts.speedSource),
      espFlash: mountEspFlashPanel(settingsHosts.espFlash),
    },
  };
}
