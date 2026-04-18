import type uPlot from "uplot";

import { SPECTRUM_TWEEN_DURATION_MS } from "../../config";
import { convertSpectrumAmplitudesToDbInPlace } from "../../spectrum";
import type { SpectrumSeriesMeta, SpectrumText } from "../../spectrum_chart";
import { getSpectrumCssVars } from "../../spectrum_css_vars";
import { chartSeriesPalette, orderBandFills } from "../../theme";
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
import type { SpectrumPanelChartDom } from "./spectrum_panel_view";
import { closestFrequencyIndex, freqGridsMatch, type SpectrumFocusMarker, type SpectrumSeriesEntry } from "./spectrum_shared";

type SpectrumChartModule = Pick<typeof import("../../spectrum_chart"), "createSpectrumChart">;
const EMPTY_FREQ_AXIS: number[] = [];
const EMPTY_SERIES_VALUES: number[][] = [];

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
  freqAxis: number[];
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
  prepareFrame(): SpectrumPreparedRenderData;
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
  const currentFreqAxis = signal<readonly number[]>([]);
  const chartSeriesMeta = signal<readonly SpectrumSeriesMeta[]>([]);
  const chartData = signal<uPlot.AlignedData>([[]]);
  const chartHeight = signal(360);
  const chartPlugins = signal<readonly uPlot.Plugin[]>([]);
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
            setSpectrumDataFromFrame(frame);
          }
        },
        onComplete: () => {
          untracked(() => setSpectrumDataFromFrame(to));
        },
      });
      anim.start();
      return anim.stop;
    });
  }

  function prepareFrame(): SpectrumPreparedRenderData {
    const entries: SpectrumSeriesEntry[] = [];
    let targetFreq: number[] = [];

    for (const [index, client] of deps.state.realtime.clients.value.entries()) {
      if (!client?.connected) {
        continue;
      }
      const spectrum = deps.state.spectrum.spectra.value.clients?.[client.id];
      if (!spectrum || !Array.isArray(spectrum.combined)) {
        continue;
      }
      const clientFreq = Array.isArray(spectrum.freq) && spectrum.freq.length
        ? spectrum.freq
        : EMPTY_FREQ_AXIS;
      const length = Math.min(clientFreq.length, spectrum.combined.length);
      if (!length) {
        continue;
      }

      let blended: number[];
      let needsInterpolation = false;
      if (!targetFreq.length) {
        targetFreq = clientFreq.length === length ? clientFreq : clientFreq.slice(0, length);
        blended = spectrum.combined.length === length
          ? spectrum.combined
          : spectrum.combined.slice(0, length);
      } else {
        needsInterpolation = clientFreq.length !== targetFreq.length
          || !freqGridsMatch(clientFreq, targetFreq, length);
        if (needsInterpolation) {
          blended = interpolateToTarget(clientFreq, spectrum.combined, targetFreq, length);
        } else {
          blended = spectrum.combined.length === length
            ? spectrum.combined
            : spectrum.combined.slice(0, length);
        }
      }
      if (!blended.length) {
        continue;
      }
      if (!needsInterpolation && blended === spectrum.combined) {
        blended = blended.slice();
      }
      convertSpectrumAmplitudesToDbInPlace(blended);

      entries.push({
        id: client.id,
        label: client.name || client.id,
        color: colorForClient(index),
        values: blended,
      });
    }

    const chartBands = calculateBands();
    if (!targetFreq.length || !entries.length) {
      return {
        entries: [],
        freqAxis: [],
        chartBands,
        frame: null,
        hasData: false,
      };
    }

    let minLen = targetFreq.length;
    const seriesIds = new Array<string>(entries.length);
    const frameValues = new Array<number[]>(entries.length);
    for (let index = 0; index < entries.length; index += 1) {
      const entry = entries[index];
      seriesIds[index] = entry.id;
      frameValues[index] = entry.values;
      if (entry.values.length < minLen) {
        minLen = entry.values.length;
      }
    }
    if (minLen < targetFreq.length) {
      targetFreq = targetFreq.slice(0, minLen);
      for (let index = 0; index < frameValues.length; index += 1) {
        if (frameValues[index]!.length === minLen) {
          continue;
        }
        const trimmedValues = frameValues[index]!.slice(0, minLen);
        frameValues[index] = trimmedValues;
        entries[index]!.values = trimmedValues;
      }
    }
    const frame: SpectrumHeavyFrame = {
      seriesIds,
      freq: targetFreq,
      values: frameValues,
    };

    return {
      entries,
      freqAxis: frame.freq,
      chartBands,
      frame,
      hasData: true,
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
    chartData.value = buildChartData(
      prepared.frame?.freq ?? prepared.freqAxis,
      prepared.frame?.values ?? EMPTY_SERIES_VALUES,
    );

    if (!prepared.frame) {
      tweenTarget.value = null;
      currentEntries.value = [];
      currentFreqAxis.value = [];
      spectrumLastFrame.value = null;
      pendingPreparedFrame.value = null;
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
      setSpectrumDataFromFrame(nextFrame);
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
    const freqAxis = currentFreqAxis.value;
    const entries = currentEntries.value;
    if (!freqAxis.length || !entries.length) {
      return;
    }
    chartData.value = buildChartDataWithClonedFreqAxis(freqAxis, entries);
  }

  function setSeriesIsolation(seriesIndex: number | null): void {
    if (disposed) {
      return;
    }
    deps.state.spectrum.spectrumPlot.value?.setSeriesIsolation(seriesIndex);
  }

  function colorForClient(index: number): string {
    return chartSeriesPalette[index % chartSeriesPalette.length];
  }

  function setSpectrumDataFromFrame(frame: SpectrumHeavyFrame): void {
    if (!deps.state.spectrum.spectrumPlot.value) {
      return;
    }
    currentFreqAxis.value = frame.freq;
    chartData.value = buildChartData(frame.freq, frame.values);
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
    for (let index = 0; index < entries.length; index += 1) {
      const entry = entries[index]!;
      nextMeta[index] = {
        label: entry.label,
        color: entry.color,
      };
    }
    chartSeriesMeta.value = nextMeta;
  }

  function buildChartData(freqAxis: number[], seriesValues: readonly number[][]): uPlot.AlignedData {
    const alignedData = new Array(seriesValues.length + 1) as uPlot.AlignedData;
    alignedData[0] = freqAxis;
    for (let index = 0; index < seriesValues.length; index += 1) {
      alignedData[index + 1] = seriesValues[index]!;
    }
    return alignedData;
  }

  function buildChartDataWithClonedFreqAxis(
    freqAxis: readonly number[],
    entries: readonly SpectrumSeriesEntry[],
  ): uPlot.AlignedData {
    const alignedData = new Array(entries.length + 1) as uPlot.AlignedData;
    alignedData[0] = Array.from(freqAxis);
    for (let index = 0; index < entries.length; index += 1) {
      alignedData[index + 1] = entries[index]!.values;
    }
    return alignedData;
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

  function createBandPlugin(): uPlot.Plugin {
    return {
      hooks: {
        setCursor: [
          (plot: uPlot) => {
            deps.onCursorDataIndexChange(
              typeof plot.cursor.idx === "number" && plot.cursor.idx >= 0
                ? plot.cursor.idx
                : null,
            );
          },
        ],
        draw: [
          (plot: uPlot) => {
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
    prepareFrame,
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

function interpolateToTarget(
  sourceFreq: readonly number[],
  sourceVals: readonly number[],
  desiredFreq: readonly number[],
  sourceLen: number,
): number[] {
  if (sourceLen < 2 || !desiredFreq.length) {
    return [];
  }
  const output = new Array<number>(desiredFreq.length);
  let index = 0;
  for (let desiredIndex = 0; desiredIndex < desiredFreq.length; desiredIndex += 1) {
    const freq = desiredFreq[desiredIndex];
    while (index + 1 < sourceLen && sourceFreq[index + 1] < freq) {
      index += 1;
    }
    if (index + 1 >= sourceLen) {
      output[desiredIndex] = sourceVals[sourceLen - 1];
      continue;
    }
    const f0 = sourceFreq[index];
    const f1 = sourceFreq[index + 1];
    const v0 = sourceVals[index];
    const v1 = sourceVals[index + 1];
    output[desiredIndex] = f1 <= f0 ? v0 : v0 + ((v1 - v0) * ((freq - f0) / (f1 - f0)));
  }
  return output;
}
