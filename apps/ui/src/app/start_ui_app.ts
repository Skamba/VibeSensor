import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import { getUiShellChromeHost } from "./dom/shell_dom";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import { createUiShellChromeActionBridge, mountUiShellChrome } from "./runtime/ui_shell_chrome";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = createUiShellChromeActionBridge();
  mountUiShellChrome(getUiShellChromeHost(), shellChromeActions, state.shell);
  new UiAppRuntime(undefined, state, shellChromeActions).start();
}
