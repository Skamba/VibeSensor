import "../styles/app.css";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import { createLazyUiPanels } from "./ui_lazy_panels";
import {
  createUiShellChromeActionBridge,
  getUiShellChromeHost,
  mountUiShellChrome,
} from "./runtime/ui_shell_chrome";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = createUiShellChromeActionBridge();
  const shellChrome = mountUiShellChrome(getUiShellChromeHost(), shellChromeActions);
  const lazyPanels = createLazyUiPanels();
  new UiAppRuntime({
    shellChrome,
    panels: lazyPanels.panels,
    ensureViewPanels: lazyPanels.ensureViewPanels,
    state,
    shellChromeActions,
  }).start();
  lazyPanels.prefetchHiddenPanels();
}
