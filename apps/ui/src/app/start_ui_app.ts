import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import { getUiLiveOverviewHost, getUiLoggingPanelHost } from "./dom/realtime_dom";
import { getUiShellChromeHost } from "./dom/shell_dom";
import { getUiSpectrumPanelHost } from "./dom/spectrum_dom";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import { mountRealtimeLoggingPanel } from "./views/realtime_logging_panel";
import { mountRealtimeLiveOverview } from "./views/realtime_live_overview";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import { createUiShellChromeActionBridge, mountUiShellChrome } from "./runtime/ui_shell_chrome";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = createUiShellChromeActionBridge();
  const spectrumPanel = mountSpectrumPanel(getUiSpectrumPanelHost());
  const liveOverview = mountRealtimeLiveOverview(getUiLiveOverviewHost());
  const loggingPanel = mountRealtimeLoggingPanel(getUiLoggingPanelHost());
  mountUiShellChrome(getUiShellChromeHost(), shellChromeActions, state.shell);
  new UiAppRuntime(undefined, state, shellChromeActions, liveOverview, spectrumPanel, loggingPanel).start();
}
