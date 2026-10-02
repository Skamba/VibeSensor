import { fmt, fmtTs, formatIntLocale } from "../format";
import {
  createAppFeatureBundle,
  type AppFeatureBundle,
} from "./app_feature_bundle";
import type { AppState } from "./ui_app_state";
import type { UiLazyPanels } from "./ui_lazy_panels";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import { createUiQueryClient } from "./runtime/ui_query_client";
import {
  DEFAULT_SHELL_VIEW_ID,
  UiShellController,
} from "./runtime/ui_shell_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";
import { type Signal } from "./ui_signals";
import type {
  UiShellChromeActions,
  UiShellChromeBindings,
} from "./runtime/ui_shell_chrome";

export interface UiAppBootRuntime {
  dispose(): void;
  start(): void;
}

export function createUiAppBootRuntime(deps: {
  lazyPanels: UiLazyPanels;
  shellChrome: UiShellChromeBindings;
  shellChromeActions: Signal<UiShellChromeActions>;
  state: AppState;
}): UiAppBootRuntime {
  const queryClient = createUiQueryClient();
  queryClient.mount();
  let features!: AppFeatureBundle;
  const shell = new UiShellController({
    bindFeatureHandlers: () => features.bindHandlers(),
    state: deps.state,
    chrome: deps.shellChrome.view,
    chromeActions: deps.shellChromeActions,
    liveOverview: deps.lazyPanels.panels.dashboard.liveOverview,
    onViewActivated: (viewId) => features.ensureViewReady(viewId),
    queryClient,
  });
  const spectrum = new UiSpectrumController({
    state: deps.state,
    panel: deps.lazyPanels.panels.dashboard.spectrum,
    t: (key, vars) => shell.t(key, vars),
  });
  const transport = new UiLiveTransportController({
    state: deps.state,
    payloadErrorMessage: () => shell.t("ws.payload_error"),
  });
  features = createAppFeatureBundle({
    state: deps.state,
    services: {
      t: (key, vars) => shell.t(key, vars),
      requestConfirmation: (message) => shell.requestConfirmation(message),
      showError: (message) => shell.showError(message),
    },
    formatting: {
      fmt,
      fmtTs,
      formatInt: (value) => formatIntLocale(value, deps.state.shell.lang.value),
    },
    queryClient,
    panels: deps.lazyPanels.panels,
    activeViewId: shell.activeViewId,
    activatePrimaryView: (viewId) => shell.setActiveView(viewId),
    setShellLiveStatus: (variant, text) => shell.setLiveStatus(variant, text),
    sendSelection: () => transport.sendSelection(),
    refreshSpectrumDecorations: () => spectrum.refreshSpectrumDecorations(),
  });
  const startup = new UiStartupCoordinator({
    shell,
    transport,
    features: features.startup,
    defaultViewId: DEFAULT_SHELL_VIEW_ID,
  });
  let started = false;
  let disposed = false;

  return {
    dispose(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      features.dispose();
      queryClient.clear();
      queryClient.unmount();
      transport.dispose();
      spectrum.dispose();
      shell.dispose();
    },
    start(): void {
      if (disposed || started) {
        return;
      }
      started = true;
      startup.start();
    },
  };
}
