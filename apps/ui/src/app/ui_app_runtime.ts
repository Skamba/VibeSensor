import { escapeHtml, fmt, fmtTs } from "../format";
import {
  createAppFeatureBundle,
  type AppFeatureBundle,
} from "./app_feature_bundle";
import type { AppState } from "./ui_app_state";
import { createAppState } from "./ui_app_state";
import { createUiRuntimeDom, type UiRuntimeDom } from "./ui_runtime_dom";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import {
  createUiShellChromeActionBridge,
  type UiShellChromeActionBridge,
} from "./runtime/ui_shell_chrome";
import { DEFAULT_SHELL_VIEW_ID } from "./runtime/ui_shell_navigation_module";
import { UiShellController } from "./runtime/ui_shell_controller";
import {
  createNullSpectrumPanelView,
  type SpectrumPanelView,
} from "./runtime/spectrum_panel_view";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { UiStartupCoordinator } from "./runtime/ui_startup_coordinator";
import {
  createNullHistoryPanelView,
  type HistoryPanelView,
} from "./views/history_table_view";
import type { InternetPanelView } from "./views/internet_panel";
import {
  createNullRealtimeLoggingPanelBridge,
  type RealtimeLoggingPanelBridge,
} from "./views/realtime_logging_panel";
import {
  createNullRealtimeLiveOverviewBridge,
  type RealtimeLiveOverviewBridge,
} from "./views/realtime_live_overview";
import type { CarsPanelView } from "./views/cars_panel";
import type { AnalysisPanelView } from "./views/analysis_panel";
import type { SensorsPanelView } from "./views/sensors_panel";
import type { SpeedSourcePanelView } from "./views/speed_source_panel";

export class UiAppRuntime {
  private readonly dom: UiRuntimeDom;

  private readonly state: AppState;

  private readonly featurePorts: AppFeatureBundle;

  private readonly shell: UiShellController;

  private readonly spectrum: UiSpectrumController;

  private readonly transport: UiLiveTransportController;

  private readonly startup: UiStartupCoordinator;

  constructor(
    dom: UiRuntimeDom = createUiRuntimeDom(),
    state: AppState = createAppState(),
    shellChromeActions: UiShellChromeActionBridge = createUiShellChromeActionBridge(),
    liveOverview: RealtimeLiveOverviewBridge = createNullRealtimeLiveOverviewBridge(),
    spectrumPanel: SpectrumPanelView = createNullSpectrumPanelView(),
    loggingPanel: RealtimeLoggingPanelBridge = createNullRealtimeLoggingPanelBridge(),
    historyPanel: HistoryPanelView = createNullHistoryPanelView(),
    carsPanel: CarsPanelView,
    analysisPanel: AnalysisPanelView,
    internetPanel: InternetPanelView,
    sensorsPanel: SensorsPanelView,
    speedSourcePanel: SpeedSourcePanelView,
  ) {
    this.dom = dom;
    this.state = state;
    this.shell = new UiShellController({
      state: this.state,
      dom: this.dom.shell,
      chromeActions: shellChromeActions,
      liveOverview,
    });
    this.spectrum = new UiSpectrumController({
      state: this.state,
      dom: this.dom.spectrum,
      panel: spectrumPanel,
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
    this.featurePorts = createAppFeatureBundle({
      state: this.state,
      dom: {
        shell: this.dom.shell,
        realtime: this.dom.realtime,
        history: this.dom.history,
        settings: this.dom.settings,
        cars: this.dom.cars,
        update: this.dom.update,
        espFlash: this.dom.espFlash,
      },
      shared: {
        t: (key, vars) => this.shell.t(key, vars),
        escapeHtml,
        showError: (message) => this.shell.showError(message),
        fmt,
        fmtTs,
        formatInt: (value) => this.shell.localFormatInt(value),
      },
      runtime: {
        analysisPanel,
        carsPanel,
        internetPanel,
        sensorsPanel,
        speedSourcePanel,
        realtimeChrome: {
          setPillState: (el, variant, text) =>
            this.shell.setPillState(el, variant, text),
          liveOverview,
          loggingPanel,
        },
        historyPanel,
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
