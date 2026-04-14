import type { ChartBand } from "../ui_app_state";
import type { SpectrumFocusMarker, SpectrumSeriesEntry } from "./spectrum_shared";
import { closestFrequencyIndex } from "./spectrum_shared";
import type {
  SpectrumLegendItemModel,
  SpectrumLegendState,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "./spectrum_panel_view";

export interface SpectrumInteractionSyncParams {
  entries: readonly SpectrumSeriesEntry[];
  freqAxis: readonly number[];
  chartBands: readonly ChartBand[];
}

export interface SpectrumInteractionControllerDeps {
  panel: SpectrumPanelView;
  t: (key: string, vars?: Record<string, unknown>) => string;
  getStrengthDb: (entryId: string) => number | null;
  getTopPeakHz: (entryId: string) => number | null;
  setSeriesIsolation: (seriesIndex: number | null) => void;
  requestPlotRefresh: () => void;
}

export interface SpectrumInteractionSyncOptions {
  applyPlotIsolation?: boolean;
}

export class SpectrumInteractionController {
  private currentEntries: readonly SpectrumSeriesEntry[] = [];

  private currentFreqAxis: readonly number[] = [];

  private currentBands: readonly ChartBand[] = [];

  private pinnedSeriesId: string | null = null;

  private cursorDataIdx: number | null = null;

  private bandsVisible = false;

  constructor(
    private readonly deps: SpectrumInteractionControllerDeps,
  ) {
    this.deps.panel.bindBandToggle(() => this.toggleBands());
    this.renderBandToggle();
  }

  sync(
    params: SpectrumInteractionSyncParams,
    options: SpectrumInteractionSyncOptions = {},
  ): void {
    this.currentEntries = params.entries;
    this.currentFreqAxis = params.freqAxis;
    this.currentBands = params.chartBands;
    if (
      this.cursorDataIdx !== null
      && (this.cursorDataIdx < 0 || this.cursorDataIdx >= this.currentFreqAxis.length)
    ) {
      this.cursorDataIdx = null;
    }
    if (!this.currentEntries.length || !this.currentBands.length) {
      this.bandsVisible = false;
    }
    this.renderBandToggle();
    if (options.applyPlotIsolation === false) {
      if (this.pinnedSeriesId && !this.currentEntries.some((entry) => entry.id === this.pinnedSeriesId)) {
        this.pinnedSeriesId = null;
      }
      this.renderSensorLegend();
      this.updateInspector();
      return;
    }
    this.applyPlotSelection();
  }

  applyPlotSelection(): void {
    if (this.pinnedSeriesId && !this.currentEntries.some((entry) => entry.id === this.pinnedSeriesId)) {
      this.pinnedSeriesId = null;
    }
    const activeIndex = this.pinnedSeriesId
      ? this.currentEntries.findIndex((entry) => entry.id === this.pinnedSeriesId)
      : -1;
    this.deps.setSeriesIsolation(activeIndex >= 0 ? activeIndex + 1 : null);
    this.renderSensorLegend();
    this.updateInspector();
  }

  setCursorDataIndex(cursorDataIdx: number | null): void {
    this.cursorDataIdx = cursorDataIdx;
    this.updateInspector();
  }

  getBandsVisible(): boolean {
    return this.bandsVisible;
  }

  getChartBands(): readonly ChartBand[] {
    return this.currentBands;
  }

  getFocusMarker(): SpectrumFocusMarker | null {
    const focusEntry = this.focusEntry();
    if (!focusEntry) {
      return null;
    }
    const peak = this.focusPeakInfo(focusEntry);
    if (!peak) {
      return null;
    }
    return {
      color: focusEntry.color,
      freq: peak.freq,
      value: peak.value,
    };
  }

  private toggleBands(): void {
    const hasBands = this.currentBands.length > 0 && this.currentEntries.length > 0;
    if (!hasBands) {
      this.bandsVisible = false;
      this.renderBandToggle();
      return;
    }
    this.bandsVisible = !this.bandsVisible;
    this.renderBandToggle();
    this.updateInspector();
    this.deps.requestPlotRefresh();
  }

  private renderBandToggle(): void {
    const hasBands = this.currentBands.length > 0 && this.currentEntries.length > 0;
    this.deps.panel.renderBandToggle({
      hasBands,
      bandsVisible: this.bandsVisible,
      text: this.deps.t(this.bandsVisible ? "spectrum.bands.hide" : "spectrum.bands.show"),
    });
  }

  private renderSensorLegend(): void {
    if (!this.currentEntries.length) {
      this.deps.panel.renderSensorLegend(null);
      return;
    }
    const allActive = this.pinnedSeriesId === null;
    const model: SpectrumSensorLegendModel = {
      reset: {
        labelText: this.deps.t("spectrum.legend.all_series"),
        titleText: this.deps.t("spectrum.legend.clear_focus"),
        ariaLabel: [
          this.deps.t("spectrum.legend.all_series"),
          allActive ? this.legendStateText("all-visible") : null,
        ].filter((value): value is string => Boolean(value)).join(". "),
        ariaPressed: allActive,
        active: allActive,
      },
      items: this.currentEntries.map((entry) => {
        const active = this.pinnedSeriesId === entry.id;
        const muted = this.pinnedSeriesId !== null && !active;
        const legendState: SpectrumLegendState = active
          ? "isolated"
          : muted
            ? "inactive"
            : "visible";
        const metric = this.deps.getStrengthDb(entry.id);
        const detailText = typeof metric === "number" && Number.isFinite(metric)
          ? this.deps.t("spectrum.legend.sensor_level", {
            value: this.formatDb(metric),
          })
          : this.legendStateText(legendState);
        return {
          id: entry.id,
          labelText: entry.label,
          color: entry.color,
          detailText,
          titleText: active
            ? this.deps.t("spectrum.legend.clear_focus")
            : this.deps.t("spectrum.legend.focus_series", { sensor: entry.label }),
          ariaLabel: [
            entry.label,
            this.legendStateText(legendState),
            typeof metric === "number" && Number.isFinite(metric)
              ? this.deps.t("spectrum.legend.sensor_level", {
                value: this.formatDb(metric),
              })
              : null,
          ].filter((value): value is string => Boolean(value)).join(". "),
          ariaPressed: active,
          active,
          muted,
        } satisfies SpectrumLegendItemModel;
      }),
    };
    this.deps.panel.renderSensorLegend(model, {
      onReset: () => {
        this.pinnedSeriesId = null;
        this.applyPlotSelection();
      },
      onSelect: (entryId) => {
        this.pinnedSeriesId = this.pinnedSeriesId === entryId ? null : entryId;
        this.applyPlotSelection();
      },
    });
  }

  private updateInspector(): void {
    const activeFreq = this.activeFrequency();
    const activeBands = activeFreq === null ? [] : this.activeBandsForFrequency(activeFreq);
    this.deps.panel.renderBandLegend({
      visible: this.bandsVisible && this.currentBands.length > 0 && this.currentEntries.length > 0,
      items: activeBands.map((band) => ({
        labelText: band.label,
        color: band.color,
      })),
      emptyText: this.deps.t("spectrum.bands.none"),
    });

    const focusEntry = this.focusEntry();
    if (!focusEntry) {
      this.deps.panel.renderInspectorText(this.deps.t("spectrum.inspector_idle"));
      return;
    }
    if (activeFreq !== null && this.cursorDataIdx !== null) {
      const currentValue = focusEntry.values[Math.min(this.cursorDataIdx, focusEntry.values.length - 1)];
      const valueText = typeof currentValue === "number" && Number.isFinite(currentValue)
        ? this.formatDb(currentValue)
        : "--";
      this.deps.panel.renderInspectorText(this.deps.t("spectrum.inspector_hover", {
        sensor: focusEntry.label,
        freq: this.formatHz(activeFreq),
        value: valueText,
        bands: this.bandSummaryText(activeBands),
      }));
      return;
    }
    const peak = this.focusPeakInfo(focusEntry);
    if (!peak) {
      this.deps.panel.renderInspectorText(this.deps.t("spectrum.inspector_idle"));
      return;
    }
    this.deps.panel.renderInspectorText(this.deps.t(
      this.pinnedSeriesId ? "spectrum.inspector_focus_selected" : "spectrum.inspector_focus_strongest",
      {
        sensor: focusEntry.label,
        freq: this.formatHz(peak.freq),
        value: this.formatDb(peak.value),
        bands: this.bandSummaryText(this.activeBandsForFrequency(peak.freq)),
      },
    ));
  }

  private activeBandsForFrequency(freqHz: number): ChartBand[] {
    return this.currentBands.filter((band) => freqHz >= band.min_hz && freqHz <= band.max_hz);
  }

  private bandSummaryText(bands: ChartBand[]): string {
    return bands.length
      ? bands.map((band) => band.label).join(", ")
      : this.deps.t("spectrum.inspector_no_band");
  }

  private activeFrequency(): number | null {
    if (
      this.cursorDataIdx !== null
      && this.cursorDataIdx >= 0
      && this.cursorDataIdx < this.currentFreqAxis.length
    ) {
      return this.currentFreqAxis[this.cursorDataIdx];
    }
    const focusEntry = this.focusEntry();
    const peak = focusEntry ? this.focusPeakInfo(focusEntry) : null;
    return peak?.freq ?? null;
  }

  private strongestEntry(): SpectrumSeriesEntry | null {
    let bestEntry: SpectrumSeriesEntry | null = null;
    let bestDb = Number.NEGATIVE_INFINITY;
    for (const entry of this.currentEntries) {
      const db = this.deps.getStrengthDb(entry.id);
      if (typeof db !== "number" || !Number.isFinite(db)) {
        continue;
      }
      if (db > bestDb) {
        bestDb = db;
        bestEntry = entry;
      }
    }
    return bestEntry;
  }

  private focusEntry(): SpectrumSeriesEntry | null {
    if (this.pinnedSeriesId) {
      const pinnedEntry = this.currentEntries.find((entry) => entry.id === this.pinnedSeriesId);
      if (pinnedEntry) {
        return pinnedEntry;
      }
    }
    return this.strongestEntry();
  }

  private focusPeakInfo(entry: SpectrumSeriesEntry): { freq: number; value: number } | null {
    const peakHz = this.deps.getTopPeakHz(entry.id);
    if (typeof peakHz !== "number" || !Number.isFinite(peakHz)) {
      return null;
    }
    const peakIndex = closestFrequencyIndex(this.currentFreqAxis, peakHz);
    if (peakIndex === null) {
      return null;
    }
    const value = entry.values[peakIndex];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return null;
    }
    return {
      freq: this.currentFreqAxis[peakIndex] ?? peakHz,
      value,
    };
  }

  private legendStateText(state: SpectrumLegendState): string {
    switch (state) {
      case "all-visible":
        return this.deps.t("spectrum.legend.state_all_visible");
      case "visible":
        return this.deps.t("spectrum.legend.state_visible");
      case "isolated":
        return this.deps.t("spectrum.legend.state_isolated");
      case "inactive":
        return this.deps.t("spectrum.legend.state_inactive");
    }
  }

  private formatHz(value: number): string {
    return value >= 100 ? value.toFixed(0) : value.toFixed(1);
  }

  private formatDb(value: number): string {
    return value.toFixed(1);
  }
}
