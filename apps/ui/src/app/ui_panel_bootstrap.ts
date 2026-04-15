import type { SpectrumPanelView } from "./runtime/spectrum_panel_view";
import {
  resolveUiPanelHosts,
  type UiPanelHostRegistry,
} from "./ui_panel_host_registry";
import { mountAnalysisPanel, type AnalysisPanelView } from "./views/analysis_panel";
import { mountCarsPanel, type CarsPanelView } from "./views/cars_panel";
import { mountEspFlashPanel, type EspFlashPanelView } from "./views/esp_flash_panel";
import { mountHistoryPanel } from "./views/history_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import { mountInternetPanel, type InternetPanelView } from "./views/internet_panel";
import {
  mountRealtimeLoggingPanel,
  type RealtimeLoggingPanelBridge,
} from "./views/realtime_logging_panel";
import {
  mountRealtimeLiveOverview,
  type RealtimeLiveOverviewBridge,
} from "./views/realtime_live_overview";
import { mountSensorsPanel, type SensorsPanelView } from "./views/sensors_panel";
import { mountSettingsShell, type SettingsShellView } from "./views/settings_shell";
import { mountSpeedSourcePanel, type SpeedSourcePanelView } from "./views/speed_source_panel";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import { mountUpdatePanel, type UpdatePanelView } from "./views/update_panel";

export interface UiMountedPanels {
  dashboard: {
    spectrum: SpectrumPanelView;
    liveOverview: RealtimeLiveOverviewBridge;
    logging: RealtimeLoggingPanelBridge;
  };
  history: HistoryPanelView;
  settingsShell: SettingsShellView;
  settings: {
    cars: CarsPanelView;
    analysis: AnalysisPanelView;
    internet: InternetPanelView;
    update: UpdatePanelView;
    sensors: SensorsPanelView;
    speedSource: SpeedSourcePanelView;
    espFlash: EspFlashPanelView;
  };
}

export function mountUiPanels(hosts: UiPanelHostRegistry = resolveUiPanelHosts()): UiMountedPanels {
  const settingsShell = mountSettingsShell(hosts.settingsShell);
  const settingsHosts = hosts.resolveSettingsPanels();
  return {
    dashboard: {
      spectrum: mountSpectrumPanel(hosts.dashboard.spectrum),
      liveOverview: mountRealtimeLiveOverview(hosts.dashboard.liveOverview),
      logging: mountRealtimeLoggingPanel(hosts.dashboard.logging),
    },
    history: mountHistoryPanel(hosts.history),
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
