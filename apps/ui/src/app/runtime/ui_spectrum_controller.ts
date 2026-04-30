import type { AppState } from "../ui_app_state";
import { computed, effectOnChange, untracked } from "../ui_signals";
import {
  createSpectrumCanvasRenderer,
  type SpectrumCanvasRenderer,
  type SpectrumPreparedRenderData,
} from "./spectrum_canvas_renderer";
import {
  createInlineSpectrumFramePreparer,
  type SpectrumFramePreparer,
  type SpectrumFramePreparationInput,
} from "./spectrum_frame_preparer";
import { SpectrumInteractionController } from "./spectrum_interaction_controller";
import type { SpectrumPanelView } from "./spectrum_panel_view";

type UiSpectrumControllerDeps = {
  state: AppState;
  panel: SpectrumPanelView;
  t: (key: string, vars?: Record<string, unknown>) => string;
  framePreparer?: SpectrumFramePreparer;
};

export class UiSpectrumController {
  private readonly panel: SpectrumPanelView;

  private readonly interaction: SpectrumInteractionController;

  private readonly canvas: SpectrumCanvasRenderer;

  private readonly framePreparer: SpectrumFramePreparer;

  private readonly disposeLanguageSync: () => void;

  private readonly disposeSpectraSync: () => void;

  private readonly disposeTransportOverlaySync: () => void;

  private disposed = false;

  private framePreparationRunning = false;

  private requestedSpectrumVersion = 0;

  private processedSpectrumVersion = 0;

  constructor(private readonly deps: UiSpectrumControllerDeps) {
    this.panel = this.deps.panel;
    this.framePreparer =
      this.deps.framePreparer ?? createInlineSpectrumFramePreparer();
    this.canvas = createSpectrumCanvasRenderer({
      state: this.state,
      dom: this.panel.chartDom,
      t: this.t,
      getBandsVisible: () => this.interaction.getBandsVisible(),
      getChartBands: () => this.interaction.getChartBands(),
      getFocusMarker: () => this.interaction.getFocusMarker(),
      onCursorDataIndexChange: (cursorDataIdx) =>
        this.interaction.setCursorDataIndex(cursorDataIdx),
      onAsyncChartUpdate: () => {
        this.interaction.applyPlotSelection();
        this.updateSpectrumOverlay();
      },
    });
    this.interaction = new SpectrumInteractionController({
      panel: this.panel,
      t: this.t,
      getStrengthDb: (entryId) =>
        this.state.spectrum.spectra.value.clients[entryId]?.strength_metrics
          ?.vibration_strength_db ?? null,
      getTopPeakHz: (entryId) =>
        this.state.spectrum.spectra.value.clients[entryId]?.strength_metrics
          ?.top_peaks?.[0]?.hz ?? null,
      setSeriesIsolation: (seriesIndex) =>
        this.canvas.setSeriesIsolation(seriesIndex),
      requestPlotRefresh: () => this.canvas.refreshDecorations(),
    });
    this.bindInteractionModelSignals();
    this.renderSpectrumHeader();
    this.updateSpectrumOverlay();
    this.disposeSpectraSync = this.bindReactiveTransportSync();
    this.disposeLanguageSync = this.bindReactiveLanguageSync();
    this.disposeTransportOverlaySync = this.bindReactiveOverlaySync();
  }

  private get state(): AppState {
    return this.deps.state;
  }

  private get t(): (key: string, vars?: Record<string, unknown>) => string {
    return this.deps.t;
  }

  updateSpectrumOverlay(): void {
    this.setSpectrumOverlay(this.spectrumOverlayModel());
  }

  private renderSpectrumHeader(): void {
    this.panel.renderHeader({
      titleText: this.t("chart.spectrum_title"),
      hintText: this.t("spectrum.controls_hint"),
    });
  }

  private applyPreparedSpectrum(
    prepared: SpectrumPreparedRenderData,
    mode: "data" | "decorations",
  ): void {
    this.state.spectrum.chartBands.value = prepared.chartBands;
    this.state.spectrum.hasSpectrumData.value = prepared.hasData;
    this.interaction.sync(
      {
        entries: prepared.entries,
        freqAxis: prepared.freqAxis,
        chartBands: prepared.chartBands,
      },
      { applyPlotIsolation: false },
    );
    if (mode === "data") {
      this.canvas.renderPreparedFrame(prepared);
    } else {
      this.canvas.refreshDecorations();
    }
    this.interaction.applyPlotSelection();
    this.updateSpectrumOverlay();
  }

  renderSpectrum(): void {
    this.renderSpectrumHeader();
    this.requestedSpectrumVersion += 1;
    if (this.framePreparationRunning) {
      return;
    }
    this.framePreparationRunning = true;
    void this.preparePendingSpectrumFrames();
  }

  refreshSpectrumDecorations(): void {
    this.renderSpectrumHeader();
    const prepared = this.canvas.refreshPreparedFrameMetadata();
    this.applyPreparedSpectrum(prepared, "decorations");
  }

  dispose(): void {
    this.disposed = true;
    this.disposeTransportOverlaySync();
    this.disposeSpectraSync();
    this.disposeLanguageSync();
    this.framePreparer.dispose();
    this.interaction.dispose();
    this.canvas.dispose();
  }

  private spectrumOverlayModel(): { hidden: boolean; text: string } {
    let message: string | null = null;
    if (this.state.spectrum.chartLoadErrorDetail.value) {
      message = this.t("spectrum.chart_load_error", {
        message: this.state.spectrum.chartLoadErrorDetail.value,
      });
    } else if (this.state.spectrum.framePrepareErrorDetail.value) {
      message = this.t("spectrum.frame_prepare_error", {
        message: this.state.spectrum.framePrepareErrorDetail.value,
      });
    } else if (this.state.transport.payloadError.value) {
      message = this.state.transport.payloadError.value;
    } else if (
      !this.state.transport.hasReceivedPayload.value &&
      this.state.transport.wsState.value === "connecting"
    ) {
      message = this.t("spectrum.loading");
    } else if (
      this.state.transport.wsState.value === "connecting" ||
      this.state.transport.wsState.value === "reconnecting"
    ) {
      message = this.t("ws.connecting");
    } else if (this.state.transport.wsState.value === "stale") {
      message = this.t("spectrum.stale");
    } else if (
      this.state.spectrum.chartLoading.value &&
      this.state.spectrum.hasSpectrumData.value
    ) {
      message = this.t("spectrum.loading");
    } else if (!this.state.spectrum.hasSpectrumData.value) {
      message = this.t("spectrum.empty");
    }
    return {
      hidden: message === null,
      text: message ?? "Waiting for sensor data...",
    };
  }

  private setSpectrumOverlay(model: { hidden: boolean; text: string }): void {
    this.panel.renderOverlay(model);
  }

  private bindInteractionModelSignals(): void {
    this.panel.bindBandToggleModel(this.interaction.bandToggleModel);
    this.panel.bindSensorLegendModel(
      this.interaction.sensorLegendModel,
      this.interaction.sensorLegendHandlersModel,
    );
    this.panel.bindBandLegendModel(this.interaction.bandLegendModel);
  }

  private bindReactiveLanguageSync(): () => void {
    return effectOnChange(this.state.shell.lang, () => {
      untracked(() => {
        this.renderSpectrumHeader();
        this.updateSpectrumOverlay();
      });
    });
  }

  private bindReactiveTransportSync(): () => void {
    return effectOnChange(this.state.spectrum.spectra, () => {
      untracked(() => this.renderSpectrum());
    });
  }

  private bindReactiveOverlaySync(): () => void {
    const transportOverlayState = computed(() => ({
      hasReceivedPayload: this.state.transport.hasReceivedPayload.value,
      framePrepareErrorDetail:
        this.state.spectrum.framePrepareErrorDetail.value,
      payloadError: this.state.transport.payloadError.value,
      wsState: this.state.transport.wsState.value,
    }));
    return effectOnChange(transportOverlayState, () => {
      untracked(() => this.updateSpectrumOverlay());
    });
  }

  private buildFramePreparationInput(): SpectrumFramePreparationInput {
    return {
      clients: this.state.realtime.clients.value.map((client) => ({
        id: client.id,
        name: client.name,
        connected: client.connected,
      })),
      spectraByClient: this.state.spectrum.spectra.value.clients,
    };
  }

  private async preparePendingSpectrumFrames(): Promise<void> {
    try {
      while (
        !this.disposed &&
        this.processedSpectrumVersion < this.requestedSpectrumVersion
      ) {
        const version = this.requestedSpectrumVersion;
        this.state.spectrum.framePrepareErrorDetail.value = null;
        try {
          const frameData = await this.framePreparer.prepare(
            this.buildFramePreparationInput(),
          );
          if (this.disposed) {
            return;
          }
          if (version !== this.requestedSpectrumVersion) {
            continue;
          }
          this.processedSpectrumVersion = version;
          const prepared = this.canvas.composePreparedFrame(frameData);
          this.applyPreparedSpectrum(prepared, "data");
        } catch (error: unknown) {
          if (this.disposed) {
            return;
          }
          if (version !== this.requestedSpectrumVersion) {
            continue;
          }
          this.processedSpectrumVersion = version;
          this.state.spectrum.framePrepareErrorDetail.value =
            getFramePrepareErrorDetail(error);
          this.updateSpectrumOverlay();
        }
      }
    } finally {
      this.framePreparationRunning = false;
      if (
        !this.disposed &&
        this.processedSpectrumVersion < this.requestedSpectrumVersion
      ) {
        this.framePreparationRunning = true;
        void this.preparePendingSpectrumFrames();
      }
    }
  }
}

function getFramePrepareErrorDetail(error: unknown): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  if (typeof error === "string" && error.trim().length > 0) {
    return error;
  }
  return "Unknown error";
}
