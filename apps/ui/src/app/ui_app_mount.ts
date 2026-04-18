import type { ComponentChild } from "preact";
import { render } from "preact";

import { createAppState, type AppState } from "./ui_app_state";
import { createUiAppRuntime, type UiAppRuntime } from "./ui_app_runtime";
import { getUiShellChromeHost } from "./runtime/ui_shell_chrome";

const UI_APP_MOUNTED_ATTR = "data-ui-app-mounted";

export interface StartedUiApp {
  dispose(): void;
}

export interface StartUiAppDeps {
  createRuntime?: (deps: { state: AppState }) => UiAppRuntime;
  createState?: () => AppState;
  renderApp?: typeof render;
  renderRoot(runtime: UiAppRuntime): ComponentChild;
}

let mountedApp: StartedUiApp | null = null;

export function mountUiApp(deps: StartUiAppDeps): StartedUiApp {
  const host = getUiShellChromeHost();
  if (host.getAttribute(UI_APP_MOUNTED_ATTR) === "true" && mountedApp) {
    return mountedApp;
  }
  host.setAttribute(UI_APP_MOUNTED_ATTR, "true");
  const state = (deps.createState ?? createAppState)();
  const runtime = (deps.createRuntime ?? createUiAppRuntime)({ state });
  const renderApp = deps.renderApp ?? render;
  renderApp(deps.renderRoot(runtime), host);
  runtime.start();
  const app: StartedUiApp = {
    dispose() {
      runtime.dispose();
      renderApp(null, host);
      host.removeAttribute(UI_APP_MOUNTED_ATTR);
      if (mountedApp === app) {
        mountedApp = null;
      }
    },
  };
  mountedApp = app;
  return app;
}
