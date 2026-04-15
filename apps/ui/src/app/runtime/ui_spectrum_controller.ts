import type { AppState } from "../ui_app_state";
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

  renderSpectrum(): void {
    this.panel.renderHeader({
      titleText: this.t("chart.spectrum_title"),
      hintText: this.t("spectrum.controls_hint"),
    });
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
    if (!this.state.spectrum.hasSpectrumData) {
      return this.t("spectrum.empty");
    }
    return null;
  }

  private setSpectrumOverlay(message: string | null): void {
    this.panel.renderOverlay(message);
  }
}
