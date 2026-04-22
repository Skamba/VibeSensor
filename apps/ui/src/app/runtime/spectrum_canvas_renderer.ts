import { SPECTRUM_TWEEN_DURATION_MS } from "../../config";
import type {
  SpectrumAlignedData,
  SpectrumChartPlugin,
  SpectrumSeriesMeta,
  SpectrumText,
} from "../../spectrum_chart";
import { getSpectrumCssVars } from "../../spectrum_css_vars";
import { orderBandFills } from "../../theme";
import {
  createRafAnimation,
  type RafAnimation,
  type RafAnimationCallbacks,
} from "../dom/raf_animation";
import {
  createSpectrumTweenDerivedState,
  resolveSpectrumTweenDurationMs,
  type SpectrumHeavyFrame,
} from "../spectrum_animation";
import type { AppState, ChartBand } from "../ui_app_state";
import { computed, effect, signal, untracked, type ReadonlySignal } from "../ui_signals";
import type { SpectrumPreparedFrameData } from "./spectrum_frame_preparer";
import type { SpectrumPanelChartDom } from "./spectrum_panel_view";
import {
  closestFrequencyIndex,
  type SpectrumFocusMarker,
  type SpectrumNumericSeries,
  type SpectrumSeriesEntry,
} from "./spectrum_shared";

type SpectrumChartModule = Pick<typeof import("../../spectrum_chart"), "createSpectrumChart">;
const EMPTY_FREQ_AXIS: number[] = [];
const EMPTY_SERIES_VALUES: number[][] = [];
const EMPTY_CHART_DATA: SpectrumAlignedData = [[]];

const bandKeyPresentation: Record<string, { color: string; labelKey: string }> = {
  wheel_1x: { color: orderBandFills.wheel1, labelKey: "bands.wheel_1x" },
  wheel_2x: { color: orderBandFills.wheel2, labelKey: "bands.wheel_2x" },
  driveshaft_1x: { color: orderBandFills.driveshaft1, labelKey: "bands.driveshaft_1x" },
  engine_1x: { color: orderBandFills.engine1, labelKey: "bands.engine_1x" },
  engine_2x: { color: orderBandFills.engine2, labelKey: "bands.engine_2x" },
  driveshaft_engine_1x: {
    color: orderBandFills.driveshaftEngine1,
    labelKey: "bands.driveshaft_engine_1x",
  },
};

export interface SpectrumPreparedRenderData {
  entries: SpectrumSeriesEntry[];
  freqAxis: SpectrumNumericSeries;
  chartBands: ChartBand[];
  frame: SpectrumHeavyFrame | null;
  hasData: boolean;
}

export interface SpectrumCanvasRendererDeps {
  state: AppState;
  dom: SpectrumPanelChartDom;
  t: (key: string, vars?: Record<string, unknown>) => string;
  getBandsVisible: () => boolean;
  getChartBands: () => readonly ChartBand[];
  getFocusMarker: () => SpectrumFocusMarker | null;
  onCursorDataIndexChange: (cursorDataIdx: number | null) => void;
  onAsyncChartUpdate?: () => void;
  loadChartModule?: () => Promise<SpectrumChartModule>;
  createAnimation?: (callbacks: RafAnimationCallbacks) => RafAnimation;
  nowMs?: () => number;
}

export interface SpectrumCanvasRenderer {
  dispose(): void;
  composePreparedFrame(frameData: SpectrumPreparedFrameData): SpectrumPreparedRenderData;
  refreshPreparedFrameMetadata(): SpectrumPreparedRenderData;
  renderPreparedFrame(prepared: SpectrumPreparedRenderData): void;
  refreshDecorations(): void;
  setSeriesIsolation(seriesIndex: number | null): void;
}

export function createSpectrumCanvasRenderer(
  deps: SpectrumCanvasRendererDeps,
): SpectrumCanvasRenderer {
  const onAsyncChartUpdate = deps.onAsyncChartUpdate ?? (() => undefined);
  const loadChartModule = deps.loadChartModule ?? loadSpectrumChartModule;
  const createAnimation = deps.createAnimation ?? ((callbacks) => createRafAnimation(callbacks));
  const nowMs = deps.nowMs ?? (() => performance.now());

  let chartLoadPromise: Promise<void> | null = null;
  let disposed = false;
  let lastAcceptedFrameAtMs: number | null = null;
  let lastPreparedFrame: SpectrumPreparedRenderData | null = null;

  const spectrumLastFrame = signal<SpectrumHeavyFrame | null>(null);
  const pendingPreparedFrame = signal<SpectrumPreparedRenderData | null>(null);
  const chartModule = signal<SpectrumChartModule | null>(null);

  const tweenAlpha = signal(1);
  const tweenDurationMs = signal(SPECTRUM_TWEEN_DURATION_MS);
  const tweenFromFrame = signal<SpectrumHeavyFrame | null>(null);
  const tweenToFrame = signal<SpectrumHeavyFrame | null>(null);
  const tweenState = createSpectrumTweenDerivedState(
    tweenFromFrame,
    tweenToFrame,
    tweenAlpha,
  );

  const tweenTarget = signal<SpectrumHeavyFrame | null>(null);
  const currentEntries = signal<readonly SpectrumSeriesEntry[]>([]);
  const currentFreqAxis = signal<SpectrumNumericSeries>(EMPTY_FREQ_AXIS);
  const chartSeriesMeta = signal<readonly SpectrumSeriesMeta[]>([]);
  const chartData = signal<SpectrumAlignedData>(EMPTY_CHART_DATA);
  const chartHeight = signal(360);
  const chartPlugins = signal<readonly SpectrumChartPlugin[]>([]);
  const chartText: ReadonlySignal<SpectrumText> = computed(() => ({
    title: deps.t("chart.spectrum_title"),
    axisHz: deps.t("chart.axis.hz"),
    axisAmplitude: deps.t("chart.axis.amplitude"),
  }));

  const spectrumBandPlugin = createBandPlugin();
  chartPlugins.value = [spectrumBandPlugin];
  const disposeTweenEffect = initTweenEffect();

  function initTweenEffect(): () => void {
    return effect(() => {
      const to = tweenTarget.value;
      const durationMs = tweenDurationMs.value;
      if (!to || durationMs <= 0) return;
      const anim = createAnimation({
        durationMs,
        onFrame: (alpha) => {
          tweenAlpha.value = alpha;
          const frame = tweenState.frame.value;
          if (frame) {
            setSpectrumDataFromFrame(frame, { resetScales: false });
          }
        },
        onComplete: () => {
          untracked(() => setSpectrumDataFromFrame(to, { resetScales: true }));
        },
      });
      anim.start();
      return anim.stop;
    });
  }

  function composePreparedFrame(frameData: SpectrumPreparedFrameData): SpectrumPreparedRenderData {
    return {
      entries: frameData.entries,
      freqAxis: frameData.freqAxis,
      chartBands: calculateBands(),
      frame: frameData.frame,
      hasData: frameData.hasData,
    };
  }

  function renderPreparedFrame(prepared: SpectrumPreparedRenderData): void {
    if (disposed) {
      return;
    }
    lastPreparedFrame = prepared;
    pendingPreparedFrame.value = prepared;
    currentEntries.value = prepared.entries;
    currentFreqAxis.value = prepared.freqAxis;
    syncChartSeriesMeta(prepared.entries);
    syncChartDataBuffer(
      prepared.frame?.freq ?? prepared.freqAxis,
      prepared.frame?.values ?? EMPTY_SERIES_VALUES,
    );

    if (!prepared.frame) {
      tweenTarget.value = null;
      currentEntries.value = [];
      currentFreqAxis.value = [];
      spectrumLastFrame.value = null;
      pendingPreparedFrame.value = null;
      deps.state.spectrum.spectrumPlot.value?.setData(chartData.value, false);
      return;
    }

    if (!ensureSpectrumPlot()) {
      return;
    }

    const nextFrame = prepared.frame;
    const renderAtMs = nowMs();
    const previousFrameAtMs = lastAcceptedFrameAtMs;
    lastAcceptedFrameAtMs = renderAtMs;
    tweenFromFrame.value = spectrumLastFrame.value;
    tweenToFrame.value = nextFrame;
    tweenTarget.value = null; // cancel any in-flight animation
    const tweenDurationForFrameMs = resolveSpectrumTweenDurationMs(
      SPECTRUM_TWEEN_DURATION_MS,
      previousFrameAtMs === null ? null : renderAtMs - previousFrameAtMs,
    );
    const canTween = deps.state.transport.wsState.value === "connected"
      && tweenState.canTween.value;
    if (!canTween || !spectrumLastFrame.value || tweenDurationForFrameMs <= 0) {
      setSpectrumDataFromFrame(nextFrame, { resetScales: true });
      return;
    }

    tweenAlpha.value = 0;
    tweenDurationMs.value = tweenDurationForFrameMs;
    tweenTarget.value = nextFrame; // triggers RAF effect
  }

  function refreshPreparedFrameMetadata(): SpectrumPreparedRenderData {
    const chartBands = calculateBands();
    if (!lastPreparedFrame) {
      return {
        entries: [],
        freqAxis: [],
        chartBands,
        frame: null,
        hasData: false,
      };
    }
    const refreshed = {
      ...lastPreparedFrame,
      chartBands,
    };
    lastPreparedFrame = refreshed;
    return refreshed;
  }

  function refreshDecorations(): void {
    if (disposed) {
      return;
    }
    if (!currentFreqAxis.value.length || !currentEntries.value.length) {
      return;
    }
    deps.state.spectrum.spectrumPlot.value?.redraw(false, false);
  }

  function setSeriesIsolation(seriesIndex: number | null): void {
    if (disposed) {
      return;
    }
    deps.state.spectrum.spectrumPlot.value?.setSeriesIsolation(seriesIndex);
  }

  function setSpectrumDataFromFrame(
    frame: SpectrumHeavyFrame,
    options: { resetScales: boolean },
  ): void {
    const plot = deps.state.spectrum.spectrumPlot.value;
    if (!plot) {
      return;
    }
    currentFreqAxis.value = frame.freq;
    syncChartDataBuffer(frame.freq, frame.values);
    plot.setData(chartData.value, options.resetScales);
    // uPlot does not commit a paint when setData() skips scale recalculation.
    // Tween frames reuse fixed axes, so explicitly rebuild paths and redraw.
    if (!options.resetScales) {
      plot.redraw(true, false);
    }
    spectrumLastFrame.value = frame;
  }

  function syncChartSeriesMeta(entries: readonly SpectrumSeriesEntry[]): void {
    const currentMeta = chartSeriesMeta.value;
    if (currentMeta.length === entries.length) {
      let changed = false;
      for (let index = 0; index < entries.length; index += 1) {
        if (
          currentMeta[index]?.label !== entries[index]?.label
          || currentMeta[index]?.color !== entries[index]?.color
        ) {
          changed = true;
          break;
        }
      }
      if (!changed) {
        return;
      }
    }

    const nextMeta = new Array<SpectrumSeriesMeta>(entries.length);
    for (const [index, entry] of entries.entries()) {
      nextMeta[index] = {
        label: entry.label,
        color: entry.color,
      };
    }
    chartSeriesMeta.value = nextMeta;
  }

  function syncChartDataBuffer(
    freqAxis: SpectrumNumericSeries,
    seriesValues: readonly SpectrumNumericSeries[],
  ): void {
    if (freqAxis.length === 0 || seriesValues.length === 0) {
      chartData.value = EMPTY_CHART_DATA;
      return;
    }
    const currentData = chartData.value;
    const nextSeriesCount = seriesValues.length + 1;
    const canReuse = currentData.length === nextSeriesCount
      && currentData[0]?.length === freqAxis.length
      && seriesValues.every((seriesValuesEntry, index) => currentData[index + 1]?.length === seriesValuesEntry.length);

    if (!canReuse) {
      const nextData = new Array(nextSeriesCount) as SpectrumAlignedData;
      nextData[0] = Array.from(freqAxis);
      for (const [index, seriesValuesEntry] of seriesValues.entries()) {
        nextData[index + 1] = Array.from(seriesValuesEntry);
      }
      chartData.value = nextData;
      return;
    }

    copyNumbersInto(currentData[0] as number[], freqAxis);
    for (const [index, seriesValuesEntry] of seriesValues.entries()) {
      copyNumbersInto(currentData[index + 1] as number[], seriesValuesEntry);
    }
  }

  function copyNumbersInto(target: number[], source: SpectrumNumericSeries): void {
    for (let index = 0; index < source.length; index += 1) {
      const value = source[index];
      if (value === undefined) {
        continue;
      }
      target[index] = value;
    }
  }

  function calculateBandsFromBackend(): ChartBand[] | null {
    const bands = deps.state.realtime.rotationalSpeeds.value?.order_bands;
    if (!Array.isArray(bands) || !bands.length) {
      return null;
    }
    const output: ChartBand[] = [];
    for (const band of bands) {
      const center = Number(band.center_hz);
      const tolerance = Number(band.tolerance);
      if (!Number.isFinite(center) || center <= 0 || !Number.isFinite(tolerance)) {
        continue;
      }
      const presentation = bandKeyPresentation[band.key];
      output.push({
        label: deps.t(presentation?.labelKey ?? band.key),
        min_hz: Math.max(0, center * (1 - tolerance)),
        max_hz: center * (1 + tolerance),
        color: presentation?.color ?? orderBandFills.wheel1,
      });
    }
    return output.length ? output : null;
  }

  function calculateBands(): ChartBand[] {
    return calculateBandsFromBackend() ?? [];
  }

  function createBandPlugin(): SpectrumChartPlugin {
    return {
      hooks: {
        setCursor: [
          (plot) => {
            deps.onCursorDataIndexChange(
              typeof plot.cursor.idx === "number" && plot.cursor.idx >= 0
                ? plot.cursor.idx
                : null,
            );
          },
        ],
        draw: [
          (plot) => {
            const top = plot.bbox.top;
            const height = plot.bbox.height;
            if (deps.getBandsVisible()) {
              for (const band of deps.getChartBands()) {
                if (!(band.max_hz > band.min_hz)) {
                  continue;
                }
                const x1 = plot.valToPos(band.min_hz, "x", true);
                const x2 = plot.valToPos(band.max_hz, "x", true);
                plot.ctx.save();
                plot.ctx.fillStyle = band.color;
                plot.ctx.fillRect(x1, top, Math.max(1, x2 - x1), height);
                plot.ctx.strokeStyle = band.color;
                plot.ctx.lineWidth = 1;
                plot.ctx.strokeRect(x1, top, Math.max(1, x2 - x1), height);
                plot.ctx.restore();
              }
            }

            const focusMarker = deps.getFocusMarker();
            if (!focusMarker) {
              return;
            }
            const freqAxis = currentFreqAxis.value;
            const peakIndex = closestFrequencyIndex(freqAxis, focusMarker.freq);
            if (peakIndex === null) {
              return;
            }
            const x = plot.valToPos(freqAxis[peakIndex], "x", true);
            const y = plot.valToPos(focusMarker.value, "y", true);
            const label = `${formatHz(focusMarker.freq)} Hz`;
            const labelPaddingX = 6;
            const labelHeight = 20;
            const labelTop = top + 8;
            const cssVars = getSpectrumCssVars();
            plot.ctx.save();
            plot.ctx.setLineDash([5, 4]);
            plot.ctx.strokeStyle = focusMarker.color;
            plot.ctx.lineWidth = 1.5;
            plot.ctx.beginPath();
            plot.ctx.moveTo(x, top);
            plot.ctx.lineTo(x, top + height);
            plot.ctx.stroke();
            plot.ctx.setLineDash([]);
            plot.ctx.fillStyle = focusMarker.color;
            plot.ctx.beginPath();
            plot.ctx.arc(x, y, 4, 0, Math.PI * 2);
            plot.ctx.fill();
            plot.ctx.font = "12px system-ui, sans-serif";
            const labelWidth = plot.ctx.measureText(label).width + (labelPaddingX * 2);
            const labelLeft = Math.max(
              plot.bbox.left,
              Math.min(x - (labelWidth / 2), plot.bbox.left + plot.bbox.width - labelWidth),
            );
            plot.ctx.fillStyle = cssVars.tooltipBg;
            plot.ctx.fillRect(labelLeft, labelTop, labelWidth, labelHeight);
            plot.ctx.fillStyle = cssVars.tooltipFg;
            plot.ctx.textBaseline = "middle";
            plot.ctx.fillText(label, labelLeft + labelPaddingX, labelTop + (labelHeight / 2));
            plot.ctx.restore();
          },
        ],
      },
    };
  }

  function createSpectrumPlot(loadedChartModule: SpectrumChartModule): void {
    if (disposed) {
      return;
    }
    tweenTarget.value = null;
    spectrumLastFrame.value = null;
    lastAcceptedFrameAtMs = null;
    lastPreparedFrame = null;
    if (deps.state.spectrum.spectrumPlot.value) {
      deps.state.spectrum.spectrumPlot.value.destroy();
      deps.state.spectrum.spectrumPlot.value = null;
    }
    deps.state.spectrum.spectrumPlot.value = loadedChartModule.createSpectrumChart({
      hostEl: deps.dom.specChart,
      measureEl: deps.dom.specChartWrap,
      height: chartHeight,
      seriesMeta: chartSeriesMeta,
      data: chartData,
      text: chartText,
      plugins: chartPlugins,
    });
  }

  function ensureSpectrumPlot(): boolean {
    if (disposed) {
      return false;
    }
    if (deps.state.spectrum.spectrumPlot.value) {
      deps.state.spectrum.chartLoadErrorDetail.value = null;
      return true;
    }
    if (chartModule.value) {
      deps.state.spectrum.chartLoading.value = false;
      deps.state.spectrum.chartLoadErrorDetail.value = null;
      createSpectrumPlot(chartModule.value);
      return deps.state.spectrum.spectrumPlot.value !== null;
    }
    if (chartLoadPromise) {
      return false;
    }

    deps.state.spectrum.chartLoading.value = true;
    deps.state.spectrum.chartLoadErrorDetail.value = null;
    chartLoadPromise = loadChartModule()
      .then((module) => {
        if (disposed) {
          return;
        }
        chartModule.value = module;
        const latestPrepared = pendingPreparedFrame.value;
        if (!latestPrepared?.frame) {
          return;
        }
        createSpectrumPlot(module);
        const rerender = latestPrepared;
        pendingPreparedFrame.value = null;
        renderPreparedFrame(rerender);
      })
      .catch((error: unknown) => {
        if (disposed) {
          return;
        }
        deps.state.spectrum.chartLoadErrorDetail.value = getChartLoadErrorDetail(error);
      })
      .finally(() => {
        if (disposed) {
          return;
        }
        deps.state.spectrum.chartLoading.value = false;
        chartLoadPromise = null;
        onAsyncChartUpdate();
      });

    return false;
  }

  function formatHz(value: number): string {
    return value >= 100 ? value.toFixed(0) : value.toFixed(1);
  }

  return {
    composePreparedFrame,
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      disposeTweenEffect();
      tweenTarget.value = null;
      pendingPreparedFrame.value = null;
      if (deps.state.spectrum.spectrumPlot.value) {
        deps.state.spectrum.spectrumPlot.value.destroy();
        deps.state.spectrum.spectrumPlot.value = null;
      }
      deps.state.spectrum.chartLoading.value = false;
    },
    refreshPreparedFrameMetadata,
    renderPreparedFrame,
    refreshDecorations,
    setSeriesIsolation,
  };
}

let spectrumChartModulePromise: Promise<SpectrumChartModule> | null = null;

function loadSpectrumChartModule(): Promise<SpectrumChartModule> {
  if (!spectrumChartModulePromise) {
    spectrumChartModulePromise = import("../../spectrum_chart");
  }
  return spectrumChartModulePromise;
}

function getChartLoadErrorDetail(error: unknown): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  if (typeof error === "string" && error.trim().length > 0) {
    return error;
  }
  return "Unknown error";
}
