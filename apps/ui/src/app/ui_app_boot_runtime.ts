import { fmt, fmtTs } from "../format";
import {
  createAppFeatureBundle,
  type AppFeatureBundle,
  type AppFeatureBundleRuntimePorts,
  type AppFeatureBundleSharedDeps,
} from "./app_feature_bundle";
import type { AppState } from "./ui_app_state";
import type {
  UiLazyPanels,
  UiMountedPanels,
} from "./ui_lazy_panels";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import { createUiQueryClient } from "./runtime/ui_query_client";
import {
  DEFAULT_SHELL_VIEW_ID,
} from "./runtime/ui_shell_navigation_module";
import { UiShellController } from "./runtime/ui_shell_controller";
import { createWorkerSpectrumFramePreparer } from "./runtime/spectrum_frame_preparer_worker_client";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";
import { type Signal } from "./ui_signals";
import type {
  UiShellChromeActions,
  UiShellChromeBindings,
} from "./runtime/ui_shell_chrome";

function createUiAppSharedDeps(
  shell: UiShellController,
): Pick<AppFeatureBundleSharedDeps, "formatting" | "services"> {
  return {
    services: {
      t: (key, vars) => shell.t(key, vars),
      requestConfirmation: (message) => shell.requestConfirmation(message),
      showError: (message) => shell.showError(message),
    },
    formatting: {
      fmt,
      fmtTs,
      formatInt: (value) => shell.localFormatInt(value),
    },
  };
}

function createUiAppFeatureRuntimePorts(deps: {
  panels: UiMountedPanels;
  shell: UiShellController;
  spectrum: UiSpectrumController;
  transport: UiLiveTransportController;
}): AppFeatureBundleRuntimePorts {
  const { panels, shell, spectrum, transport } = deps;
  return {
    panels,
    navigation: {
      activatePrimaryView: (viewId) => shell.setActiveView(viewId),
      activeViewId: shell.activeViewId,
    },
    realtimeChrome: {
      setShellLiveStatus: (variant, text) => shell.setLiveStatus(variant, text),
    },
    view: {
      renderSpectrum: () => spectrum.renderSpectrum(),
      refreshSpectrumDecorations: () => spectrum.refreshSpectrumDecorations(),
    },
    transport: {
      sendSelection: () => transport.sendSelection(),
    },
  };
}

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
  let featurePorts!: AppFeatureBundle;
  const shell = new UiShellController({
    bindFeatureHandlers: () => featurePorts.shell.bindHandlers(),
    state: deps.state,
    chrome: deps.shellChrome.view,
    chromeActions: deps.shellChromeActions,
    liveOverview: deps.lazyPanels.panels.dashboard.liveOverview,
    onViewActivated: (viewId) => featurePorts.ensureViewReady(viewId),
    queryClient,
  });
  const spectrum = new UiSpectrumController({
    state: deps.state,
    panel: deps.lazyPanels.panels.dashboard.spectrum,
    t: (key, vars) => shell.t(key, vars),
    framePreparer: createWorkerSpectrumFramePreparer(),
  });
  const transport = new UiLiveTransportController({
    state: deps.state,
    payloadErrorMessage: () => shell.t("ws.payload_error"),
  });
  featurePorts = createAppFeatureBundle({
    state: deps.state,
    shared: {
      ...createUiAppSharedDeps(shell),
      serverState: {
        queryClient,
      },
    },
    runtime: createUiAppFeatureRuntimePorts({
      panels: deps.lazyPanels.panels,
      shell,
      spectrum,
      transport,
    }),
  });
  const startup = new UiStartupCoordinator({
    shell,
    transport,
    features: featurePorts.startup,
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
      featurePorts.dispose();
      queryClient.clear();
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
