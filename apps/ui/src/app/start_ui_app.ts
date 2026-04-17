import "../styles/app.css";
import { createAppState } from "./ui_app_state";
import { UiAppRuntime } from "./ui_app_runtime";
import { createLazyUiPanels } from "./ui_lazy_panels";
import {
  DEFAULT_UI_SHELL_CHROME_ACTIONS,
  getUiShellChromeHost,
  mountUiShellChrome,
} from "./runtime/ui_shell_chrome";
import { signal } from "./ui_signals";

export function startUiApp(): void {
  const state = createAppState();
  const shellChromeActions = signal({ ...DEFAULT_UI_SHELL_CHROME_ACTIONS });
  const shellChrome = mountUiShellChrome(getUiShellChromeHost(), shellChromeActions);
  const lazyPanels = createLazyUiPanels({ hosts: shellChrome.panelHosts });
  new UiAppRuntime({
    shellChrome,
    panels: lazyPanels.panels,
    ensureViewPanels: lazyPanels.ensureViewPanels,
    state,
    shellChromeActions,
  }).start();
  lazyPanels.prefetchHiddenPanels();
}
