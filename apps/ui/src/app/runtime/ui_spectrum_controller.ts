import uPlot from "uplot";

import { escapeHtml } from "../../format";
import { SpectrumChart } from "../../spectrum";
import { chartSeriesPalette, orderBandFills } from "../../theme";
import { areHeavyFramesCompatible, interpolateHeavyFrame, type SpectrumHeavyFrame } from "../spectrum_animation";
import type { UiDomElements } from "../ui_dom_registry";
import type { AppState, ChartBand } from "../ui_app_state";

const SPECTRUM_DB_MIN = 0;
const SPECTRUM_DB_MAX = 100;
const SPECTRUM_DB_REFERENCE_AMP_G = 1e-4;
const SPECTRUM_MIN_RENDER_AMP_G = 1e-6;
const SPECTRUM_TWEEN_DURATION_MS = 180;
const SPECTRUM_LOG10_REF = Math.log10(SPECTRUM_DB_REFERENCE_AMP_G);
const FREQ_MATCH_EPSILON = 1e-6;

/** Check if two freq arrays match up to `len` elements. */
function freqGridsMatch(a: number[], b: number[], len: number): boolean {
  for (let i = 0; i < len; i++) {
    if (Math.abs(a[i] - b[i]) > FREQ_MATCH_EPSILON) return false;
  }
  return true;
}

/** Interpolate source values onto a different frequency grid. */
function interpolateToTarget(
  sourceFreq: number[],
  sourceVals: number[],
  desiredFreq: number[],
  sourceLen: number,
): number[] {
  if (sourceLen < 2 || !desiredFreq.length) return [];
  const out = new Array<number>(desiredFreq.length);
  let index = 0;
  for (let i = 0; i < desiredFreq.length; i += 1) {
    const freq = desiredFreq[i];
    while (index + 1 < sourceLen && sourceFreq[index + 1] < freq) index += 1;
    if (index + 1 >= sourceLen) {
      out[i] = sourceVals[sourceLen - 1];
      continue;
    }
    const f0 = sourceFreq[index];
    const f1 = sourceFreq[index + 1];
    const v0 = sourceVals[index];
    const v1 = sourceVals[index + 1];
    out[i] = f1 <= f0 ? v0 : v0 + ((v1 - v0) * ((freq - f0) / (f1 - f0)));
  }
  return out;
}

/** Convert amplitude array to dB scale in-place. */
function convertToDbInPlace(values: number[]): void {
  for (let i = 0; i < values.length; i++) {
    const amplitude = values[i];
    const safe = Number.isFinite(amplitude) && amplitude > 0
      ? Math.max(amplitude, SPECTRUM_MIN_RENDER_AMP_G)
      : SPECTRUM_MIN_RENDER_AMP_G;
    const db = 20 * (Math.log10(safe) - SPECTRUM_LOG10_REF);
    values[i] = Math.max(SPECTRUM_DB_MIN, Math.min(SPECTRUM_DB_MAX, db));
  }
}

const bandKeyColors: Record<string, string> = {
  wheel_1x: orderBandFills.wheel1,
  wheel_2x: orderBandFills.wheel2,
  driveshaft_1x: orderBandFills.driveshaft1,
  engine_1x: orderBandFills.engine1,
  engine_2x: orderBandFills.engine2,
  driveshaft_engine_1x: orderBandFills.driveshaftEngine1,
};

const bandKeyLabels: Record<string, string> = {
  wheel_1x: "bands.wheel_1x",
  wheel_2x: "bands.wheel_2x",
  driveshaft_1x: "bands.driveshaft_1x",
  engine_1x: "bands.engine_1x",
  engine_2x: "bands.engine_2x",
  driveshaft_engine_1x: "bands.driveshaft_engine_1x",
};

type SpectrumSeriesEntry = {
  id: string;
  label: string;
  color: string;
  values: number[];
};

type UiSpectrumControllerDeps = {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
};

export class UiSpectrumController {
  private readonly state: AppState;

  private readonly els: UiDomElements;

  private readonly t: (key: string, vars?: Record<string, unknown>) => string;

  private spectrumTweenRaf: number | null = null;

  private spectrumLastFrame: SpectrumHeavyFrame | null = null;

  constructor(deps: UiSpectrumControllerDeps) {
    this.state = deps.state;
    this.els = deps.els;
    this.t = deps.t;
  }

  updateSpectrumOverlay(): void {
    if (!this.els.spectrumOverlay) return;
    if (this.state.transport.payloadError) {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.state.transport.payloadError;
      return;
    }
    if (!this.state.transport.hasReceivedPayload && this.state.transport.wsState === "connecting") {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("spectrum.loading");
      return;
    }
    if (this.state.transport.wsState === "connecting" || this.state.transport.wsState === "reconnecting") {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("ws.connecting");
      return;
    }
    if (this.state.transport.wsState === "stale") {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("spectrum.stale");
      return;
    }
    if (!this.state.spectrum.hasSpectrumData) {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("spectrum.empty");
      return;
    }
    this.els.spectrumOverlay.hidden = true;
    this.els.spectrumOverlay.textContent = "";
  }

  renderSpectrum(): void {
    const fallbackFreq: number[] = [];
    const entries: SpectrumSeriesEntry[] = [];
    let targetFreq: number[] = [];

    for (const [index, client] of this.state.realtime.clients.entries()) {
      if (!client?.connected) continue;
      const spectrum = this.state.spectrum.spectra.clients?.[client.id];
      if (!spectrum || !Array.isArray(spectrum.combined)) continue;
      const clientFreq = Array.isArray(spectrum.freq) && spectrum.freq.length
        ? spectrum.freq
        : fallbackFreq;
      const length = Math.min(clientFreq.length, spectrum.combined.length);
      if (!length) continue;

      // Use source arrays directly; only allocate when interpolation is needed.
      let blended: number[];
      let needsInterp = false;
      if (!targetFreq.length) {
        targetFreq = clientFreq.length === length ? clientFreq : clientFreq.slice(0, length);
        blended = spectrum.combined.length === length
          ? spectrum.combined
          : spectrum.combined.slice(0, length);
      } else {
        needsInterp = clientFreq.length !== targetFreq.length
          || !freqGridsMatch(clientFreq, targetFreq, length);
        if (needsInterp) {
          blended = interpolateToTarget(clientFreq, spectrum.combined, targetFreq, length);
        } else {
          blended = spectrum.combined.length === length
            ? spectrum.combined
            : spectrum.combined.slice(0, length);
        }
      }
      if (!blended.length) continue;

      // Convert to dB in-place (we either own the array or just allocated it).
      if (!needsInterp && blended === spectrum.combined) {
        // Source array — must copy before mutating.
        blended = blended.slice();
      }
      convertToDbInPlace(blended);

      entries.push({
        id: client.id,
        label: client.name || client.id,
        color: this.colorForClient(index),
        values: blended,
      });
    }

    if (!this.state.spectrum.spectrumPlot || this.state.spectrum.spectrumPlot.getSeriesCount() !== entries.length + 1) {
      this.recreateSpectrumPlot(entries);
    } else {
      this.state.spectrum.spectrumPlot.ensurePlot(
        entries,
        {
          title: this.t("chart.spectrum_title"),
          axisHz: this.t("chart.axis.hz"),
          axisAmplitude: this.t("chart.axis.amplitude"),
        },
        [this.bandPlugin()],
      );
    }
    this.state.spectrum.spectrumPlot!.renderLegend(this.els.legend!, entries);
    this.state.spectrum.chartBands = this.calculateBands();
    if (this.els.bandLegend) {
      this.els.bandLegend.innerHTML = "";
      for (const band of this.state.spectrum.chartBands) {
        const row = document.createElement("div");
        row.className = "legend-item";
        row.innerHTML = `<span class="swatch" style="--swatch-color:${escapeHtml(band.color)}"></span><span>${escapeHtml(band.label)}</span>`;
        this.els.bandLegend.appendChild(row);
      }
    }

    if (!targetFreq.length || !entries.length) {
      this.stopSpectrumTween();
      this.spectrumLastFrame = null;
      this.state.spectrum.hasSpectrumData = false;
      this.state.spectrum.spectrumPlot!.setData([[], ...entries.map(() => [] as number[])]);
      this.updateSpectrumOverlay();
      return;
    }

    this.state.spectrum.hasSpectrumData = true;
    const minLen = Math.min(targetFreq.length, ...entries.map((entry) => entry.values.length));
    // Build frame without redundant copies — entries already own their arrays.
    const nextFrame: SpectrumHeavyFrame = {
      seriesIds: entries.map((entry) => entry.id),
      freq: targetFreq.length === minLen ? targetFreq : targetFreq.slice(0, minLen),
      values: entries.map((entry) =>
        entry.values.length === minLen ? entry.values : entry.values.slice(0, minLen),
      ),
    };
    const canTween = this.state.transport.wsState === "connected"
      && areHeavyFramesCompatible(this.spectrumLastFrame, nextFrame);
    this.stopSpectrumTween();
    if (!canTween || !this.spectrumLastFrame) {
      this.setSpectrumDataFromFrame(nextFrame);
      this.updateSpectrumOverlay();
      return;
    }

    const tweenFrom = this.spectrumLastFrame;
    const startedAt = performance.now();
    const animate = (now: number): void => {
      const alpha = Math.min(1, Math.max(0, (now - startedAt) / SPECTRUM_TWEEN_DURATION_MS));
      this.setSpectrumDataFromFrame(interpolateHeavyFrame(tweenFrom, nextFrame, alpha));
      if (alpha >= 1) {
        this.spectrumTweenRaf = null;
        this.setSpectrumDataFromFrame(nextFrame);
        this.updateSpectrumOverlay();
        return;
      }
      this.spectrumTweenRaf = window.requestAnimationFrame(animate);
    };
    this.spectrumTweenRaf = window.requestAnimationFrame(animate);
    this.updateSpectrumOverlay();
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
    if (!this.state.spectrum.spectrumPlot) return;
    this.state.spectrum.spectrumPlot.setData([frame.freq, ...frame.values]);
    // Store a shallow snapshot for tween comparison.
    // The frame's arrays are not mutated after construction, so no deep clone needed.
    this.spectrumLastFrame = frame;
  }

  private calculateBandsFromBackend(): ChartBand[] | null {
    const bands = this.state.realtime.rotationalSpeeds?.order_bands;
    if (!Array.isArray(bands) || !bands.length) return null;
    const out: ChartBand[] = [];
    for (const band of bands) {
      const center = Number(band.center_hz);
      const tolerance = Number(band.tolerance);
      if (!Number.isFinite(center) || center <= 0 || !Number.isFinite(tolerance)) continue;
      const color = bandKeyColors[band.key] || orderBandFills.wheel1;
      const labelKey = bandKeyLabels[band.key] || band.key;
      out.push({
        label: this.t(labelKey),
        min_hz: Math.max(0, center * (1 - tolerance)),
        max_hz: center * (1 + tolerance),
        color,
      });
    }
    return out.length ? out : null;
  }

  private calculateBands(): ChartBand[] {
    return this.calculateBandsFromBackend() ?? [];
  }

  private bandPlugin(): uPlot.Plugin {
    return {
      hooks: {
        draw: [
          (plot: uPlot) => {
            if (!this.state.spectrum.chartBands.length) return;
            const top = plot.bbox.top;
            const height = plot.bbox.height;
            for (const band of this.state.spectrum.chartBands) {
              if (!(band.max_hz > band.min_hz)) continue;
              const x1 = plot.valToPos(band.min_hz, "x", true);
              const x2 = plot.valToPos(band.max_hz, "x", true);
              plot.ctx.fillStyle = band.color;
              plot.ctx.fillRect(x1, top, Math.max(1, x2 - x1), height);
            }
          },
        ],
      },
    };
  }

  private recreateSpectrumPlot(seriesMeta: SpectrumSeriesEntry[]): void {
    this.stopSpectrumTween();
    this.spectrumLastFrame = null;
    if (this.state.spectrum.spectrumPlot) {
      this.state.spectrum.spectrumPlot.destroy();
      this.state.spectrum.spectrumPlot = null;
    }
    this.state.spectrum.spectrumPlot = new SpectrumChart(
      this.els.specChart!,
      this.els.spectrumOverlay,
      360,
      this.els.specChartWrap,
    );
    this.state.spectrum.spectrumPlot.ensurePlot(
      seriesMeta,
      {
        title: this.t("chart.spectrum_title"),
        axisHz: this.t("chart.axis.hz"),
        axisAmplitude: this.t("chart.axis.amplitude"),
      },
      [this.bandPlugin()],
    );
  }
}
