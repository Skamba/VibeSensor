import "../styles/app.css";
import { h, render } from "preact";

import { UiAppRoot } from "./ui_app_root";
import { createAppState } from "./ui_app_state";
import { createUiAppRuntime } from "./ui_app_runtime";
import { getUiShellChromeHost } from "./runtime/ui_shell_chrome";

const UI_APP_MOUNTED_ATTR = "data-ui-app-mounted";

export function startUiApp(): void {
  const host = getUiShellChromeHost();
  if (host.getAttribute(UI_APP_MOUNTED_ATTR) === "true") {
    return;
  }
  host.setAttribute(UI_APP_MOUNTED_ATTR, "true");
  const state = createAppState();
  const runtime = createUiAppRuntime({ state });
  render(
    h(UiAppRoot, {
      attachSettingsPanels: runtime.attachSettingsPanels,
      panels: runtime.panels,
      shellChrome: runtime.shellChrome,
      spectrumPanel: runtime.spectrumPanel,
    }),
    host,
  );
  runtime.start();
}
