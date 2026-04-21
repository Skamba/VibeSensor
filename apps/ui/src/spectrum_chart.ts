import "uplot/dist/uPlot.min.css";

import uPlot from "uplot";

import { spectrumDbDisplayRangeFromDataBounds } from "./spectrum";
import { getSpectrumCssVars } from "./spectrum_css_vars";
import {
  computed,
  effect,
  signal,
  untracked,
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

export interface SpectrumChart {
  destroy(): void;
  redraw(rebuildPaths?: boolean, recalcAxes?: boolean): void;
  resize(): void;
  setData(data: uPlot.AlignedData, resetScales?: boolean): void;
  setSeriesIsolation(seriesIdx: number | null): void;
}

export interface CreateSpectrumChartDeps {
  hostEl: HTMLElement;
  measureEl?: HTMLElement | null;
  height?: ReadonlySignal<number>;
  seriesMeta: ReadonlySignal<readonly SpectrumSeriesMeta[]>;
  data: ReadonlySignal<uPlot.AlignedData>;
  text: ReadonlySignal<SpectrumText>;
  plugins?: ReadonlySignal<readonly uPlot.Plugin[]>;
}

const DEFAULT_HEIGHT = 360;
const EMPTY_DATA: uPlot.AlignedData = [[]];

export function createSpectrumChart(deps: CreateSpectrumChartDeps): SpectrumChart {
  const measureEl = deps.measureEl ?? deps.hostEl;
  const height = deps.height ?? signal(DEFAULT_HEIGHT);
  const plugins = deps.plugins ?? computed<readonly uPlot.Plugin[]>(() => []);
  const width = signal(computeWidth(measureEl));
  const plot = signal<uPlot | null>(null);
  let resizeRaf: number | null = null;
  let disposed = false;

  const stopResizeObserver = effect(() => {
    width.value = computeWidth(measureEl);
    const resizeObserver = new ResizeObserver(() => {
      if (resizeRaf !== null) {
        window.cancelAnimationFrame(resizeRaf);
      }
      resizeRaf = window.requestAnimationFrame(() => {
        resizeRaf = null;
        width.value = computeWidth(measureEl);
      });
    });
    resizeObserver.observe(measureEl);
    return () => {
      resizeObserver.disconnect();
      if (resizeRaf !== null) {
        window.cancelAnimationFrame(resizeRaf);
        resizeRaf = null;
      }
    };
  });

  const stopPlotLifecycle = effect(() => {
    const seriesMeta = deps.seriesMeta.value;
    const text = deps.text.value;
    const currentPlugins = Array.from(plugins.value);
    if (!seriesMeta.length) {
      plot.value = null;
      return;
    }
    const cssVars = getSpectrumCssVars();
    const nextPlot = new uPlot(
      {
        title: "",
        width: untracked(() => width.value),
        height: untracked(() => height.value),
        focus: { alpha: 0.16 },
        cursor: {
          x: true,
          y: true,
          focus: { prox: 24 },
          hover: { prox: 18 },
          points: {
            one: true,
            size: 7,
            width: 2,
            fill: cssVars.surface,
          },
        },
        scales: {
          x: { time: false },
          y: {
            range: (_self, dataMin, dataMax) =>
              spectrumDbDisplayRangeFromDataBounds(dataMin, dataMax),
          },
        },
        axes: [
          {
            label: text.axisHz,
            stroke: cssVars.muted,
            grid: { stroke: cssVars.border, width: 1 },
          },
          {
            label: text.axisAmplitude,
            stroke: cssVars.muted,
            grid: { stroke: cssVars.border, width: 1 },
          },
        ],
        series: [{ label: "Hz" }, ...seriesMeta.map((item) => ({
          label: item.label,
          stroke: item.color,
          width: 2,
        }))],
        plugins: currentPlugins,
      },
      untracked(() => deps.data.value.length ? deps.data.value : EMPTY_DATA),
      deps.hostEl,
    );
    plot.value = nextPlot;
    return () => {
      if (plot.value === nextPlot) {
        plot.value = null;
      }
      nextPlot.destroy();
    };
  });

  const stopSizeSync = effect(() => {
    const currentPlot = plot.value;
    if (!currentPlot) {
      return;
    }
    currentPlot.setSize({
      width: width.value,
      height: height.value,
    });
  });

  return {
    destroy(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      stopSizeSync();
      stopPlotLifecycle();
      stopResizeObserver();
      plot.value = null;
    },
    redraw(rebuildPaths?: boolean, recalcAxes?: boolean): void {
      const currentPlot = plot.value;
      if (!currentPlot) {
        return;
      }
      currentPlot.redraw(rebuildPaths, recalcAxes);
    },
    resize(): void {
      width.value = computeWidth(measureEl);
    },
    setData(data: uPlot.AlignedData, resetScales?: boolean): void {
      const currentPlot = plot.value;
      if (!currentPlot) {
        return;
      }
      currentPlot.setData(data, resetScales);
    },
    setSeriesIsolation(seriesIdx: number | null): void {
      const currentPlot = plot.value;
      if (!currentPlot) {
        return;
      }
      currentPlot.batch(() => {
        for (let index = 1; index < currentPlot.series.length; index += 1) {
          currentPlot.setSeries(
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
