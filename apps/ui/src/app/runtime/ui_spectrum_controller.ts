import { trackAppStateSlice, type AppState } from "../ui_app_state";
import { effect, untracked } from "../ui_signals";
import { SpectrumCanvasRenderer } from "./spectrum_canvas_renderer";
import { SpectrumInteractionController } from "./spectrum_interaction_controller";
import type { SpectrumPanelView } from "./spectrum_panel_view";

type UiSpectrumControllerDeps = {
  state: AppState;
  panel: SpectrumPanelView;
  t: (key: string, vars?: Record<string, unknown>) => string;
};

export class UiSpectrumController {
  private readonly panel: SpectrumPanelView;

  private readonly interaction: SpectrumInteractionController;

  private readonly canvas: SpectrumCanvasRenderer;

  constructor(
    private readonly deps: UiSpectrumControllerDeps,
  ) {
    this.panel = this.deps.panel;
    this.canvas = new SpectrumCanvasRenderer({
      state: this.state,
      dom: this.panel.chartDom,
      t: this.t,
      getBandsVisible: () => this.interaction.getBandsVisible(),
      getChartBands: () => this.interaction.getChartBands(),
      getFocusMarker: () => this.interaction.getFocusMarker(),
      onCursorDataIndexChange: (cursorDataIdx) => this.interaction.setCursorDataIndex(cursorDataIdx),
      onAsyncChartUpdate: () => {
        this.interaction.applyPlotSelection();
        this.updateSpectrumOverlay();
      },
    });
    this.interaction = new SpectrumInteractionController({
      panel: this.panel,
      t: this.t,
      getStrengthDb: (entryId) =>
        this.state.spectrum.spectra.clients[entryId]?.strength_metrics?.vibration_strength_db
        ?? null,
      getTopPeakHz: (entryId) =>
        this.state.spectrum.spectra.clients[entryId]?.strength_metrics?.top_peaks?.[0]?.hz
        ?? null,
      setSeriesIsolation: (seriesIndex) => this.canvas.setSeriesIsolation(seriesIndex),
      requestPlotRefresh: () => this.canvas.refreshDecorations(),
    });
    this.renderSpectrumHeader();
    this.updateSpectrumOverlay();
    this.bindReactiveTransportSync();
    this.bindReactiveLanguageSync();
  }

  private get state(): AppState {
    return this.deps.state;
  }

  private get t(): (key: string, vars?: Record<string, unknown>) => string {
    return this.deps.t;
  }

  updateSpectrumOverlay(): void {
    this.setSpectrumOverlay(this.spectrumOverlayMessage());
  }

  private renderSpectrumHeader(): void {
    this.panel.renderHeader({
      titleText: this.t("chart.spectrum_title"),
      hintText: this.t("spectrum.controls_hint"),
    });
  }

  renderSpectrum(): void {
    this.renderSpectrumHeader();
    const prepared = this.canvas.prepareFrame();
    this.state.spectrum.chartBands = prepared.chartBands;
    this.state.spectrum.hasSpectrumData = prepared.hasData;
    this.interaction.sync({
      entries: prepared.entries,
      freqAxis: prepared.freqAxis,
      chartBands: prepared.chartBands,
    }, { applyPlotIsolation: false });
    this.canvas.renderPreparedFrame(prepared);
    this.interaction.applyPlotSelection();
    this.updateSpectrumOverlay();
  }

  private spectrumOverlayMessage(): string | null {
    if (this.state.spectrum.chartLoadErrorDetail) {
      return this.t("spectrum.chart_load_error", {
        message: this.state.spectrum.chartLoadErrorDetail,
      });
    }
    if (this.state.transport.payloadError) {
      return this.state.transport.payloadError;
    }
    if (!this.state.transport.hasReceivedPayload && this.state.transport.wsState === "connecting") {
      return this.t("spectrum.loading");
    }
    if (
      this.state.transport.wsState === "connecting"
      || this.state.transport.wsState === "reconnecting"
    ) {
      return this.t("ws.connecting");
    }
    if (this.state.transport.wsState === "stale") {
      return this.t("spectrum.stale");
    }
    if (this.state.spectrum.chartLoading && this.state.spectrum.hasSpectrumData) {
      return this.t("spectrum.loading");
    }
    if (!this.state.spectrum.hasSpectrumData) {
      return this.t("spectrum.empty");
    }
    return null;
  }

  private setSpectrumOverlay(message: string | null): void {
    this.panel.renderOverlay(message);
  }

  private bindReactiveLanguageSync(): void {
    let initialized = false;
    let previousLanguage = this.state.shell.lang;
    effect(() => {
      trackAppStateSlice(this.state.shell);
      const currentLanguage = this.state.shell.lang;
      if (!initialized) {
        initialized = true;
        previousLanguage = currentLanguage;
        return;
      }
      if (currentLanguage === previousLanguage) {
        return;
      }
      previousLanguage = currentLanguage;
      untracked(() => {
        if (this.state.spectrum.spectrumPlot) {
          this.state.spectrum.spectrumPlot.destroy();
          this.state.spectrum.spectrumPlot = null;
          this.renderSpectrum();
          return;
        }
        this.renderSpectrumHeader();
        this.updateSpectrumOverlay();
      });
    });
  }

  private bindReactiveTransportSync(): void {
    let previousSpectra = this.state.spectrum.spectra;
    let previousWsState = this.state.transport.wsState;
    let previousPayloadError = this.state.transport.payloadError;
    let previousHasReceivedPayload = this.state.transport.hasReceivedPayload;
    let initialized = false;
    effect(() => {
      trackAppStateSlice(this.state.spectrum);
      trackAppStateSlice(this.state.transport);
      const nextSpectra = this.state.spectrum.spectra;
      const nextWsState = this.state.transport.wsState;
      const nextPayloadError = this.state.transport.payloadError;
      const nextHasReceivedPayload = this.state.transport.hasReceivedPayload;
      if (!initialized) {
        initialized = true;
        previousSpectra = nextSpectra;
        previousWsState = nextWsState;
        previousPayloadError = nextPayloadError;
        previousHasReceivedPayload = nextHasReceivedPayload;
        return;
      }
      const spectraChanged = nextSpectra !== previousSpectra;
      const transportChanged =
        nextWsState !== previousWsState
        || nextPayloadError !== previousPayloadError
        || nextHasReceivedPayload !== previousHasReceivedPayload;
      previousSpectra = nextSpectra;
      previousWsState = nextWsState;
      previousPayloadError = nextPayloadError;
      previousHasReceivedPayload = nextHasReceivedPayload;
      if (spectraChanged) {
        untracked(() => this.renderSpectrum());
        return;
      }
      if (transportChanged) {
        untracked(() => this.updateSpectrumOverlay());
      }
    });
  }
}
