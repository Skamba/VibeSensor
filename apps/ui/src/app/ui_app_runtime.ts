import { fmt, fmtTs } from "../format";
import {
  createAppFeatureBundle,
  type AppFeatureBundle,
  type AppFeatureBundleRuntimePorts,
  type AppFeatureBundleSharedDeps,
} from "./app_feature_bundle";
import { createAppState, type AppState } from "./ui_app_state";
import {
  createLazyUiPanels,
  type UiLazyPanels,
  type UiMountedLazyPanelHandles,
  type UiMountedPanels,
} from "./ui_lazy_panels";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import {
  createUiShellChromeBindings,
  DEFAULT_UI_SHELL_CHROME_ACTIONS,
  type UiShellChromeActions,
  type UiShellChromeBindings,
} from "./runtime/ui_shell_chrome";
import { DEFAULT_SHELL_VIEW_ID } from "./runtime/ui_shell_navigation_module";
import { UiShellController } from "./runtime/ui_shell_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";
import { signal, type Signal } from "./ui_signals";

function requireUiRuntimeDependency<T>(value: T | null, name: string): T {
  if (value === null) {
    throw new Error(`UiAppRuntime ${name} used before initialization`);
  }
  return value;
}

function createUiAppSharedDeps(
  shell: UiShellController,
): AppFeatureBundleSharedDeps {
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
    },
    transport: {
      sendSelection: () => transport.sendSelection(),
    },
  };
}

export interface UiAppRuntime {
  attachSettingsPanels(handles: UiMountedLazyPanelHandles): void;
  panels: UiMountedPanels;
  prefetchHiddenPanels(): void;
  shellChrome: UiShellChromeBindings;
  spectrumPanel: UiLazyPanels["spectrumPanel"];
  start(): void;
}

export interface UiAppRuntimeDeps {
  state?: AppState;
}

export function createUiAppRuntime(
  deps: UiAppRuntimeDeps = {},
): UiAppRuntime {
  const state = deps.state ?? createAppState();
  const shellChromeActions: Signal<UiShellChromeActions> =
    signal<UiShellChromeActions>({ ...DEFAULT_UI_SHELL_CHROME_ACTIONS });
  const shellChrome = createUiShellChromeBindings(shellChromeActions);
  const lazyPanels = createLazyUiPanels();
  let spectrum: UiSpectrumController | null = null;
  let shellBindings: AppFeatureBundle["shell"] | null = null;
  const shell = new UiShellController({
    bindFeatureHandlers: () =>
      requireUiRuntimeDependency(shellBindings, "shell bindings").bindHandlers(),
    state,
    chrome: shellChrome.view,
    chromeActions: shellChromeActions,
    liveOverview: lazyPanels.panels.dashboard.liveOverview,
  });
  spectrum = new UiSpectrumController({
    state,
    panel: lazyPanels.panels.dashboard.spectrum,
    t: (key, vars) => shell.t(key, vars),
  });
  const transport = new UiLiveTransportController({
    state,
    payloadErrorMessage: () => shell.t("ws.payload_error"),
  });
  const featurePorts = createAppFeatureBundle({
    state,
    shared: createUiAppSharedDeps(shell),
    runtime: createUiAppFeatureRuntimePorts({
      panels: lazyPanels.panels,
      shell,
      spectrum,
      transport,
    }),
  });
  shellBindings = featurePorts.shell;
  const startup = new UiStartupCoordinator({
    shell,
    transport,
    features: featurePorts.startup,
    defaultViewId: DEFAULT_SHELL_VIEW_ID,
  });

  return {
    attachSettingsPanels: lazyPanels.attachSettingsPanels,
    panels: lazyPanels.panels,
    prefetchHiddenPanels: lazyPanels.prefetchHiddenPanels,
    shellChrome,
    spectrumPanel: lazyPanels.spectrumPanel,
    start() {
      startup.start();
    },
  };
}
