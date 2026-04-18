import "../styles/app.css";
import { h, render } from "preact";

import { UiAppRoot } from "./ui_app_root";
import {
  mountUiApp,
  type StartedUiApp,
  type StartUiAppDeps,
} from "./ui_app_mount";

export type { StartedUiApp, StartUiAppDeps };

export function startUiApp(deps: Omit<StartUiAppDeps, "renderRoot"> = {}): StartedUiApp {
  return mountUiApp({
    ...deps,
    renderApp: deps.renderApp ?? render,
    renderRoot: (runtime) => h(UiAppRoot, {
      attachSettingsPanels: runtime.attachSettingsPanels,
      panels: runtime.panels,
      shellChrome: runtime.shellChrome,
      spectrumPanel: runtime.spectrumPanel,
    }),
  });
}
