import { batch, computed, effect, signal, type ReadonlySignal } from "../ui_signals";
import type { ChartBand } from "../ui_app_state";
import type { SpectrumFocusMarker, SpectrumSeriesEntry } from "./spectrum_shared";
import { closestFrequencyIndex } from "./spectrum_shared";
import type {
  SpectrumBandLegendModel,
  SpectrumLegendItemModel,
  SpectrumLegendHandlers,
  SpectrumLegendState,
  SpectrumPanelBandToggleModel,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "./spectrum_panel_view";

type TimeoutHandle = ReturnType<typeof globalThis.setTimeout>;
const HOVER_INSPECTOR_THROTTLE_MS = 33;

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
  scheduleTimeout?: (callback: () => void, delayMs: number) => TimeoutHandle;
  cancelTimeout?: (handle: TimeoutHandle) => void;
  nowMs?: () => number;
}

export interface SpectrumInteractionSyncOptions {
  applyPlotIsolation?: boolean;
}

export class SpectrumInteractionController {
  private readonly currentEntries = signal<readonly SpectrumSeriesEntry[]>([]);

  private readonly currentFreqAxis = signal<readonly number[]>([]);

  private readonly currentBands = signal<readonly ChartBand[]>([]);

  private readonly pinnedSeriesId = signal<string | null>(null);

  private readonly cursorDataIdx = signal<number | null>(null);

  private readonly bandsVisible = signal(false);

  readonly bandToggleModel: ReadonlySignal<SpectrumPanelBandToggleModel>;

  readonly sensorLegendModel: ReadonlySignal<SpectrumSensorLegendModel | null>;

  readonly sensorLegendHandlersModel: ReadonlySignal<SpectrumLegendHandlers | null>;

  readonly bandLegendModel: ReadonlySignal<SpectrumBandLegendModel>;

  private readonly disposeInspectorSync: () => void;

  private readonly scheduleTimeout: (callback: () => void, delayMs: number) => TimeoutHandle;

  private readonly cancelTimeout: (handle: TimeoutHandle) => void;

  private readonly nowMs: () => number;

  private pendingHoverTimeoutHandle: TimeoutHandle | null = null;

  private pendingHoverInspectorText: string | null = null;

  private lastHoverInspectorCommitAtMs: number | null = null;

  private lastInspectorText: string | null = null;

  private lastAnnouncedInspectorText: string | null = null;

  constructor(
    private readonly deps: SpectrumInteractionControllerDeps,
  ) {
    this.scheduleTimeout = this.deps.scheduleTimeout ?? ((callback, delayMs) => globalThis.setTimeout(callback, delayMs));
    this.cancelTimeout = this.deps.cancelTimeout ?? ((handle) => globalThis.clearTimeout(handle));
    this.nowMs = this.deps.nowMs ?? (() => performance.now());
    this.bandToggleModel = computed(() => {
      const bands = this.currentBands.value;
      const entries = this.currentEntries.value;
      const visible = this.bandsVisible.value;
      const hasBands = bands.length > 0 && entries.length > 0;
      const pressed = hasBands && visible ? "true" : "false";
      return {
        hasBands,
        bandsVisible: visible,
        disabled: !hasBands,
        hidden: !hasBands,
        pressed,
        text: this.deps.t(visible ? "spectrum.bands.hide" : "spectrum.bands.show"),
      };
    });

    this.sensorLegendModel = computed(() => {
      const entries = this.currentEntries.value;
      const pinnedId = this.pinnedSeriesId.value;
      if (!entries.length) {
        return null;
      }
      const allActive = pinnedId === null;
      return {
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
        items: entries.map((entry) => {
          const active = pinnedId === entry.id;
          const muted = pinnedId !== null && !active;
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
      } satisfies SpectrumSensorLegendModel;
    });

    this.sensorLegendHandlersModel = computed(() =>
      this.sensorLegendModel.value === null
        ? null
        : {
          onReset: () => {
            this.pinnedSeriesId.value = null;
            this.applyPlotSelection();
          },
          onSelect: (entryId: string) => {
            this.pinnedSeriesId.value = this.pinnedSeriesId.value === entryId ? null : entryId;
            this.applyPlotSelection();
          },
        } satisfies SpectrumLegendHandlers
    );

    this.bandLegendModel = computed(() => {
      const activeFreq = this.activeFrequency();
      const activeBands = activeFreq === null ? [] : this.activeBandsForFrequency(activeFreq);
      return {
        visible: this.bandsVisible.value && this.currentBands.value.length > 0 && this.currentEntries.value.length > 0,
        items: activeBands.map((band) => ({
          labelText: band.label,
          color: band.color,
        })),
        emptyText: this.deps.t("spectrum.bands.none"),
      };
    });

    this.deps.panel.bindBandToggle(() => this.toggleBands());
    this.disposeInspectorSync = effect(() => {
      const activeFreq = this.activeFrequency();
      const activeBands = activeFreq === null ? [] : this.activeBandsForFrequency(activeFreq);
      const focusEntry = this.focusEntry();
      if (!focusEntry) {
        this.renderInspectorText(this.deps.t("spectrum.inspector_idle"), { announce: false });
        return;
      }
      const cursorIdx = this.cursorDataIdx.value;
      if (activeFreq !== null && cursorIdx !== null) {
        const currentValue = focusEntry.values[Math.min(cursorIdx, focusEntry.values.length - 1)];
        const valueText = typeof currentValue === "number" && Number.isFinite(currentValue)
          ? this.formatDb(currentValue)
          : "--";
        this.renderInspectorText(this.deps.t("spectrum.inspector_hover", {
          sensor: focusEntry.label,
          freq: this.formatHz(activeFreq),
          value: valueText,
          bands: this.bandSummaryText(activeBands),
        }), { announce: false, throttleHover: true });
        return;
      }
      const peak = this.focusPeakInfo(focusEntry);
      if (!peak) {
        this.renderInspectorText(this.deps.t("spectrum.inspector_idle"), { announce: false });
        return;
      }
      this.renderInspectorText(this.deps.t(
        this.pinnedSeriesId.value ? "spectrum.inspector_focus_selected" : "spectrum.inspector_focus_strongest",
        {
          sensor: focusEntry.label,
          freq: this.formatHz(peak.freq),
          value: this.formatDb(peak.value),
          bands: this.bandSummaryText(this.activeBandsForFrequency(peak.freq)),
        },
      ), { announce: true });
    });
  }

  dispose(): void {
    this.cancelPendingHoverInspector();
    this.disposeInspectorSync();
  }

  sync(
    params: SpectrumInteractionSyncParams,
    options: SpectrumInteractionSyncOptions = {},
  ): void {
    batch(() => {
      this.currentEntries.value = params.entries;
      this.currentFreqAxis.value = params.freqAxis;
      this.currentBands.value = params.chartBands;
      if (
        this.cursorDataIdx.value !== null
        && (this.cursorDataIdx.value < 0 || this.cursorDataIdx.value >= params.freqAxis.length)
      ) {
        this.cursorDataIdx.value = null;
      }
      if (!params.entries.length || !params.chartBands.length) {
        this.bandsVisible.value = false;
      }
      if (options.applyPlotIsolation === false) {
        if (this.pinnedSeriesId.value && !params.entries.some((entry) => entry.id === this.pinnedSeriesId.value)) {
          this.pinnedSeriesId.value = null;
        }
      }
    });
    if (options.applyPlotIsolation !== false) {
      this.applyPlotSelection();
    }
  }

  applyPlotSelection(): void {
    if (this.pinnedSeriesId.value && !this.currentEntries.value.some((entry) => entry.id === this.pinnedSeriesId.value)) {
      this.pinnedSeriesId.value = null;
    }
    const activeIndex = this.pinnedSeriesId.value
      ? this.currentEntries.value.findIndex((entry) => entry.id === this.pinnedSeriesId.value)
      : -1;
    this.deps.setSeriesIsolation(activeIndex >= 0 ? activeIndex + 1 : null);
  }

  setCursorDataIndex(cursorDataIdx: number | null): void {
    this.cursorDataIdx.value = cursorDataIdx;
  }

  getBandsVisible(): boolean {
    return this.bandsVisible.value;
  }

  getChartBands(): readonly ChartBand[] {
    return this.currentBands.value;
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
    const hasBands = this.currentBands.value.length > 0 && this.currentEntries.value.length > 0;
    if (!hasBands) {
      this.bandsVisible.value = false;
      return;
    }
    this.bandsVisible.value = !this.bandsVisible.value;
    this.deps.requestPlotRefresh();
  }

  private renderInspectorText(
    text: string,
    options: { announce: boolean; throttleHover?: boolean },
  ): void {
    if (options.throttleHover) {
      this.queueHoverInspectorText(text);
      return;
    }
    this.cancelPendingHoverInspector();
    this.commitInspectorText(text, options.announce);
  }

  private queueHoverInspectorText(text: string): void {
    this.pendingHoverInspectorText = text;
    const lastCommitAtMs = this.lastHoverInspectorCommitAtMs;
    const nowMs = this.nowMs();
    if (
      lastCommitAtMs === null
      || (nowMs - lastCommitAtMs) >= HOVER_INSPECTOR_THROTTLE_MS
    ) {
      this.flushPendingHoverInspector();
      return;
    }
    if (this.pendingHoverTimeoutHandle !== null) {
      return;
    }
    const delayMs = HOVER_INSPECTOR_THROTTLE_MS - (nowMs - lastCommitAtMs);
    this.pendingHoverTimeoutHandle = this.scheduleTimeout(() => {
      this.pendingHoverTimeoutHandle = null;
      this.flushPendingHoverInspector();
    }, delayMs);
  }

  private flushPendingHoverInspector(): void {
    const text = this.pendingHoverInspectorText;
    if (text === null) {
      return;
    }
    this.pendingHoverInspectorText = null;
    this.lastHoverInspectorCommitAtMs = this.nowMs();
    this.commitInspectorText(text, false);
  }

  private cancelPendingHoverInspector(): void {
    if (this.pendingHoverTimeoutHandle !== null) {
      this.cancelTimeout(this.pendingHoverTimeoutHandle);
      this.pendingHoverTimeoutHandle = null;
    }
    this.pendingHoverInspectorText = null;
  }

  private commitInspectorText(text: string, announce: boolean): void {
    const shouldAnnounce = announce && text !== this.lastAnnouncedInspectorText;
    if (text === this.lastInspectorText && !shouldAnnounce) {
      return;
    }
    this.deps.panel.renderInspector({
      text,
      announce: shouldAnnounce,
    });
    this.lastInspectorText = text;
    if (shouldAnnounce) {
      this.lastAnnouncedInspectorText = text;
    }
  }

  private activeBandsForFrequency(freqHz: number): ChartBand[] {
    return this.currentBands.value.filter((band) => freqHz >= band.min_hz && freqHz <= band.max_hz);
  }

  private bandSummaryText(bands: ChartBand[]): string {
    return bands.length
      ? bands.map((band) => band.label).join(", ")
      : this.deps.t("spectrum.inspector_no_band");
  }

  private activeFrequency(): number | null {
    const cursorIdx = this.cursorDataIdx.value;
    const freqAxis = this.currentFreqAxis.value;
    if (
      cursorIdx !== null
      && cursorIdx >= 0
      && cursorIdx < freqAxis.length
    ) {
      return freqAxis[cursorIdx];
    }
    const focusEntry = this.focusEntry();
    const peak = focusEntry ? this.focusPeakInfo(focusEntry) : null;
    return peak?.freq ?? null;
  }

  private strongestEntry(): SpectrumSeriesEntry | null {
    let bestEntry: SpectrumSeriesEntry | null = null;
    let bestDb = Number.NEGATIVE_INFINITY;
    for (const entry of this.currentEntries.value) {
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
    const pinnedId = this.pinnedSeriesId.value;
    if (pinnedId) {
      const pinnedEntry = this.currentEntries.value.find((entry) => entry.id === pinnedId);
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
    const freqAxis = this.currentFreqAxis.value;
    const peakIndex = closestFrequencyIndex(freqAxis, peakHz);
    if (peakIndex === null) {
      return null;
    }
    const value = entry.values[peakIndex];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return null;
    }
    return {
      freq: freqAxis[peakIndex] ?? peakHz,
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
