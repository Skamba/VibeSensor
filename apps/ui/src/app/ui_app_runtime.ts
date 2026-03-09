import { escapeHtml, fmt, fmtTs } from "../format";
import type { UiDomElements } from "./dom/ui_dom_registry";
import { createUiDomRegistry } from "./dom/ui_dom_registry";
import { createAppFeatureBundle, type AppFeatureBundle } from "./app_feature_bundle";
import type { AppState } from "./state/ui_app_state";
import { createAppState } from "./state/ui_app_state";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import { UiShellController } from "./runtime/ui_shell_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";

const CAR_MAP_WINDOW_MS = 10_000;
const DEFAULT_VIEW_ID = "dashboardView";

const CAR_MAP_POSITIONS: Record<string, { top: number; left: number }> = {
  front_left_wheel: { top: 22, left: 18 },
  front_right_wheel: { top: 22, left: 82 },
  rear_left_wheel: { top: 78, left: 18 },
  rear_right_wheel: { top: 78, left: 82 },
  engine_bay: { top: 28, left: 50 },
  front_subframe: { top: 14, left: 50 },
  rear_subframe: { top: 88, left: 50 },
  driveshaft_tunnel: { top: 52, left: 50 },
  transmission: { top: 40, left: 48 },
  driver_seat: { top: 44, left: 38 },
  front_passenger_seat: { top: 44, left: 62 },
  rear_left_seat: { top: 66, left: 30 },
  rear_center_seat: { top: 66, left: 50 },
  rear_right_seat: { top: 66, left: 70 },
  trunk: { top: 88, left: 50 },
};

export class UiAppRuntime {
  private readonly els: UiDomElements;

  private readonly state: AppState;

  private readonly features: AppFeatureBundle;

  private readonly shell: UiShellController;

  private readonly spectrum: UiSpectrumController;

  private readonly transport: UiLiveTransportController;

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
      fmt,
      fmtTs,
      formatInt: (value) => this.shell.localFormatInt(value),
      setPillState: (el, variant, text) => this.shell.setPillState(el, variant, text),
      setStatValue: (container, value) => this.shell.setStatValue(container, value),
      renderSpectrum: () => this.spectrum.renderSpectrum(),
      renderSpeedReadout: () => this.shell.renderSpeedReadout(),
      renderCarSelectionWarning: () => this.shell.renderCarSelectionWarning(),
      sendSelection: () => this.transport.sendSelection(),
      carMapPositions: CAR_MAP_POSITIONS,
      carMapWindowMs: CAR_MAP_WINDOW_MS,
    });
    this.shell.attachFeatures(this.features);
    this.transport.attachFeatures(this.features);
  }

  start(): void {
    this.shell.bindUiEvents();
    this.features.settings.syncSettingsInputs();
    this.runAsyncTask("hydrate persisted preferences", () => this.shell.hydratePersistedPreferences());
    this.shell.applyLanguage(false);
    this.shell.renderCarSelectionWarning();
    this.shell.setActiveView(DEFAULT_VIEW_ID);
    this.startBackgroundActivity();
    this.transport.startTransportMode();
  }

  private runAsyncTask(taskName: string, task: () => Promise<void>): void {
    void task().catch((error) => {
      console.warn(`UI startup task failed: ${taskName}`, error);
    });
  }

  private startBackgroundActivity(): void {
    this.runAsyncTask("refresh location options", () => this.features.realtime.refreshLocationOptions());
    this.runAsyncTask("load speed source", () => this.features.settings.loadSpeedSourceFromServer());
    this.runAsyncTask("load analysis settings", () => this.features.settings.loadAnalysisSettingsFromServer());
    this.runAsyncTask("load cars", () => this.features.settings.loadCarsFromServer());
    this.runAsyncTask("refresh logging status", () => this.features.realtime.refreshLoggingStatus());
    this.runAsyncTask("refresh history", () => this.features.history.refreshHistory());
    this.features.update.startPolling();
    this.features.espFlash.startPolling();
    this.features.settings.startGpsStatusPolling();
  }
}
