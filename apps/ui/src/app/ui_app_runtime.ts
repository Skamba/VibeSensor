import { fmt, fmtTs } from "../format";
import {
  createAppFeatureBundle,
  type AppFeatureBundle,
  type AppFeatureBundleRuntimePorts,
  type AppFeatureBundleSharedDeps,
} from "./app_feature_bundle";
import type { AppState } from "./ui_app_state";
import { createAppState } from "./ui_app_state";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import {
  createUiShellChromeActionBridge,
  type UiShellChromeActionBridge,
  type UiShellChromeView,
} from "./runtime/ui_shell_chrome";
import { DEFAULT_SHELL_VIEW_ID } from "./runtime/ui_shell_navigation_module";
import { UiShellController } from "./runtime/ui_shell_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";
import type { UiMountedPanels } from "./ui_panel_bootstrap";

export interface UiAppRuntimeDeps {
  shellChrome: UiShellChromeView;
  panels: UiMountedPanels;
  state?: AppState;
  shellChromeActions?: UiShellChromeActionBridge;
}

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
  const {
    panels,
    shell,
    spectrum,
    transport,
  } = deps;
  return {
    panels,
    navigation: {
      activatePrimaryView: (viewId) => shell.setActiveView(viewId),
      activeViewId: shell.activeViewId,
    },
    realtimeChrome: {
      setShellLiveStatus: (variant, text) =>
        shell.setLiveStatus(variant, text),
    },
    view: {
      renderSpectrum: () => spectrum.renderSpectrum(),
      renderSpeedReadout: () => shell.renderSpeedReadout(),
    },
    transport: {
      sendSelection: () => transport.sendSelection(),
    },
  };
}

export class UiAppRuntime {
  private readonly startup: UiStartupCoordinator;

  constructor(deps: UiAppRuntimeDeps) {
    const state = deps.state ?? createAppState();
    const shellChromeActions =
      deps.shellChromeActions ?? createUiShellChromeActionBridge();
    let spectrum: UiSpectrumController | null = null;
    let shellBindings: AppFeatureBundle["shell"] | null = null;
    const shell = new UiShellController({
      bindFeatureHandlers: () =>
        requireUiRuntimeDependency(shellBindings, "shell bindings").bindHandlers(),
      state,
      chrome: deps.shellChrome,
      chromeActions: shellChromeActions,
      liveOverview: deps.panels.dashboard.liveOverview,
    });
    spectrum = new UiSpectrumController({
      state,
      panel: deps.panels.dashboard.spectrum,
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
        panels: deps.panels,
        shell,
        spectrum,
        transport,
      }),
    });
    shellBindings = featurePorts.shell;
    this.startup = new UiStartupCoordinator({
      shell,
      transport,
      features: featurePorts.startup,
      defaultViewId: DEFAULT_SHELL_VIEW_ID,
    });
  }

  start(): void {
    this.startup.start();
  }
}
