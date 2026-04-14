import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import { getUiAnalysisPanelHost } from "./dom/analysis_dom";
import { getUiCarsPanelHost } from "./dom/cars_dom";
import { getUiHistoryPanelHost } from "./dom/history_dom";
import { getUiInternetPanelHost } from "./dom/internet_dom";
import { getUiSensorsPanelHost } from "./dom/sensors_dom";
import { getUiSpeedSourcePanelHost } from "./dom/speed_source_dom";
import { getUiUpdatePanelHost } from "./dom/update_dom";
import {
  getUiLiveOverviewHost,
  getUiLoggingPanelHost,
} from "./dom/realtime_dom";
import { getUiShellChromeHost } from "./dom/shell_dom";
import { getUiSpectrumPanelHost } from "./dom/spectrum_dom";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import { mountAnalysisPanel } from "./views/analysis_panel";
import { mountCarsPanel } from "./views/cars_panel";
import { mountHistoryPanel } from "./views/history_panel";
import { mountInternetPanel } from "./views/internet_panel";
import { mountRealtimeLoggingPanel } from "./views/realtime_logging_panel";
import { mountRealtimeLiveOverview } from "./views/realtime_live_overview";
import { mountSensorsPanel } from "./views/sensors_panel";
import { mountSpeedSourcePanel } from "./views/speed_source_panel";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import { mountUpdatePanel } from "./views/update_panel";
import {
  createUiShellChromeActionBridge,
  mountUiShellChrome,
} from "./runtime/ui_shell_chrome";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = createUiShellChromeActionBridge();
  const spectrumPanel = mountSpectrumPanel(getUiSpectrumPanelHost());
  const liveOverview = mountRealtimeLiveOverview(getUiLiveOverviewHost());
  const loggingPanel = mountRealtimeLoggingPanel(getUiLoggingPanelHost());
  const historyPanel = mountHistoryPanel(getUiHistoryPanelHost());
  const carsPanel = mountCarsPanel(getUiCarsPanelHost());
  const analysisPanel = mountAnalysisPanel(getUiAnalysisPanelHost());
  const internetPanel = mountInternetPanel(getUiInternetPanelHost());
  const updatePanel = mountUpdatePanel(getUiUpdatePanelHost());
  const sensorsPanel = mountSensorsPanel(getUiSensorsPanelHost());
  const speedSourcePanel = mountSpeedSourcePanel(getUiSpeedSourcePanelHost());
  mountUiShellChrome(getUiShellChromeHost(), shellChromeActions, state.shell);
  new UiAppRuntime(
    undefined,
    state,
    shellChromeActions,
    liveOverview,
    spectrumPanel,
    loggingPanel,
    historyPanel,
    carsPanel,
    analysisPanel,
    internetPanel,
    updatePanel,
    sensorsPanel,
    speedSourcePanel,
  ).start();
}
