import type { AppState } from "../ui_app_state";
import { computed, effectOnChange, untracked } from "../ui_signals";
import {
  createSpectrumCanvasRenderer,
  type SpectrumCanvasRenderer,
} from "./spectrum_canvas_renderer";
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
    this.canvas = createSpectrumCanvasRenderer({
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
        this.state.spectrum.spectra.value.clients[entryId]?.strength_metrics?.vibration_strength_db
        ?? null,
      getTopPeakHz: (entryId) =>
        this.state.spectrum.spectra.value.clients[entryId]?.strength_metrics?.top_peaks?.[0]?.hz
        ?? null,
      setSeriesIsolation: (seriesIndex) => this.canvas.setSeriesIsolation(seriesIndex),
      requestPlotRefresh: () => this.canvas.refreshDecorations(),
    });
    this.bindInteractionModelSignals();
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
    this.state.spectrum.chartBands.value = prepared.chartBands;
    this.state.spectrum.hasSpectrumData.value = prepared.hasData;
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
    if (this.state.spectrum.chartLoadErrorDetail.value) {
      return this.t("spectrum.chart_load_error", {
        message: this.state.spectrum.chartLoadErrorDetail.value,
      });
    }
    if (this.state.transport.payloadError.value) {
      return this.state.transport.payloadError.value;
    }
    if (
      !this.state.transport.hasReceivedPayload.value
      && this.state.transport.wsState.value === "connecting"
    ) {
      return this.t("spectrum.loading");
    }
    if (
      this.state.transport.wsState.value === "connecting"
      || this.state.transport.wsState.value === "reconnecting"
    ) {
      return this.t("ws.connecting");
    }
    if (this.state.transport.wsState.value === "stale") {
      return this.t("spectrum.stale");
    }
    if (this.state.spectrum.chartLoading.value && this.state.spectrum.hasSpectrumData.value) {
      return this.t("spectrum.loading");
    }
    if (!this.state.spectrum.hasSpectrumData.value) {
      return this.t("spectrum.empty");
    }
    return null;
  }

  private setSpectrumOverlay(message: string | null): void {
    this.panel.renderOverlay(message);
  }

  private bindInteractionModelSignals(): void {
    this.panel.bindBandToggleModel(this.interaction.bandToggleModel);
    this.panel.bindSensorLegendModel(
      this.interaction.sensorLegendModel,
      this.interaction.sensorLegendHandlersModel,
    );
    this.panel.bindBandLegendModel(this.interaction.bandLegendModel);
  }

  private bindReactiveLanguageSync(): void {
    effectOnChange(this.state.shell.lang, () => {
      untracked(() => {
        this.renderSpectrumHeader();
        this.updateSpectrumOverlay();
      });
    });
  }

  private bindReactiveTransportSync(): void {
    effectOnChange(this.state.spectrum.spectra, () => {
      untracked(() => this.renderSpectrum());
    });
    const transportOverlayState = computed(() => ({
      hasReceivedPayload: this.state.transport.hasReceivedPayload.value,
      payloadError: this.state.transport.payloadError.value,
      wsState: this.state.transport.wsState.value,
    }));
    effectOnChange(transportOverlayState, () => {
      untracked(() => this.updateSpectrumOverlay());
    });
  }
}
