import { escapeHtml, fmt, fmtTs } from "../format";
import type { UiDomElements } from "./ui_dom_registry";
import { createUiDomRegistry } from "./ui_dom_registry";
import { createAppFeatureBundle, type AppFeatureBundle } from "./app_feature_bundle";
import type { AppState } from "./ui_app_state";
import { createAppState } from "./ui_app_state";
import { UiLiveTransportController, type UiTransportFeaturePorts } from "./runtime/ui_live_transport_controller";
import { DEFAULT_SHELL_VIEW_ID } from "./runtime/ui_shell_navigation_module";
import { UiShellController } from "./runtime/ui_shell_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";

export class UiAppRuntime {
  private readonly els: UiDomElements;

  private readonly state: AppState;

  private readonly features: AppFeatureBundle;

  private readonly shell: UiShellController;

  private readonly spectrum: UiSpectrumController;

  private readonly transport: UiLiveTransportController;

  private readonly startup: UiStartupCoordinator;

  constructor(
    els: UiDomElements = createUiDomRegistry(),
    state: AppState = createAppState(),
  ) {
    this.els = els;
    this.state = state;
    this.shell = new UiShellController({
      state: this.state,
      els: this.els,
    });
    this.spectrum = new UiSpectrumController({
      state: this.state,
      els: this.els,
      t: (key, vars) => this.shell.t(key, vars),
    });
    this.shell.attachSpectrumHooks({
      renderSpectrum: () => this.spectrum.renderSpectrum(),
      updateSpectrumOverlay: () => this.spectrum.updateSpectrumOverlay(),
    });
    this.transport = new UiLiveTransportController({
      state: this.state,
      payloadErrorMessage: () => this.shell.t("ws.payload_error"),
      renderWsState: () => this.shell.renderWsState(),
      renderSpeedReadout: () => this.shell.renderSpeedReadout(),
      renderSpectrum: () => this.spectrum.renderSpectrum(),
      updateSpectrumOverlay: () => this.spectrum.updateSpectrumOverlay(),
    });
    this.features = createAppFeatureBundle({
      state: this.state,
      els: this.els,
      t: (key, vars) => this.shell.t(key, vars),
      escapeHtml,
      showError: (message) => this.shell.showError(message),
      fmt,
      fmtTs,
      formatInt: (value) => this.shell.localFormatInt(value),
      setPillState: (el, variant, text) => this.shell.setPillState(el, variant, text),
      setStatValue: (container, value) => this.shell.setStatValue(container, value),
      renderSpectrum: () => this.spectrum.renderSpectrum(),
      renderSpeedReadout: () => this.shell.renderSpeedReadout(),
      renderCarSelectionWarning: () => this.shell.renderCarSelectionWarning(),
      sendSelection: () => this.transport.sendSelection(),
    });
    this.shell.attachFeatures(this.features);
    const transportPorts: UiTransportFeaturePorts = {
      updateClientSelection: () => this.features.realtime.updateClientSelection(),
      maybeRenderSensorsSettingsList: (force) => this.features.realtime.maybeRenderSensorsSettingsList(force),
      renderLoggingStatus: () => this.features.realtime.renderLoggingStatus(),
      renderStatus: (clientRow) => this.features.realtime.renderStatus(clientRow),
    };
    this.transport.attachPorts(transportPorts);
    this.startup = new UiStartupCoordinator({
      shell: this.shell,
      transport: this.transport,
      features: this.features,
      defaultViewId: DEFAULT_SHELL_VIEW_ID,
    });
  }

  start(): void {
    this.startup.start();
  }
}
