import { escapeHtml, fmt, fmtTs } from "../format";
import { createAppFeatureBundle, type AppFeatureBundle } from "./app_feature_bundle";
import type { AppState } from "./ui_app_state";
import { createAppState } from "./ui_app_state";
import { createUiRuntimeDom, type UiRuntimeDom } from "./ui_runtime_dom";
import { UiLiveTransportController, type UiTransportFeaturePorts } from "./runtime/ui_live_transport_controller";
import { DEFAULT_SHELL_VIEW_ID } from "./runtime/ui_shell_navigation_module";
import type { UiShellFeaturePorts } from "./runtime/ui_shell_feature_ports";
import { UiShellController } from "./runtime/ui_shell_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";

export class UiAppRuntime {
  private readonly dom: UiRuntimeDom;

  private readonly state: AppState;

  private readonly features: AppFeatureBundle;

  private readonly shell: UiShellController;

  private readonly spectrum: UiSpectrumController;

  private readonly transport: UiLiveTransportController;

  private readonly startup: UiStartupCoordinator;

  constructor(
    dom: UiRuntimeDom = createUiRuntimeDom(),
    state: AppState = createAppState(),
  ) {
    this.dom = dom;
    this.state = state;
    this.shell = new UiShellController({
      state: this.state,
      dom: this.dom.shell,
    });
    this.spectrum = new UiSpectrumController({
      state: this.state,
      dom: this.dom.spectrum,
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
      shellDom: this.dom.shell,
      realtimeDom: this.dom.realtime,
      historyDom: this.dom.history,
      settingsDom: this.dom.settings,
      carsDom: this.dom.cars,
      updateDom: this.dom.update,
      espFlashDom: this.dom.espFlash,
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
      sendSelection: () => this.transport.sendSelection(),
    });
    const shellPorts: UiShellFeaturePorts = {
      bindSettingsHandlers: () => this.features.settings.bindHandlers(),
      bindCarWizardHandlers: () => this.features.cars.bindWizardHandlers(),
      bindRealtimeHandlers: () => this.features.realtime.bindHandlers(),
      bindHistoryHandlers: () => this.features.history.bindHandlers(),
      bindUpdateHandlers: () => this.features.update.bindUpdateHandlers(),
      bindEspFlashHandlers: () => this.features.espFlash.bindHandlers(),
      languageRefresh: {
        realtime: {
          buildLocationOptions: (codes) => this.features.realtime.buildLocationOptions(codes),
          maybeRenderSensorsSettingsList: (force) => this.features.realtime.maybeRenderSensorsSettingsList(force),
          renderLoggingStatus: () => this.features.realtime.renderLoggingStatus(),
          renderStatus: () => this.features.realtime.renderStatus(),
        },
        history: {
          renderHistoryTable: () => this.features.history.renderHistoryTable(),
          reloadExpandedRunOnLanguageChange: () => this.features.history.reloadExpandedRunOnLanguageChange(),
        },
        settings: {
          syncSettingsInputs: () => this.features.settings.syncSettingsInputs(),
        },
      },
    };
    this.shell.attachPorts(shellPorts);
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
