import uPlot from "uplot";

import { escapeHtml } from "../../format";
import {
  combinedRelativeUncertainty,
  parseTireSpec,
  tireDiameterMeters,
  toleranceForOrder,
} from "../../vehicle_math";
import { SpectrumChart } from "../../spectrum";
import { chartSeriesPalette, orderBandFills } from "../../theme";
import { areHeavyFramesCompatible, interpolateHeavyFrame, type SpectrumHeavyFrame } from "../spectrum_animation";
import type { UiDomElements } from "../dom/ui_dom_registry";
import type { AppState, ChartBand } from "../state/ui_app_state";

const SPECTRUM_DB_MIN = 0;
const SPECTRUM_DB_MAX = 100;
const SPECTRUM_DB_REFERENCE_AMP_G = 1e-4;
const SPECTRUM_MIN_RENDER_AMP_G = 1e-6;
const SPECTRUM_TWEEN_DURATION_MS = 180;
const SPECTRUM_LOG10_REF = Math.log10(SPECTRUM_DB_REFERENCE_AMP_G);

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
    if (this.state.payloadError) {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.state.payloadError;
      return;
    }
    if (!this.state.hasReceivedPayload && this.state.wsState === "connecting") {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("spectrum.loading");
      return;
    }
    if (this.state.wsState === "connecting" || this.state.wsState === "reconnecting") {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("ws.connecting");
      return;
    }
    if (this.state.wsState === "stale") {
      this.els.spectrumOverlay.hidden = false;
      this.els.spectrumOverlay.textContent = this.t("spectrum.stale");
      return;
    }
    if (!this.state.hasSpectrumData) {
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

    const interpolateToTarget = (
      sourceFreq: number[],
      sourceVals: number[],
      desiredFreq: number[],
    ): number[] => {
      if (!Array.isArray(sourceFreq) || !Array.isArray(sourceVals)) return [];
      if (!Array.isArray(desiredFreq) || !desiredFreq.length) return sourceVals.slice();
      if (sourceFreq.length !== sourceVals.length || sourceFreq.length < 2) return [];
      const out = new Array(desiredFreq.length);
      let index = 0;
      for (let i = 0; i < desiredFreq.length; i += 1) {
        const freq = desiredFreq[i];
        while (index + 1 < sourceFreq.length && sourceFreq[index + 1] < freq) index += 1;
        if (index + 1 >= sourceFreq.length) {
          out[i] = sourceVals[sourceVals.length - 1];
          continue;
        }
        const f0 = sourceFreq[index];
        const f1 = sourceFreq[index + 1];
        const v0 = sourceVals[index];
        const v1 = sourceVals[index + 1];
        out[i] = f1 <= f0 ? v0 : v0 + ((v1 - v0) * ((freq - f0) / (f1 - f0)));
      }
      return out;
    };

    for (const [index, client] of this.state.clients.entries()) {
      if (!client?.connected) continue;
      const spectrum = this.state.spectra.clients?.[client.id];
      if (!spectrum || !Array.isArray(spectrum.combined)) continue;
      const clientFreq = Array.isArray(spectrum.freq) && spectrum.freq.length
        ? spectrum.freq
        : fallbackFreq;
      const length = Math.min(clientFreq.length, spectrum.combined.length);
      if (!length) continue;
      let blended = spectrum.combined.slice(0, length);
      const freqSlice = clientFreq.slice(0, length);
      if (!targetFreq.length) {
        targetFreq = freqSlice;
      } else if (
        freqSlice.length !== targetFreq.length
        || freqSlice.some((value, freqIndex) => Math.abs(value - targetFreq[freqIndex]) > 1e-6)
      ) {
        blended = interpolateToTarget(freqSlice, blended, targetFreq);
      }
      if (!blended.length) continue;
      entries.push({
        id: client.id,
        label: client.name || client.id,
        color: this.colorForClient(index),
        values: blended,
      });
    }

    const toDbAbsolute = (amplitude: number): number => {
      const safeAmplitude = Number.isFinite(amplitude) && amplitude > 0
        ? Math.max(amplitude, SPECTRUM_MIN_RENDER_AMP_G)
        : SPECTRUM_MIN_RENDER_AMP_G;
      const db = 20 * (Math.log10(safeAmplitude) - SPECTRUM_LOG10_REF);
      return Math.max(SPECTRUM_DB_MIN, Math.min(SPECTRUM_DB_MAX, db));
    };

    for (const entry of entries) {
      entry.values = entry.values.map(toDbAbsolute);
    }

    if (!this.state.spectrumPlot || this.state.spectrumPlot.getSeriesCount() !== entries.length + 1) {
      this.recreateSpectrumPlot(entries);
    } else {
      this.state.spectrumPlot.ensurePlot(
        entries,
        {
          title: this.t("chart.spectrum_title"),
          axisHz: this.t("chart.axis.hz"),
          axisAmplitude: this.t("chart.axis.amplitude"),
        },
        [this.bandPlugin()],
      );
    }
    this.state.spectrumPlot!.renderLegend(this.els.legend!, entries);
    this.state.chartBands = this.calculateBands();
    if (this.els.bandLegend) {
      this.els.bandLegend.innerHTML = "";
      for (const band of this.state.chartBands) {
        const row = document.createElement("div");
        row.className = "legend-item";
        row.innerHTML = `<span class="swatch" style="--swatch-color:${escapeHtml(band.color)}"></span><span>${escapeHtml(band.label)}</span>`;
        this.els.bandLegend.appendChild(row);
      }
    }

    if (!targetFreq.length || !entries.length) {
      this.stopSpectrumTween();
      this.spectrumLastFrame = null;
      this.state.hasSpectrumData = false;
      this.state.spectrumPlot!.setData([[], ...entries.map(() => [] as number[])]);
      this.updateSpectrumOverlay();
      return;
    }

    this.state.hasSpectrumData = true;
    const minLen = Math.min(targetFreq.length, ...entries.map((entry) => entry.values.length));
    const nextFrame: SpectrumHeavyFrame = {
      seriesIds: entries.map((entry) => entry.id),
      freq: targetFreq.slice(0, minLen),
      values: entries.map((entry) => entry.values.slice(0, minLen)),
    };
    const canTween = this.state.wsState === "connected"
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

  private effectiveSpeedMps(): number | null {
    return typeof this.state.speedMps === "number" && this.state.speedMps > 0
      ? this.state.speedMps
      : null;
  }

  private stopSpectrumTween(): void {
    if (this.spectrumTweenRaf !== null) {
      window.cancelAnimationFrame(this.spectrumTweenRaf);
      this.spectrumTweenRaf = null;
    }
  }

  private setSpectrumDataFromFrame(frame: SpectrumHeavyFrame): void {
    if (!this.state.spectrumPlot) return;
    this.state.spectrumPlot.setData([frame.freq, ...frame.values]);
    this.spectrumLastFrame = {
      seriesIds: frame.seriesIds.slice(),
      freq: frame.freq.slice(),
      values: frame.values.map((series) => series.slice()),
    };
  }

  private vehicleOrdersHz(): {
    wheelHz: number;
    driveHz: number;
    engineHz: number;
    wheelUncertaintyPct: number;
    driveUncertaintyPct: number;
    engineUncertaintyPct: number;
  } | null {
    const speed = this.effectiveSpeedMps();
    if (speed === null) return null;
    const tire = parseTireSpec({
      widthMm: this.state.vehicleSettings.tire_width_mm,
      aspect: this.state.vehicleSettings.tire_aspect_pct,
      rimIn: this.state.vehicleSettings.rim_in,
    });
    if (!tire) return null;
    const wheelHz = speed / (Math.PI * tireDiameterMeters(tire));
    const driveHz = wheelHz * this.state.vehicleSettings.final_drive_ratio;
    const engineHz = driveHz * this.state.vehicleSettings.current_gear_ratio;
    const speedUncertaintyPct = Math.max(0, this.state.vehicleSettings.speed_uncertainty_pct || 0)
      / 100;
    const tireUncertaintyPct = Math.max(
      0,
      this.state.vehicleSettings.tire_diameter_uncertainty_pct || 0,
    ) / 100;
    const finalDriveUncertaintyPct = Math.max(
      0,
      this.state.vehicleSettings.final_drive_uncertainty_pct || 0,
    ) / 100;
    const gearUncertaintyPct = Math.max(0, this.state.vehicleSettings.gear_uncertainty_pct || 0)
      / 100;
    const wheelUncertaintyPct = combinedRelativeUncertainty(
      speedUncertaintyPct,
      tireUncertaintyPct,
    );
    const driveUncertaintyPct = combinedRelativeUncertainty(
      wheelUncertaintyPct,
      finalDriveUncertaintyPct,
    );
    const engineUncertaintyPct = combinedRelativeUncertainty(
      driveUncertaintyPct,
      gearUncertaintyPct,
    );
    return {
      wheelHz,
      driveHz,
      engineHz,
      wheelUncertaintyPct,
      driveUncertaintyPct,
      engineUncertaintyPct,
    };
  }

  private calculateBandsFromBackend(): ChartBand[] | null {
    const bands = this.state.rotationalSpeeds?.order_bands;
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
    const backendBands = this.calculateBandsFromBackend();
    if (backendBands) return backendBands;

    const orders = this.vehicleOrdersHz();
    if (!orders) return [];

    const makeBand = (label: string, center: number, spread: number, color: string): ChartBand => ({
      label,
      min_hz: Math.max(0, center * (1 - spread)),
      max_hz: center * (1 + spread),
      color,
    });

    const wheelSpread = toleranceForOrder(
      this.state.vehicleSettings.wheel_bandwidth_pct,
      orders.wheelHz,
      orders.wheelUncertaintyPct,
      this.state.vehicleSettings.min_abs_band_hz,
      this.state.vehicleSettings.max_band_half_width_pct,
    );
    const driveSpread = toleranceForOrder(
      this.state.vehicleSettings.driveshaft_bandwidth_pct,
      orders.driveHz,
      orders.driveUncertaintyPct,
      this.state.vehicleSettings.min_abs_band_hz,
      this.state.vehicleSettings.max_band_half_width_pct,
    );
    const engineSpread = toleranceForOrder(
      this.state.vehicleSettings.engine_bandwidth_pct,
      orders.engineHz,
      orders.engineUncertaintyPct,
      this.state.vehicleSettings.min_abs_band_hz,
      this.state.vehicleSettings.max_band_half_width_pct,
    );
    const out: ChartBand[] = [
      makeBand(this.t("bands.wheel_1x"), orders.wheelHz, wheelSpread, orderBandFills.wheel1),
      makeBand(this.t("bands.wheel_2x"), orders.wheelHz * 2, wheelSpread, orderBandFills.wheel2),
    ];
    const overlapTolerance = Math.max(0.03, orders.driveUncertaintyPct + orders.engineUncertaintyPct);
    if (Math.abs(orders.driveHz - orders.engineHz) / Math.max(1e-6, orders.engineHz) < overlapTolerance) {
      out.push(
        makeBand(
          this.t("bands.driveshaft_engine_1x"),
          orders.driveHz,
          Math.max(driveSpread, engineSpread),
          orderBandFills.driveshaftEngine1,
        ),
      );
    } else {
      out.push(makeBand(this.t("bands.driveshaft_1x"), orders.driveHz, driveSpread, orderBandFills.driveshaft1));
      out.push(makeBand(this.t("bands.engine_1x"), orders.engineHz, engineSpread, orderBandFills.engine1));
    }
    out.push(makeBand(this.t("bands.engine_2x"), orders.engineHz * 2, engineSpread, orderBandFills.engine2));
    return out;
  }

  private bandPlugin(): uPlot.Plugin {
    return {
      hooks: {
        draw: [
          (plot: uPlot) => {
            if (!this.state.chartBands.length) return;
            const top = plot.bbox.top;
            const height = plot.bbox.height;
            for (const band of this.state.chartBands) {
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
    if (this.state.spectrumPlot) {
      this.state.spectrumPlot.destroy();
      this.state.spectrumPlot = null;
    }
    this.state.spectrumPlot = new SpectrumChart(
      this.els.specChart!,
      this.els.spectrumOverlay,
      360,
      this.els.specChartWrap,
    );
    this.state.spectrumPlot.ensurePlot(
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
