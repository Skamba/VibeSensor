import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import { requiredById } from "./dom/dom_query";
import { getUiAnalysisPanelHost } from "./dom/analysis_dom";
import { getUiCarsPanelHost } from "./dom/cars_dom";
import { getUiEspFlashPanelHost } from "./dom/esp_flash_dom";
import { getUiHistoryPanelHost } from "./dom/history_dom";
import { getUiInternetPanelHost } from "./dom/internet_dom";
import { getUiSensorsPanelHost } from "./dom/sensors_dom";
import { getUiSettingsShellHost } from "./dom/settings_shell_dom";
import { getUiSpeedSourcePanelHost } from "./dom/speed_source_dom";
import { getUiUpdatePanelHost } from "./dom/update_dom";
import {
  getUiLiveOverviewHost,
  getUiLoggingPanelHost,
} from "./dom/realtime_dom";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import { mountAnalysisPanel } from "./views/analysis_panel";
import { mountCarsPanel } from "./views/cars_panel";
import { mountEspFlashPanel } from "./views/esp_flash_panel";
import { mountHistoryPanel } from "./views/history_panel";
import { mountInternetPanel } from "./views/internet_panel";
import { mountRealtimeLoggingPanel } from "./views/realtime_logging_panel";
import { mountRealtimeLiveOverview } from "./views/realtime_live_overview";
import { mountSensorsPanel } from "./views/sensors_panel";
import { mountSettingsShell } from "./views/settings_shell";
import { mountSpeedSourcePanel } from "./views/speed_source_panel";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import { mountUpdatePanel } from "./views/update_panel";
import {
  createUiShellChromeActionBridge,
  getUiShellChromeHost,
  mountUiShellChrome,
} from "./runtime/ui_shell_chrome";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = createUiShellChromeActionBridge();
  const spectrumPanel = mountSpectrumPanel(
    requiredById<HTMLElement>("spectrumPanelRoot", "Spectrum UI"),
  );
  const liveOverview = mountRealtimeLiveOverview(getUiLiveOverviewHost());
  const loggingPanel = mountRealtimeLoggingPanel(getUiLoggingPanelHost());
  const historyPanel = mountHistoryPanel(getUiHistoryPanelHost());
  const settingsShell = mountSettingsShell(getUiSettingsShellHost());
  const carsPanel = mountCarsPanel(getUiCarsPanelHost());
  const analysisPanel = mountAnalysisPanel(getUiAnalysisPanelHost());
  const internetPanel = mountInternetPanel(getUiInternetPanelHost());
  const updatePanel = mountUpdatePanel(getUiUpdatePanelHost());
  const sensorsPanel = mountSensorsPanel(getUiSensorsPanelHost());
  const speedSourcePanel = mountSpeedSourcePanel(getUiSpeedSourcePanelHost());
  const espFlashPanel = mountEspFlashPanel(getUiEspFlashPanelHost());
  const shellChrome = mountUiShellChrome(getUiShellChromeHost(), shellChromeActions);
  new UiAppRuntime(
    shellChrome,
    settingsShell,
    carsPanel,
    analysisPanel,
    internetPanel,
    updatePanel,
    sensorsPanel,
    speedSourcePanel,
    espFlashPanel,
    state,
    shellChromeActions,
    liveOverview,
    spectrumPanel,
    loggingPanel,
    historyPanel,
  ).start();
}
