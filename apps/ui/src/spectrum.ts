import uPlot from "uplot";

import {
  SPECTRUM_DB_MAX,
  SPECTRUM_DB_MIN,
  SPECTRUM_DB_REFERENCE_AMP_G,
  SPECTRUM_MIN_RENDER_AMP_G,
} from "./config";

export interface SpectrumSeriesMeta {
  label: string;
  color: string;
}

export interface SpectrumText {
  title: string;
  axisHz: string;
  axisAmplitude: string;
}

const SPECTRUM_LOG10_REF = Math.log10(SPECTRUM_DB_REFERENCE_AMP_G);

export function convertSpectrumAmplitudesToDbInPlace(values: number[]): void {
  for (let i = 0; i < values.length; i += 1) {
    const amplitude = values[i];
    const safe = Number.isFinite(amplitude) && amplitude > 0
      ? Math.max(amplitude, SPECTRUM_MIN_RENDER_AMP_G)
      : SPECTRUM_MIN_RENDER_AMP_G;
    const db = 20 * (Math.log10(safe) - SPECTRUM_LOG10_REF);
    values[i] = Math.max(SPECTRUM_DB_MIN, Math.min(SPECTRUM_DB_MAX, db));
  }
}

export class SpectrumChart {
  private static readonly FIXED_Y_RANGE: [number, number] = [SPECTRUM_DB_MIN, SPECTRUM_DB_MAX];

  private plot: uPlot | null = null;
  private readonly hostEl: HTMLElement;
  private readonly measureEl: HTMLElement;
  private readonly height: number;
  private readonly rootStyle: CSSStyleDeclaration;
  private resizeObserver: ResizeObserver | null = null;
  private resizeRaf: number | null = null;

  constructor(hostEl: HTMLElement, height = 360, measureEl?: HTMLElement | null) {
    this.hostEl = hostEl;
    this.measureEl = measureEl || hostEl;
    this.height = height;
    this.rootStyle = getComputedStyle(document.documentElement);
    this.startResizeObserver();
  }

  ensurePlot(seriesMeta: SpectrumSeriesMeta[], text: SpectrumText, plugins: uPlot.Plugin[] = []): void {
    if (this.plot && this.plot.series.length === seriesMeta.length + 1) {
      return;
    }

    this.destroyPlot();
    const series: uPlot.Series[] = [{ label: "Hz" }];
    for (const item of seriesMeta) {
      series.push({ label: item.label, stroke: item.color, width: 2 });
    }

    this.plot = new uPlot(
      {
        title: "",
        width: this.computeWidth(),
        height: this.height,
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
            fill: this.cssVar("--surface", "#f8f9fb"),
          },
        },
        scales: {
          x: { time: false },
          y: {
            range: SpectrumChart.FIXED_Y_RANGE as uPlot.Range.MinMax,
          },
        },
        axes: [
          {
            label: text.axisHz,
            stroke: this.cssVar("--muted", "#5a6b82"),
            grid: { stroke: this.cssVar("--border", "#d7e1ee"), width: 1 },
          },
          {
            label: text.axisAmplitude,
            stroke: this.cssVar("--muted", "#5a6b82"),
            grid: { stroke: this.cssVar("--border", "#d7e1ee"), width: 1 },
          },
        ],
        series,
        plugins,
      },
      [[]],
      this.hostEl,
    );
  }

  setData(data: uPlot.AlignedData): void {
    if (!this.plot) return;
    this.plot.setData(data);
  }

  setSeriesIsolation(seriesIdx: number | null): void {
    const plot = this.plot;
    if (!plot) return;
    plot.batch(() => {
      for (let index = 1; index < plot.series.length; index += 1) {
        plot.setSeries(index, { show: seriesIdx === null || index === seriesIdx }, false);
      }
    });
  }

  resize(): void {
    if (!this.plot) return;
    this.plot.setSize({ width: this.computeWidth(), height: this.height });
  }

  getSeriesCount(): number {
    return this.plot ? this.plot.series.length : 0;
  }

  destroy(): void {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.resizeRaf !== null) {
      window.cancelAnimationFrame(this.resizeRaf);
      this.resizeRaf = null;
    }
    this.destroyPlot();
  }

  private destroyPlot(): void {
    if (this.plot) {
      this.plot.destroy();
      this.plot = null;
    }
  }

  private startResizeObserver(): void {
    this.resizeObserver = new ResizeObserver(() => {
      if (this.resizeRaf !== null) {
        window.cancelAnimationFrame(this.resizeRaf);
      }
      this.resizeRaf = window.requestAnimationFrame(() => {
        this.resizeRaf = null;
        this.resize();
      });
    });
    this.resizeObserver.observe(this.measureEl);
  }


  private cssVar(name: string, fallback: string): string {
    return this.rootStyle.getPropertyValue(name).trim() || fallback;
  }

  private computeWidth(): number {
    return Math.max(320, Math.floor(this.measureEl.getBoundingClientRect().width));
  }
}
