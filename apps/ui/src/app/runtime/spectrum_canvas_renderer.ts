import type uPlot from "uplot";

import { SPECTRUM_TWEEN_DURATION_MS } from "../../config";
import { convertSpectrumAmplitudesToDbInPlace, SpectrumChart } from "../../spectrum";
import { chartSeriesPalette, orderBandFills } from "../../theme";
import {
  createSpectrumTweenDerivedState,
  type SpectrumHeavyFrame,
} from "../spectrum_animation";
import type { AppState, ChartBand } from "../ui_app_state";
import { signal } from "../ui_signals";
import type { SpectrumPanelChartDom } from "./spectrum_panel_view";
import { closestFrequencyIndex, freqGridsMatch, type SpectrumFocusMarker, type SpectrumSeriesEntry } from "./spectrum_shared";

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
}

export class SpectrumCanvasRenderer {
  private readonly rootStyle: CSSStyleDeclaration;

  private readonly spectrumBandPlugin: uPlot.Plugin;

  private spectrumTweenRaf: number | null = null;

  private spectrumLastFrame: SpectrumHeavyFrame | null = null;

  private readonly tweenAlpha = signal(1);

  private readonly tweenFromFrame = signal<SpectrumHeavyFrame | null>(null);

  private readonly tweenToFrame = signal<SpectrumHeavyFrame | null>(null);

  private readonly tweenState = createSpectrumTweenDerivedState(
    this.tweenFromFrame,
    this.tweenToFrame,
    this.tweenAlpha,
  );

  private currentEntries: readonly SpectrumSeriesEntry[] = [];

  private currentFreqAxis: readonly number[] = [];

  constructor(
    private readonly deps: SpectrumCanvasRendererDeps,
  ) {
    this.rootStyle = getComputedStyle(document.documentElement);
    this.spectrumBandPlugin = this.createBandPlugin();
  }

  prepareFrame(): SpectrumPreparedRenderData {
    const fallbackFreq: number[] = [];
    const entries: SpectrumSeriesEntry[] = [];
    let targetFreq: number[] = [];

    for (const [index, client] of this.deps.state.realtime.clients.entries()) {
      if (!client?.connected) {
        continue;
      }
      const spectrum = this.deps.state.spectrum.spectra.clients?.[client.id];
      if (!spectrum || !Array.isArray(spectrum.combined)) {
        continue;
      }
      const clientFreq = Array.isArray(spectrum.freq) && spectrum.freq.length
        ? spectrum.freq
        : fallbackFreq;
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
        color: this.colorForClient(index),
        values: blended,
      });
    }

    const chartBands = this.calculateBands();
    if (!targetFreq.length || !entries.length) {
      return {
        entries: [],
        freqAxis: [],
        chartBands,
        frame: null,
        hasData: false,
      };
    }

    const minLen = Math.min(targetFreq.length, ...entries.map((entry) => entry.values.length));
    const frame: SpectrumHeavyFrame = {
      seriesIds: entries.map((entry) => entry.id),
      freq: targetFreq.length === minLen ? targetFreq : targetFreq.slice(0, minLen),
      values: entries.map((entry) =>
        entry.values.length === minLen ? entry.values : entry.values.slice(0, minLen),
      ),
    };

    return {
      entries,
      freqAxis: frame.freq,
      chartBands,
      frame,
      hasData: true,
    };
  }

  renderPreparedFrame(prepared: SpectrumPreparedRenderData): void {
    this.currentEntries = prepared.entries;
    this.currentFreqAxis = prepared.freqAxis;

    if (
      !this.deps.state.spectrum.spectrumPlot
      || this.deps.state.spectrum.spectrumPlot.getSeriesCount() !== prepared.entries.length + 1
    ) {
      this.recreateSpectrumPlot(prepared.entries);
    }

    if (!prepared.frame) {
      this.stopSpectrumTween();
      this.currentEntries = [];
      this.currentFreqAxis = [];
      this.spectrumLastFrame = null;
      this.deps.state.spectrum.spectrumPlot?.setData([[], ...prepared.entries.map(() => [] as number[])]);
      return;
    }

    const nextFrame = prepared.frame;
    this.tweenFromFrame.value = this.spectrumLastFrame;
    this.tweenToFrame.value = nextFrame;
    this.stopSpectrumTween();
    const canTween = this.deps.state.transport.wsState === "connected"
      && this.tweenState.canTween.value;
    if (!canTween || !this.spectrumLastFrame) {
      this.setSpectrumDataFromFrame(nextFrame);
      return;
    }

    const startedAt = performance.now();
    const animate = (now: number): void => {
      this.tweenAlpha.value = Math.min(1, Math.max(0, (now - startedAt) / SPECTRUM_TWEEN_DURATION_MS));
      const frame = this.tweenState.frame.value;
      if (frame) {
        this.setSpectrumDataFromFrame(frame);
      }
      if (this.tweenAlpha.value >= 1) {
        this.spectrumTweenRaf = null;
        this.setSpectrumDataFromFrame(nextFrame);
        return;
      }
      this.spectrumTweenRaf = window.requestAnimationFrame(animate);
    };
    this.spectrumTweenRaf = window.requestAnimationFrame(animate);
  }

  refreshDecorations(): void {
    if (!this.currentFreqAxis.length || !this.currentEntries.length) {
      return;
    }
    this.deps.state.spectrum.spectrumPlot?.setData([
      this.currentFreqAxis.slice(),
      ...this.currentEntries.map((entry) => entry.values),
    ]);
  }

  setSeriesIsolation(seriesIndex: number | null): void {
    this.deps.state.spectrum.spectrumPlot?.setSeriesIsolation(seriesIndex);
  }

  private colorForClient(index: number): string {
    return chartSeriesPalette[index % chartSeriesPalette.length];
  }

  private stopSpectrumTween(): void {
    if (this.spectrumTweenRaf !== null) {
      window.cancelAnimationFrame(this.spectrumTweenRaf);
      this.spectrumTweenRaf = null;
    }
  }

  private setSpectrumDataFromFrame(frame: SpectrumHeavyFrame): void {
    if (!this.deps.state.spectrum.spectrumPlot) {
      return;
    }
    this.currentFreqAxis = frame.freq;
    this.deps.state.spectrum.spectrumPlot.setData([frame.freq, ...frame.values]);
    this.spectrumLastFrame = frame;
  }

  private calculateBandsFromBackend(): ChartBand[] | null {
    const bands = this.deps.state.realtime.rotationalSpeeds?.order_bands;
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
        label: this.deps.t(presentation?.labelKey ?? band.key),
        min_hz: Math.max(0, center * (1 - tolerance)),
        max_hz: center * (1 + tolerance),
        color: presentation?.color ?? orderBandFills.wheel1,
      });
    }
    return output.length ? output : null;
  }

  private calculateBands(): ChartBand[] {
    return this.calculateBandsFromBackend() ?? [];
  }

  private createBandPlugin(): uPlot.Plugin {
    return {
      hooks: {
        setCursor: [
          (plot: uPlot) => {
            this.deps.onCursorDataIndexChange(
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
            if (this.deps.getBandsVisible()) {
              for (const band of this.deps.getChartBands()) {
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

            const focusMarker = this.deps.getFocusMarker();
            if (!focusMarker) {
              return;
            }
            const peakIndex = closestFrequencyIndex(this.currentFreqAxis, focusMarker.freq);
            if (peakIndex === null) {
              return;
            }
            const x = plot.valToPos(this.currentFreqAxis[peakIndex], "x", true);
            const y = plot.valToPos(focusMarker.value, "y", true);
            const label = `${this.formatHz(focusMarker.freq)} Hz`;
            const labelPaddingX = 6;
            const labelHeight = 20;
            const labelTop = top + 8;
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
            plot.ctx.fillStyle = this.cssVar("--tooltip-bg", "rgba(15, 23, 42, 0.88)");
            plot.ctx.fillRect(labelLeft, labelTop, labelWidth, labelHeight);
            plot.ctx.fillStyle = this.cssVar("--tooltip-fg", "#f8f9fb");
            plot.ctx.textBaseline = "middle";
            plot.ctx.fillText(label, labelLeft + labelPaddingX, labelTop + (labelHeight / 2));
            plot.ctx.restore();
          },
        ],
      },
    };
  }

  private recreateSpectrumPlot(seriesMeta: readonly SpectrumSeriesEntry[]): void {
    this.stopSpectrumTween();
    this.spectrumLastFrame = null;
    if (this.deps.state.spectrum.spectrumPlot) {
      this.deps.state.spectrum.spectrumPlot.destroy();
      this.deps.state.spectrum.spectrumPlot = null;
    }
    this.deps.state.spectrum.spectrumPlot = new SpectrumChart(
      this.deps.dom.specChart,
      360,
      this.deps.dom.specChartWrap,
    );
    this.deps.state.spectrum.spectrumPlot.ensurePlot(
      Array.from(seriesMeta),
      {
        title: this.deps.t("chart.spectrum_title"),
        axisHz: this.deps.t("chart.axis.hz"),
        axisAmplitude: this.deps.t("chart.axis.amplitude"),
      },
      [this.spectrumBandPlugin],
    );
  }

  private cssVar(name: string, fallback: string): string {
    return this.rootStyle.getPropertyValue(name).trim() || fallback;
  }

  private formatHz(value: number): string {
    return value >= 100 ? value.toFixed(0) : value.toFixed(1);
  }
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
