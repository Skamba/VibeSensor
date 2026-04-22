import { spectrumDbDisplayRangeFromDataBounds } from "./spectrum";
import { getSpectrumCssVars } from "./spectrum_css_vars";
import {
  computed,
  effect,
  signal,
  type ReadonlySignal,
} from "./app/ui_signals";

export interface SpectrumSeriesMeta {
  label: string;
  color: string;
}

export interface SpectrumText {
  title: string;
  axisHz: string;
  axisAmplitude: string;
}

export type SpectrumAlignedData = number[][];

export interface SpectrumChartSeriesState {
  show: boolean;
}

export interface SpectrumChartPluginContext {
  readonly bbox: {
    height: number;
    left: number;
    top: number;
    width: number;
  };
  readonly ctx: CanvasRenderingContext2D;
  readonly cursor: {
    idx: number | null;
  };
  readonly series: readonly SpectrumChartSeriesState[];
  batch(run: () => void): void;
  setSeries(index: number, options: { show: boolean }, redraw?: boolean): void;
  valToPos(value: number, scale: "x" | "y", canvasPixels?: boolean): number;
}

export interface SpectrumChartPlugin {
  hooks?: {
    draw?: ReadonlyArray<(plot: SpectrumChartPluginContext) => void>;
    setCursor?: ReadonlyArray<(plot: SpectrumChartPluginContext) => void>;
  };
}

export interface SpectrumChart {
  destroy(): void;
  redraw(rebuildPaths?: boolean, recalcAxes?: boolean): void;
  resize(): void;
  setData(data: SpectrumAlignedData, resetScales?: boolean): void;
  setSeriesIsolation(seriesIdx: number | null): void;
}

export interface CreateSpectrumChartDeps {
  hostEl: HTMLElement;
  measureEl?: HTMLElement | null;
  height?: ReadonlySignal<number>;
  seriesMeta: ReadonlySignal<readonly SpectrumSeriesMeta[]>;
  data: ReadonlySignal<SpectrumAlignedData>;
  text: ReadonlySignal<SpectrumText>;
  plugins?: ReadonlySignal<readonly SpectrumChartPlugin[]>;
}

const DEFAULT_HEIGHT = 360;
const EMPTY_DATA: SpectrumAlignedData = [[]];
const HOVER_POINT_RADIUS = 4;
const X_TICK_COUNT = 6;
const Y_TICK_COUNT = 6;

type ChartRange = {
  max: number;
  min: number;
};

type ChartState = {
  plugins: readonly SpectrumChartPlugin[];
  text: SpectrumText;
};

export function createSpectrumChart(deps: CreateSpectrumChartDeps): SpectrumChart {
  const measureEl = deps.measureEl ?? deps.hostEl;
  const height = deps.height ?? signal(DEFAULT_HEIGHT);
  const plugins = deps.plugins ?? computed<readonly SpectrumChartPlugin[]>(() => []);
  const width = signal(computeWidth(measureEl));
  const canvas = document.createElement("canvas");
  const cssVars = getSpectrumCssVars();
  const ctx = requireCanvasContext(canvas);
  const cursorState = { idx: null as number | null };
  const seriesState: SpectrumChartSeriesState[] = [{ show: true }];
  let batching = 0;
  let chartState: ChartState = {
    plugins: plugins.value,
    text: deps.text.value,
  };
  let currentData = normalizeData(deps.data.value);
  let currentXRange: ChartRange | null = null;
  let currentYRange: ChartRange | null = null;
  let currentBbox = createChartBox(width.value, height.value);
  let disposed = false;
  let forceAxesRecalc = true;

  canvas.className = "spectrum-canvas";
  canvas.style.display = "block";
  canvas.style.height = "100%";
  canvas.style.width = "100%";
  canvas.style.touchAction = "none";
  deps.hostEl.replaceChildren(canvas);

  const plotContext: SpectrumChartPluginContext = {
    get bbox() {
      return currentBbox;
    },
    get ctx() {
      return ctx;
    },
    get cursor() {
      return cursorState;
    },
    get series() {
      return seriesState;
    },
    batch(run) {
      batching += 1;
      try {
        run();
      } finally {
        batching -= 1;
        if (batching === 0) {
          renderChart(forceAxesRecalc);
        }
      }
    },
    setSeries(index, options, redraw = true) {
      if (index < 0 || index >= seriesState.length) {
        return;
      }
      seriesState[index] = { show: options.show };
      if (redraw && batching === 0) {
        renderChart(true);
      }
    },
    valToPos(value, scale) {
      if (scale === "x") {
        return projectValue(value, currentXRange ?? { min: 0, max: 1 }, currentBbox.left, currentBbox.width);
      }
      return projectValue(
        value,
        currentYRange ?? { min: -120, max: 0 },
        currentBbox.top + currentBbox.height,
        -currentBbox.height,
      );
    },
  };

  function syncSeriesVisibility(seriesMeta: readonly SpectrumSeriesMeta[]): void {
    const nextLength = seriesMeta.length + 1;
    if (seriesState.length === nextLength) {
      return;
    }
    const nextState = new Array<SpectrumChartSeriesState>(nextLength);
    nextState[0] = { show: true };
    for (let index = 1; index < nextLength; index += 1) {
      nextState[index] = { show: seriesState[index]?.show ?? true };
    }
    seriesState.splice(0, seriesState.length, ...nextState);
  }

  function recalculateRanges(): void {
    const freqAxis = currentData[0] ?? [];
    const xMin = freqAxis[0] ?? 0;
    const xMax = freqAxis[freqAxis.length - 1] ?? Math.max(1, xMin);
    currentXRange = {
      min: xMin,
      max: xMax > xMin ? xMax : xMin + 1,
    };

    let dataMin = Number.POSITIVE_INFINITY;
    let dataMax = Number.NEGATIVE_INFINITY;
    let sawValue = false;
    const visibleSeries = getVisibleSeriesIndexes();
    const sourceIndexes = visibleSeries.length
      ? visibleSeries
      : Array.from({ length: Math.max(0, currentData.length - 1) }, (_, index) => index + 1);
    for (const seriesIndex of sourceIndexes) {
      const series = currentData[seriesIndex];
      if (!series) {
        continue;
      }
      for (const value of series) {
        if (!Number.isFinite(value)) {
          continue;
        }
        sawValue = true;
        dataMin = Math.min(dataMin, value);
        dataMax = Math.max(dataMax, value);
      }
    }
    if (!sawValue) {
      currentYRange = { min: -120, max: 0 };
      return;
    }
    const [min, max] = spectrumDbDisplayRangeFromDataBounds(dataMin, dataMax);
    currentYRange = {
      min,
      max: max > min ? max : min + 1,
    };
  }

  function resizeCanvas(cssWidth: number, cssHeight: number): void {
    const dpr = window.devicePixelRatio || 1;
    const renderWidth = Math.max(1, Math.floor(cssWidth));
    const renderHeight = Math.max(1, Math.floor(cssHeight));
    canvas.width = Math.max(1, Math.floor(renderWidth * dpr));
    canvas.height = Math.max(1, Math.floor(renderHeight * dpr));
    canvas.style.width = `${renderWidth}px`;
    canvas.style.height = `${renderHeight}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    currentBbox = createChartBox(renderWidth, renderHeight);
  }

  function clearCanvas(cssWidth: number, cssHeight: number): void {
    ctx.clearRect(0, 0, cssWidth, cssHeight);
  }

  function getVisibleSeriesIndexes(): number[] {
    const indexes: number[] = [];
    for (let index = 1; index < seriesState.length; index += 1) {
      if (seriesState[index]?.show !== false) {
        indexes.push(index);
      }
    }
    return indexes;
  }

  function drawAxes(): void {
    if (!currentXRange || !currentYRange) {
      return;
    }
    const { left, top, width: plotWidth, height: plotHeight } = currentBbox;
    ctx.save();
    ctx.strokeStyle = cssVars.border;
    ctx.fillStyle = cssVars.muted;
    ctx.lineWidth = 1;
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";

    for (const value of buildTickValues(currentXRange, X_TICK_COUNT)) {
      const x = plotContext.valToPos(value, "x");
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, top + plotHeight);
      ctx.stroke();
      ctx.fillText(formatHzTick(value), x, top + plotHeight + 6);
    }

    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const value of buildTickValues(currentYRange, Y_TICK_COUNT)) {
      const y = plotContext.valToPos(value, "y");
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + plotWidth, y);
      ctx.stroke();
      ctx.fillText(formatDbTick(value), left - 8, y);
    }

    ctx.fillStyle = cssVars.muted;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(chartState.text.axisHz, left + (plotWidth / 2), top + plotHeight + 28);
    ctx.save();
    ctx.translate(14, top + (plotHeight / 2));
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(chartState.text.axisAmplitude, 0, 0);
    ctx.restore();
    ctx.restore();
  }

  function drawSeries(): void {
    if (!currentXRange || !currentYRange) {
      return;
    }
    const freqAxis = currentData[0] ?? [];
    if (freqAxis.length === 0) {
      return;
    }
    ctx.save();
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.lineWidth = 2;
    for (const seriesIndex of getVisibleSeriesIndexes()) {
      const series = currentData[seriesIndex];
      const meta = deps.seriesMeta.value[seriesIndex - 1];
      if (!series || !meta || series.length === 0) {
        continue;
      }
      ctx.beginPath();
      let started = false;
      for (let index = 0; index < Math.min(freqAxis.length, series.length); index += 1) {
        const x = plotContext.valToPos(freqAxis[index] ?? 0, "x");
        const y = plotContext.valToPos(series[index] ?? 0, "y");
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.strokeStyle = meta.color;
      ctx.stroke();
    }
    ctx.restore();
    drawHoverMarker();
  }

  function drawHoverMarker(): void {
    if (cursorState.idx == null || !currentXRange || !currentYRange) {
      return;
    }
    const freqAxis = currentData[0] ?? [];
    const hoverFreq = freqAxis[cursorState.idx];
    if (!Number.isFinite(hoverFreq)) {
      return;
    }
    const seriesIndex = getVisibleSeriesIndexes()[0];
    const series = seriesIndex == null ? null : currentData[seriesIndex];
    const hoverValue = series?.[cursorState.idx] ?? null;
    const x = plotContext.valToPos(hoverFreq, "x");
    ctx.save();
    ctx.strokeStyle = cssVars.muted;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, currentBbox.top);
    ctx.lineTo(x, currentBbox.top + currentBbox.height);
    ctx.stroke();
    ctx.setLineDash([]);
    if (hoverValue != null && Number.isFinite(hoverValue)) {
      const y = plotContext.valToPos(hoverValue, "y");
      ctx.fillStyle = cssVars.surface;
      ctx.strokeStyle = cssVars.muted;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x, y, HOVER_POINT_RADIUS, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  function runPluginHooks(hook: keyof NonNullable<SpectrumChartPlugin["hooks"]>): void {
    for (const plugin of chartState.plugins) {
      for (const callback of plugin.hooks?.[hook] ?? []) {
        callback(plotContext);
      }
    }
  }

  function renderChart(recalcAxes: boolean): void {
    if (disposed) {
      return;
    }
    forceAxesRecalc = recalcAxes;
    if (batching > 0) {
      return;
    }
    const cssWidth = Math.max(320, Math.floor(width.value));
    const cssHeight = Math.max(240, Math.floor(height.value));
    resizeCanvas(cssWidth, cssHeight);
    if (recalcAxes || currentXRange === null || currentYRange === null) {
      recalculateRanges();
      forceAxesRecalc = false;
    }
    clearCanvas(cssWidth, cssHeight);
    drawAxes();
    drawSeries();
    runPluginHooks("draw");
  }

  function updateCursorIndex(nextIndex: number | null): void {
    if (cursorState.idx === nextIndex) {
      return;
    }
    cursorState.idx = nextIndex;
    runPluginHooks("setCursor");
    renderChart(false);
  }

  function handlePointerMove(event: PointerEvent): void {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (
      x < currentBbox.left
      || x > currentBbox.left + currentBbox.width
      || y < currentBbox.top
      || y > currentBbox.top + currentBbox.height
    ) {
      updateCursorIndex(null);
      return;
    }
    updateCursorIndex(findClosestIndex(currentData[0] ?? [], x, currentXRange, currentBbox));
  }

  function handlePointerLeave(): void {
    updateCursorIndex(null);
  }

  canvas.addEventListener("pointermove", handlePointerMove);
  canvas.addEventListener("pointerleave", handlePointerLeave);

  const stopResizeObserver = effect(() => {
    width.value = computeWidth(measureEl);
    const resizeObserver = new ResizeObserver(() => {
      width.value = computeWidth(measureEl);
    });
    resizeObserver.observe(measureEl);
    return () => {
      resizeObserver.disconnect();
    };
  });

  const stopConfigSync = effect(() => {
    chartState = {
      plugins: Array.from(plugins.value),
      text: deps.text.value,
    };
    syncSeriesVisibility(deps.seriesMeta.value);
    renderChart(true);
  });

  return {
    destroy(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      stopConfigSync();
      stopResizeObserver();
      canvas.removeEventListener("pointermove", handlePointerMove);
      canvas.removeEventListener("pointerleave", handlePointerLeave);
      deps.hostEl.replaceChildren();
    },
    redraw(_rebuildPaths?: boolean, recalcAxes?: boolean): void {
      renderChart(Boolean(recalcAxes));
    },
    resize(): void {
      width.value = computeWidth(measureEl);
      renderChart(true);
    },
    setData(data: SpectrumAlignedData, resetScales = true): void {
      currentData = normalizeData(data);
      renderChart(resetScales);
    },
    setSeriesIsolation(seriesIdx: number | null): void {
      plotContext.batch(() => {
        for (let index = 1; index < seriesState.length; index += 1) {
          plotContext.setSeries(
            index,
            { show: seriesIdx === null || index === seriesIdx },
            false,
          );
        }
      });
    },
  };
}

function computeWidth(measureEl: HTMLElement): number {
  return Math.max(320, Math.floor(measureEl.getBoundingClientRect().width));
}

function createChartBox(width: number, height: number): {
  height: number;
  left: number;
  top: number;
  width: number;
} {
  const left = 54;
  const right = 16;
  const top = 16;
  const bottom = 36;
  return {
    top,
    left,
    width: Math.max(1, width - left - right),
    height: Math.max(1, height - top - bottom),
  };
}

function normalizeData(data: SpectrumAlignedData): SpectrumAlignedData {
  return data.length ? data : EMPTY_DATA;
}

function requireCanvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext("2d");
  if (context === null) {
    throw new Error("Spectrum chart requires a 2D canvas context");
  }
  return context;
}

function projectValue(value: number, range: ChartRange, start: number, span: number): number {
  const denominator = range.max - range.min || 1;
  return start + (((value - range.min) / denominator) * span);
}

function buildTickValues(range: ChartRange, count: number): number[] {
  if (count <= 1) {
    return [range.min];
  }
  const step = (range.max - range.min) / (count - 1 || 1);
  const ticks: number[] = [];
  for (let index = 0; index < count; index += 1) {
    ticks.push(range.min + (step * index));
  }
  return ticks;
}

function formatHzTick(value: number): string {
  return value >= 100 ? value.toFixed(0) : value.toFixed(1);
}

function formatDbTick(value: number): string {
  return value.toFixed(0);
}

function findClosestIndex(
  freqAxis: readonly number[],
  x: number,
  xRange: ChartRange | null,
  bbox: { left: number; width: number },
): number | null {
  if (freqAxis.length === 0 || xRange === null) {
    return null;
  }
  const freqValue = xRange.min + (((x - bbox.left) / (bbox.width || 1)) * (xRange.max - xRange.min));
  let low = 0;
  let high = freqAxis.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    const nextValue = freqAxis[mid];
    if ((nextValue ?? 0) < freqValue) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  const candidate = low;
  const previous = Math.max(0, candidate - 1);
  const candidateDistance = Math.abs((freqAxis[candidate] ?? freqValue) - freqValue);
  const previousDistance = Math.abs((freqAxis[previous] ?? freqValue) - freqValue);
  return previousDistance <= candidateDistance ? previous : candidate;
}
