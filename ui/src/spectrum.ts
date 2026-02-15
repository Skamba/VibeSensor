// @ts-nocheck
import uPlot from "uplot";

export interface SpectrumSeriesMeta {
  label: string;
  color: string;
}

export interface SpectrumText {
  title: string;
  axisHz: string;
  axisAmplitude: string;
}

export class SpectrumChart {
  private plot: uPlot | null = null;
  private readonly hostEl: HTMLElement;
  private readonly measureEl: HTMLElement;
  private readonly overlayEl: HTMLElement | null;
  private readonly height: number;
  private resizeObserver: ResizeObserver | null = null;
  private resizeRaf: number | null = null;

  constructor(hostEl: HTMLElement, overlayEl?: HTMLElement | null, height = 360, measureEl?: HTMLElement | null) {
    this.hostEl = hostEl;
    this.measureEl = measureEl || hostEl;
    this.overlayEl = overlayEl || null;
    this.height = height;
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
        title: text.title,
        width: this.computeWidth(),
        height: this.height,
        scales: {
          x: { time: false },
          y: { range: [0, 50] },
        },
        axes: [{ label: text.axisHz }, { label: text.axisAmplitude }],
        series,
        plugins,
      },
      [[]],
      this.hostEl,
    );
  }

  setData(data: number[][]): void {
    if (!this.plot) return;
    this.plot.setData(data);
  }

  resize(): void {
    if (!this.plot) return;
    this.plot.setSize({ width: this.computeWidth(), height: this.height });
  }

  getSeriesCount(): number {
    return this.plot ? this.plot.series.length : 0;
  }

  renderLegend(legendEl: HTMLElement, seriesMeta: SpectrumSeriesMeta[]): void {
    legendEl.innerHTML = "";
    for (const item of seriesMeta) {
      const row = document.createElement("div");
      row.className = "legend-item";
      row.innerHTML = `<span class="swatch" style="background:${item.color}"></span><span>${item.label}</span>`;
      legendEl.appendChild(row);
    }
  }

  setOverlay(message: string | null): void {
    if (!this.overlayEl) return;
    if (!message) {
      this.overlayEl.hidden = true;
      this.overlayEl.textContent = "";
      return;
    }
    this.overlayEl.hidden = false;
    this.overlayEl.textContent = message;
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

  private computeWidth(): number {
    return Math.max(320, Math.floor(this.measureEl.getBoundingClientRect().width));
  }
}
