import { escapeHtml, fmt, fmtTs } from "../format";
import {
  createAppFeatureBundle,
  type AppFeatureBundle,
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

export class UiAppRuntime {
  private readonly state: AppState;

  private readonly featurePorts: AppFeatureBundle;

  private readonly shell: UiShellController;

  private readonly spectrum: UiSpectrumController;

  private readonly transport: UiLiveTransportController;

  private readonly startup: UiStartupCoordinator;

  constructor(deps: UiAppRuntimeDeps) {
    this.state = deps.state ?? createAppState();
    const shellChromeActions =
      deps.shellChromeActions ?? createUiShellChromeActionBridge();
    this.shell = new UiShellController({
      state: this.state,
      chrome: deps.shellChrome,
      chromeActions: shellChromeActions,
      liveOverview: deps.panels.dashboard.liveOverview,
    });
    this.spectrum = new UiSpectrumController({
      state: this.state,
      panel: deps.panels.dashboard.spectrum,
      t: (key, vars) => this.shell.t(key, vars),
    });
    this.shell.attachSpectrumHooks({
      renderSpectrum: () => this.spectrum.renderSpectrum(),
      updateSpectrumOverlay: () => this.spectrum.updateSpectrumOverlay(),
    });
    this.transport = new UiLiveTransportController({
      state: this.state,
      payloadErrorMessage: () => this.shell.t("ws.payload_error"),
    });
    this.featurePorts = createAppFeatureBundle({
      state: this.state,
      shared: {
        t: (key, vars) => this.shell.t(key, vars),
        escapeHtml,
        showError: (message) => this.shell.showError(message),
        fmt,
        fmtTs,
        formatInt: (value) => this.shell.localFormatInt(value),
      },
      runtime: {
        panels: deps.panels,
        navigation: {
          activatePrimaryView: (viewId) => this.shell.setActiveView(viewId),
          subscribeActiveViewChanges: (listener) =>
            this.shell.subscribeActiveViewChanges(listener),
        },
        realtimeChrome: {
          setShellLiveStatus: (variant, text) =>
            this.shell.setLiveStatus(variant, text),
        },
        view: {
          renderSpectrum: () => this.spectrum.renderSpectrum(),
          renderSpeedReadout: () => this.shell.renderSpeedReadout(),
        },
        transport: {
          sendSelection: () => this.transport.sendSelection(),
        },
      },
    });
    this.shell.attachPorts(this.featurePorts.shell);
    this.transport.attachPorts(this.featurePorts.transport);
    this.startup = new UiStartupCoordinator({
      shell: this.shell,
      transport: this.transport,
      features: this.featurePorts.startup,
      defaultViewId: DEFAULT_SHELL_VIEW_ID,
    });
  }

  start(): void {
    this.startup.start();
  }
}
