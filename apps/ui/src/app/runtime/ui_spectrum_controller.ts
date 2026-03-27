import type uPlot from "uplot";

import {
  SPECTRUM_DB_MAX,
  SPECTRUM_DB_MIN,
  SPECTRUM_TWEEN_DURATION_MS,
} from "../../config";
import { escapeHtml } from "../../format";
import { convertSpectrumAmplitudesToDbInPlace, SpectrumChart } from "../../spectrum";
import { chartSeriesPalette, orderBandFills } from "../../theme";
import { areHeavyFramesCompatible, interpolateHeavyFrame, type SpectrumHeavyFrame } from "../spectrum_animation";
import type { UiDomElements } from "../ui_dom_registry";
import type { AppState, ChartBand } from "../ui_app_state";

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

  private readonly rootStyle: CSSStyleDeclaration;

  private readonly spectrumBandPlugin: uPlot.Plugin;

  private spectrumTweenRaf: number | null = null;

  private spectrumLastFrame: SpectrumHeavyFrame | null = null;

  private currentEntries: SpectrumSeriesEntry[] = [];

  private currentFreqAxis: number[] = [];

  private pinnedSeriesId: string | null = null;

  private cursorDataIdx: number | null = null;

  private bandsVisible = false;

  constructor(deps: UiSpectrumControllerDeps) {
    this.state = deps.state;
    this.els = deps.els;
    this.t = deps.t;
    this.rootStyle = getComputedStyle(document.documentElement);
    this.spectrumBandPlugin = this.createBandPlugin();
    this.bindSpectrumControls();
  }

  updateSpectrumOverlay(): void {
    const message = this.spectrumOverlayMessage();
    this.setSpectrumOverlay(message);
  }

  private spectrumOverlayMessage(): string | null {
    if (this.state.transport.payloadError) {
      return this.state.transport.payloadError;
    }
    if (!this.state.transport.hasReceivedPayload && this.state.transport.wsState === "connecting") {
      return this.t("spectrum.loading");
    }
    if (this.state.transport.wsState === "connecting" || this.state.transport.wsState === "reconnecting") {
      return this.t("ws.connecting");
    }
    if (this.state.transport.wsState === "stale") {
      return this.t("spectrum.stale");
    }
    if (!this.state.spectrum.hasSpectrumData) {
      return this.t("spectrum.empty");
    }
    return null;
  }

  private setSpectrumOverlay(message: string | null): void {
    if (!this.els.spectrumOverlay) return;
    this.els.spectrumOverlay.hidden = message === null;
    this.els.spectrumOverlay.textContent = message ?? "";
  }

  private cssVar(name: string, fallback: string): string {
    return this.rootStyle.getPropertyValue(name).trim() || fallback;
  }

  private formatHz(value: number): string {
    return value >= 100 ? value.toFixed(0) : value.toFixed(1);
  }

  private formatDb(value: number): string {
    return value.toFixed(1);
  }

  private closestFrequencyIndex(targetHz: number): number | null {
    if (!this.currentFreqAxis.length || !Number.isFinite(targetHz)) return null;
    let bestIndex = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let index = 0; index < this.currentFreqAxis.length; index += 1) {
      const distance = Math.abs(this.currentFreqAxis[index] - targetHz);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    }
    return bestIndex;
  }

  private strongestEntry(entries: SpectrumSeriesEntry[] = this.currentEntries): SpectrumSeriesEntry | null {
    let bestEntry: SpectrumSeriesEntry | null = null;
    let bestDb = Number.NEGATIVE_INFINITY;
    for (const entry of entries) {
      const db = this.state.spectrum.spectra.clients[entry.id]?.strength_metrics?.vibration_strength_db;
      if (typeof db !== "number" || !Number.isFinite(db)) continue;
      if (db > bestDb) {
        bestDb = db;
        bestEntry = entry;
      }
    }
    return bestEntry;
  }

  private focusEntry(entries: SpectrumSeriesEntry[] = this.currentEntries): SpectrumSeriesEntry | null {
    if (this.pinnedSeriesId) {
      const pinnedEntry = entries.find((entry) => entry.id === this.pinnedSeriesId);
      if (pinnedEntry) {
        return pinnedEntry;
      }
    }
    return this.strongestEntry(entries);
  }

  private focusPeakInfo(entry: SpectrumSeriesEntry): { freq: number; value: number } | null {
    const peak = this.state.spectrum.spectra.clients[entry.id]?.strength_metrics?.top_peaks?.[0];
    if (!peak || typeof peak.hz !== "number" || !Number.isFinite(peak.hz)) {
      return null;
    }
    const peakIndex = this.closestFrequencyIndex(peak.hz);
    if (peakIndex === null) {
      return null;
    }
    const value = entry.values[peakIndex];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return null;
    }
    return {
      freq: this.currentFreqAxis[peakIndex] ?? peak.hz,
      value,
    };
  }

  private activeBandsForFrequency(freqHz: number): ChartBand[] {
    return this.state.spectrum.chartBands.filter((band) => freqHz >= band.min_hz && freqHz <= band.max_hz);
  }

  private bandSummaryText(bands: ChartBand[]): string {
    return bands.length
      ? bands.map((band) => band.label).join(", ")
      : this.t("spectrum.inspector_no_band");
  }

  private activeFrequency(): number | null {
    if (this.cursorDataIdx !== null && this.cursorDataIdx >= 0 && this.cursorDataIdx < this.currentFreqAxis.length) {
      return this.currentFreqAxis[this.cursorDataIdx];
    }
    const focusEntry = this.focusEntry();
    const peak = focusEntry ? this.focusPeakInfo(focusEntry) : null;
    return peak?.freq ?? null;
  }

  private bindSpectrumControls(): void {
    this.els.spectrumBandToggle?.addEventListener("click", () => {
      if (!this.state.spectrum.chartBands.length) {
        this.bandsVisible = false;
        this.renderBandToggle();
        return;
      }
      this.bandsVisible = !this.bandsVisible;
      this.refreshSpectrumDecorations();
    });
    this.renderBandToggle();
  }

  private renderBandToggle(): void {
    const button = this.els.spectrumBandToggle;
    if (!button) return;
    const hasBands = this.state.spectrum.chartBands.length > 0 && this.currentEntries.length > 0;
    if (!hasBands) {
      this.bandsVisible = false;
    }
    button.hidden = !hasBands;
    button.disabled = !hasBands;
    button.setAttribute("aria-pressed", hasBands && this.bandsVisible ? "true" : "false");
    button.textContent = this.t(this.bandsVisible ? "spectrum.bands.hide" : "spectrum.bands.show");
  }

  private refreshSpectrumDecorations(): void {
    this.renderBandToggle();
    this.updateSpectrumInspector();
    if (!this.currentFreqAxis.length || !this.currentEntries.length) {
      return;
    }
    this.state.spectrum.spectrumPlot?.setData([
      this.currentFreqAxis,
      ...this.currentEntries.map((entry) => entry.values),
    ]);
  }

  private renderSensorLegend(entries: SpectrumSeriesEntry[]): void {
    if (!this.els.legend) return;
    this.els.legend.innerHTML = "";
    if (!entries.length) return;

    const allButton = document.createElement("button");
    allButton.type = "button";
    const allActive = this.pinnedSeriesId === null;
    allButton.className = `legend-item legend-item--interactive legend-item--reset${allActive ? " legend-item--active" : ""}`;
    allButton.setAttribute("aria-pressed", allActive ? "true" : "false");
    allButton.title = this.t("spectrum.legend.clear_focus");
    allButton.addEventListener("click", () => {
      this.pinnedSeriesId = null;
      this.applyLegendSelection();
    });
    const allLabel = document.createElement("span");
    allLabel.className = "legend-item__label";
    allLabel.textContent = this.t("spectrum.legend.all_series");
    allButton.appendChild(allLabel);
    this.els.legend.appendChild(allButton);

    for (const entry of entries) {
      const button = document.createElement("button");
      button.type = "button";
      const isActive = this.pinnedSeriesId === entry.id;
      const isMuted = this.pinnedSeriesId !== null && !isActive;
      button.className = `legend-item legend-item--interactive${isActive ? " legend-item--active" : ""}${isMuted ? " legend-item--muted" : ""}`;
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      button.title = isActive
        ? this.t("spectrum.legend.clear_focus")
        : this.t("spectrum.legend.focus_series", { sensor: entry.label });
      button.addEventListener("click", () => {
        this.pinnedSeriesId = isActive ? null : entry.id;
        this.applyLegendSelection();
      });

      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.setProperty("--swatch-color", entry.color);

      const textGroup = document.createElement("span");
      textGroup.className = "legend-item__text-group";

      const labelSpan = document.createElement("span");
      labelSpan.className = "legend-item__label";
      labelSpan.textContent = entry.label;

      const metric = this.state.spectrum.spectra.clients[entry.id]?.strength_metrics?.vibration_strength_db;
      const metaSpan = document.createElement("span");
      metaSpan.className = "legend-item__meta";
      metaSpan.textContent = typeof metric === "number" && Number.isFinite(metric)
        ? `${this.formatDb(metric)} dB`
        : "";

      textGroup.appendChild(labelSpan);
      textGroup.appendChild(metaSpan);
      button.appendChild(swatch);
      button.appendChild(textGroup);
      this.els.legend.appendChild(button);
    }
  }

  private renderBandLegend(activeBands: ChartBand[] = []): void {
    const legend = this.els.bandLegend;
    if (!legend) return;
    legend.innerHTML = "";
    const shouldShow = this.bandsVisible && this.state.spectrum.chartBands.length > 0 && this.currentEntries.length > 0;
    legend.hidden = !shouldShow;
    if (!shouldShow) return;
    if (!activeBands.length) {
      const row = document.createElement("div");
      row.className = "legend-item legend-item--band legend-item--band-empty";
      row.textContent = this.t("spectrum.bands.none");
      legend.appendChild(row);
      return;
    }
    for (const band of activeBands) {
      const row = document.createElement("div");
      row.className = "legend-item legend-item--band legend-item--band-active";
      row.innerHTML = `<span class="swatch" style="--swatch-color:${escapeHtml(band.color)}"></span><span>${escapeHtml(band.label)}</span>`;
      legend.appendChild(row);
    }
  }

  private updateSpectrumInspector(): void {
    const activeFreq = this.activeFrequency();
    const activeBands = activeFreq === null ? [] : this.activeBandsForFrequency(activeFreq);
    this.renderBandLegend(activeBands);

    if (!this.els.spectrumInspector) return;
    const focusEntry = this.focusEntry();
    if (!focusEntry) {
      this.els.spectrumInspector.textContent = this.t("spectrum.inspector_idle");
      return;
    }

    if (activeFreq !== null && this.cursorDataIdx !== null) {
      const currentValue = focusEntry.values[Math.min(this.cursorDataIdx, focusEntry.values.length - 1)];
      const valueText = typeof currentValue === "number" && Number.isFinite(currentValue)
        ? this.formatDb(currentValue)
        : "--";
      this.els.spectrumInspector.textContent = this.t("spectrum.inspector_hover", {
        sensor: focusEntry.label,
        freq: this.formatHz(activeFreq),
        value: valueText,
        bands: this.bandSummaryText(activeBands),
      });
      return;
    }

    const peak = this.focusPeakInfo(focusEntry);
    if (!peak) {
      this.els.spectrumInspector.textContent = this.t("spectrum.inspector_idle");
      return;
    }
    this.els.spectrumInspector.textContent = this.t(
      this.pinnedSeriesId ? "spectrum.inspector_focus_selected" : "spectrum.inspector_focus_strongest",
      {
        sensor: focusEntry.label,
        freq: this.formatHz(peak.freq),
        value: this.formatDb(peak.value),
        bands: this.bandSummaryText(this.activeBandsForFrequency(peak.freq)),
      },
    );
  }

  private applyLegendSelection(): void {
    if (this.pinnedSeriesId && !this.currentEntries.some((entry) => entry.id === this.pinnedSeriesId)) {
      this.pinnedSeriesId = null;
    }
    const activeIndex = this.pinnedSeriesId
      ? this.currentEntries.findIndex((entry) => entry.id === this.pinnedSeriesId)
      : -1;
    this.state.spectrum.spectrumPlot?.setSeriesIsolation(activeIndex >= 0 ? activeIndex + 1 : null);
    this.renderSensorLegend(this.currentEntries);
    this.updateSpectrumInspector();
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
      convertSpectrumAmplitudesToDbInPlace(blended);

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
        this.spectrumPlugins(),
      );
    }
    this.state.spectrum.chartBands = this.calculateBands();

    if (!targetFreq.length || !entries.length) {
      this.stopSpectrumTween();
      this.currentEntries = [];
      this.currentFreqAxis = [];
      this.cursorDataIdx = null;
      this.spectrumLastFrame = null;
      this.state.spectrum.hasSpectrumData = false;
      this.renderBandToggle();
      this.renderSensorLegend([]);
      this.renderBandLegend();
      this.updateSpectrumInspector();
      this.state.spectrum.spectrumPlot?.setData([[], ...entries.map(() => [] as number[])]);
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
    this.currentEntries = entries;
    this.currentFreqAxis = nextFrame.freq;
    this.renderBandToggle();
    this.applyLegendSelection();
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
    this.currentFreqAxis = frame.freq;
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
      const presentation = bandKeyPresentation[band.key];
      out.push({
        label: this.t(presentation?.labelKey ?? band.key),
        min_hz: Math.max(0, center * (1 - tolerance)),
        max_hz: center * (1 + tolerance),
        color: presentation?.color ?? orderBandFills.wheel1,
      });
    }
    return out.length ? out : null;
  }

  private calculateBands(): ChartBand[] {
    return this.calculateBandsFromBackend() ?? [];
  }

  private createBandPlugin(): uPlot.Plugin {
    return {
      hooks: {
        setCursor: [
          (plot: uPlot) => {
            this.cursorDataIdx = typeof plot.cursor.idx === "number" && plot.cursor.idx >= 0
              ? plot.cursor.idx
              : null;
            this.updateSpectrumInspector();
          },
        ],
        draw: [
          (plot: uPlot) => {
            const top = plot.bbox.top;
            const height = plot.bbox.height;
            if (this.bandsVisible) {
              for (const band of this.state.spectrum.chartBands) {
                if (!(band.max_hz > band.min_hz)) continue;
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

            const focusEntry = this.focusEntry();
            if (!focusEntry) return;
            const focusPeak = this.focusPeakInfo(focusEntry);
            if (!focusPeak) return;
            const peakIndex = this.closestFrequencyIndex(focusPeak.freq);
            if (peakIndex === null) return;
            const x = plot.valToPos(this.currentFreqAxis[peakIndex], "x", true);
            const y = plot.valToPos(focusEntry.values[peakIndex], "y", true);
            const label = `${this.formatHz(focusPeak.freq)} Hz`;
            const labelPaddingX = 6;
            const labelHeight = 20;
            const labelTop = top + 8;
            plot.ctx.save();
            plot.ctx.setLineDash([5, 4]);
            plot.ctx.strokeStyle = focusEntry.color;
            plot.ctx.lineWidth = 1.5;
            plot.ctx.beginPath();
            plot.ctx.moveTo(x, top);
            plot.ctx.lineTo(x, top + height);
            plot.ctx.stroke();
            plot.ctx.setLineDash([]);
            plot.ctx.fillStyle = focusEntry.color;
            plot.ctx.beginPath();
            plot.ctx.arc(x, y, 4, 0, Math.PI * 2);
            plot.ctx.fill();
            plot.ctx.font = "12px system-ui, sans-serif";
            const labelWidth = plot.ctx.measureText(label).width + (labelPaddingX * 2);
            const labelLeft = Math.max(plot.bbox.left, Math.min(x - (labelWidth / 2), plot.bbox.left + plot.bbox.width - labelWidth));
            plot.ctx.fillStyle = this.cssVar("--tooltip-bg", "rgba(15, 23, 42, 0.88)");
            plot.ctx.fillRect(labelLeft, labelTop, labelWidth, labelHeight);
            plot.ctx.fillStyle = this.cssVar("--tooltip-fg", "#f8f9fb");
            plot.ctx.textBaseline = "middle";
            plot.ctx.fillText(label, labelLeft + labelPaddingX, labelTop + (labelHeight / 2));
            plot.ctx.restore();
            this.updateSpectrumInspector();
          },
        ],
        setData: [
          () => {
            this.applyLegendSelection();
          },
        ],
        setSeries: [
          () => {
            this.renderSensorLegend(this.currentEntries);
          },
        ],
      },
    };
  }

  private spectrumPlugins(): uPlot.Plugin[] {
    return [this.spectrumBandPlugin];
  }

  private recreateSpectrumPlot(seriesMeta: SpectrumSeriesEntry[]): void {
    this.stopSpectrumTween();
    this.spectrumLastFrame = null;
    if (this.state.spectrum.spectrumPlot) {
      this.state.spectrum.spectrumPlot.destroy();
      this.state.spectrum.spectrumPlot = null;
    }
    if (!this.els.specChart) return;
    this.state.spectrum.spectrumPlot = new SpectrumChart(
      this.els.specChart,
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
      this.spectrumPlugins(),
    );
  }
}
