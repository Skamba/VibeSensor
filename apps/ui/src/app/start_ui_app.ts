import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import { mountUiPanels } from "./ui_panel_bootstrap";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import {
  createUiShellChromeActionBridge,
  getUiShellChromeHost,
  mountUiShellChrome,
} from "./runtime/ui_shell_chrome";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = createUiShellChromeActionBridge();
  const shellChrome = mountUiShellChrome(getUiShellChromeHost(), shellChromeActions);
  const panels = mountUiPanels();
  new UiAppRuntime({
    shellChrome,
    panels,
    state,
    shellChromeActions,
  }).start();
}
