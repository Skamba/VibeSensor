import uPlot from "uplot";
import * as I18N from "../i18n";
import { defaultLocationCodes } from "../constants";
import { createEmptyMatrix } from "../diagnostics";
import { adaptServerPayload } from "../server_payload";
import type { RotationalSpeeds } from "../server_payload";
import { escapeHtml, fmt, fmtTs, formatIntLocale } from "../format";
import {
  combinedRelativeUncertainty,
  parseTireSpec,
  tireDiameterMeters,
  toleranceForOrder,
} from "../vehicle_math";
import { SpectrumChart } from "../spectrum";
import { getSettingsLanguage, getSettingsSpeedUnit, setSettingsLanguage, setSettingsSpeedUnit } from "../api/settings";
import { runDemoMode } from "../features/demo/runDemoMode";
import { chartSeriesPalette, orderBandFills } from "../theme";
import { WsClient } from "../ws";
import type { UiDomElements } from "./dom/ui_dom_registry";
import { createUiDomRegistry } from "./dom/ui_dom_registry";
import { createAppFeatureBundle, type AppFeatureBundle } from "./app_feature_bundle";
import { areHeavyFramesCompatible, interpolateHeavyFrame, type SpectrumHeavyFrame } from "./spectrum_animation";
import type { AppState, ChartBand } from "./state/ui_app_state";
import { applySpectrumTick, createAppState } from "./state/ui_app_state";

const CAR_MAP_WINDOW_MS = 10_000;
const DEFAULT_VIEW_ID = "dashboardView";

const CAR_MAP_POSITIONS: Record<string, { top: number; left: number }> = {
  front_left_wheel: { top: 22, left: 18 },
  front_right_wheel: { top: 22, left: 82 },
  rear_left_wheel: { top: 78, left: 18 },
  rear_right_wheel: { top: 78, left: 82 },
  engine_bay: { top: 28, left: 50 },
  front_subframe: { top: 14, left: 50 },
  rear_subframe: { top: 88, left: 50 },
  driveshaft_tunnel: { top: 52, left: 50 },
  transmission: { top: 40, left: 48 },
  driver_seat: { top: 44, left: 38 },
  front_passenger_seat: { top: 44, left: 62 },
  rear_left_seat: { top: 66, left: 30 },
  rear_center_seat: { top: 66, left: 50 },
  rear_right_seat: { top: 66, left: 70 },
  trunk: { top: 88, left: 50 },
};

const SPECTRUM_DB_MIN = 0;
const SPECTRUM_DB_MAX = 100;
const SPECTRUM_DB_REFERENCE_AMP_G = 1e-4;
const SPECTRUM_MIN_RENDER_AMP_G = 1e-6;
const SPECTRUM_TWEEN_DURATION_MS = 180;
const SPECTRUM_LOG10_REF = Math.log10(SPECTRUM_DB_REFERENCE_AMP_G);

const WS_KEY_BY_STATE: Record<string, string> = {
  connecting: "ws.connecting",
  connected: "ws.connected",
  reconnecting: "ws.reconnecting",
  stale: "ws.stale",
  no_data: "ws.no_data",
};

const WS_VARIANT_BY_STATE: Record<string, string> = {
  connecting: "muted",
  connected: "ok",
  reconnecting: "warn",
  stale: "bad",
  no_data: "muted",
};

const WS_BANNER_CFG: Record<string, { key: string; cls: string }> = {
  reconnecting: { key: "ws.banner.reconnecting", cls: "connection-banner--bad" },
  stale: { key: "ws.banner.stale", cls: "connection-banner--warn" },
  connecting: { key: "ws.banner.connecting", cls: "connection-banner--muted" },
};

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

export class UiAppRuntime {
  private readonly els: UiDomElements;

  private readonly state: AppState;

  private readonly features: AppFeatureBundle;

  private latestRotationalSpeeds: RotationalSpeeds | null = null;

  private spectrumTweenRaf: number | null = null;

  private spectrumLastFrame: SpectrumHeavyFrame | null = null;

  constructor(
    els: UiDomElements = createUiDomRegistry(),
    state: AppState = createAppState(),
  ) {
    this.els = els;
    this.state = state;
    this.features = createAppFeatureBundle({
      state: this.state,
      els: this.els,
      t: (key, vars) => this.t(key, vars),
      escapeHtml,
      fmt,
      fmtTs,
      formatInt: (value) => this.localFormatInt(value),
      setPillState: (el, variant, text) => this.setPillState(el, variant, text),
      setStatValue: (container, value) => this.setStatValue(container, value),
      renderSpectrum: () => this.renderSpectrum(),
      renderSpeedReadout: () => this.renderSpeedReadout(),
      renderCarSelectionWarning: () => this.renderCarSelectionWarning(),
      sendSelection: () => this.sendSelection(),
      carMapPositions: CAR_MAP_POSITIONS,
      carMapWindowMs: CAR_MAP_WINDOW_MS,
    });
  }

  start(): void {
    this.bindUiEvents();
    this.features.settings.syncSettingsInputs();
    void this.hydratePersistedPreferences();
    this.applyLanguage(false);
    this.renderCarSelectionWarning();
    this.setActiveView(DEFAULT_VIEW_ID);
    this.startBackgroundActivity();
    this.startTransportMode();
  }

  private t(key: string, vars?: Record<string, unknown>): string {
    return I18N.get(this.state.lang, key, vars);
  }

  private localFormatInt(value: number): string {
    return formatIntLocale(value, this.state.lang);
  }

  private normalizeSpeedUnit(raw: string): string {
    return raw === "mps" ? "mps" : "kmh";
  }

  private saveLanguage(lang: string): void {
    this.state.lang = I18N.normalizeLang(lang);
    void setSettingsLanguage(this.state.lang).catch(() => {});
  }

  private saveSpeedUnit(unit: string): void {
    this.state.speedUnit = this.normalizeSpeedUnit(unit);
    void setSettingsSpeedUnit(this.state.speedUnit).catch(() => {});
  }

  private speedValueInSelectedUnit(speedMps: number | null): number | null {
    if (!(typeof speedMps === "number") || !Number.isFinite(speedMps)) return null;
    return this.state.speedUnit === "mps" ? speedMps : speedMps * 3.6;
  }

  private selectedSpeedUnitLabel(): string {
    return this.state.speedUnit === "mps" ? this.t("speed.unit.mps") : this.t("speed.unit.kmh");
  }

  private setStatValue(container: HTMLElement | null, value: string | number): void {
    const valueEl = container?.querySelector?.("[data-value]");
    if (valueEl) {
      valueEl.textContent = String(value);
      return;
    }
    if (container) {
      container.textContent = String(value);
    }
  }

  private setPillState(el: HTMLElement | null, variant: string, text: string): void {
    if (!el) return;
    el.className = `pill pill--${variant}`;
    el.textContent = text;
  }

  private colorForClient(index: number): string {
    return chartSeriesPalette[index % chartSeriesPalette.length];
  }

  private effectiveSpeedMps(): number | null {
    return typeof this.state.speedMps === "number" && this.state.speedMps > 0
      ? this.state.speedMps
      : null;
  }

  private renderSpeedReadout(): void {
    if (!this.els.speed) return;
    const unitLabel = this.selectedSpeedUnitLabel();
    if (typeof this.state.speedMps === "number" && Number.isFinite(this.state.speedMps)) {
      const value = this.speedValueInSelectedUnit(this.state.speedMps);
      const isManualSource = this.state.speedSource === "manual"
        && typeof this.state.manualSpeedKph === "number"
        && this.state.manualSpeedKph > 0;
      const isFallbackOverride = this.state.gpsFallbackActive
        || this.latestRotationalSpeeds?.basis_speed_source === "fallback_manual";
      const isOverride = isManualSource || isFallbackOverride;
      this.els.speed.textContent = this.t(isOverride ? "speed.override" : "speed.gps", {
        value: fmt(value!, 1),
        unit: unitLabel,
      });
      return;
    }
    this.els.speed.textContent = this.t("speed.none", { unit: unitLabel });
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

  private renderWsState(): void {
    if (this.state.payloadError) {
      this.setPillState(this.els.linkState, "bad", this.t("ws.payload_error_pill"));
      return;
    }
    this.setPillState(
      this.els.linkState,
      WS_VARIANT_BY_STATE[this.state.wsState] || "muted",
      this.t(WS_KEY_BY_STATE[this.state.wsState] || "ws.connecting"),
    );

    const banner = this.els.connectionBanner;
    if (banner) {
      const cfg = WS_BANNER_CFG[this.state.wsState];
      if (cfg) {
        banner.hidden = false;
        banner.textContent = this.t(cfg.key);
        banner.className = `connection-banner ${cfg.cls}`;
      } else {
        banner.hidden = true;
        banner.textContent = "";
        banner.className = "connection-banner";
      }
    }

    const wrap = document.querySelector(".wrap");
    if (wrap) {
      const degraded = this.state.wsState === "reconnecting" || this.state.wsState === "stale";
      wrap.classList.toggle("wrap--stale", degraded);
    }
  }

  private renderCarSelectionWarning(): void {
    const banner = this.els.carSelectionBanner;
    if (!banner) return;
    const hasValidActiveCar = Boolean(
      this.state.activeCarId && this.state.cars.some((car) => car.id === this.state.activeCarId),
    );
    if (hasValidActiveCar) {
      banner.hidden = true;
      banner.textContent = "";
      return;
    }
    banner.hidden = false;
    banner.textContent = `${this.t("header.no_car_selected")} ${this.t("header.no_car_selected_action")}`;
  }

  private updateSpectrumOverlay(): void {
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

  private setActiveView(viewId: string): void {
    const valid = this.els.views.some((view) => view.id === viewId);
    this.state.activeViewId = valid ? viewId : DEFAULT_VIEW_ID;
    for (const view of this.els.views) {
      const isActive = view.id === this.state.activeViewId;
      view.classList.toggle("active", isActive);
      view.hidden = !isActive;
    }
    for (const button of this.els.menuButtons) {
      const isActive = button.dataset.view === this.state.activeViewId;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
      button.tabIndex = isActive ? 0 : -1;
    }
    if (this.state.activeViewId === DEFAULT_VIEW_ID && this.state.spectrumPlot) {
      this.state.spectrumPlot.resize();
    }
  }

  private applyLanguage(forceReloadInsights = false): void {
    document.documentElement.lang = this.state.lang;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (key) element.textContent = this.t(key);
    });
    if (this.els.languageSelect) this.els.languageSelect.value = this.state.lang;
    if (this.els.speedUnitSelect) this.els.speedUnitSelect.value = this.state.speedUnit;
    this.state.locationOptions = this.features.realtime.buildLocationOptions(this.state.locationCodes);
    this.state.sensorsSettingsSignature = "";
    this.features.realtime.maybeRenderSensorsSettingsList(true);
    this.renderSpeedReadout();
    this.features.realtime.renderLoggingStatus();
    this.features.history.renderHistoryTable();
    this.renderWsState();
    this.renderCarSelectionWarning();
    if (this.state.spectrumPlot) {
      this.state.spectrumPlot.destroy();
      this.state.spectrumPlot = null;
      this.renderSpectrum();
    }
    this.features.dashboard.recreateStrengthChart();
    if (forceReloadInsights) {
      this.features.history.reloadExpandedRunOnLanguageChange();
    }
    this.updateSpectrumOverlay();
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
    const speedUncertaintyPct = Math.max(0, this.state.vehicleSettings.speed_uncertainty_pct || 0) / 100;
    const tireUncertaintyPct = Math.max(0, this.state.vehicleSettings.tire_diameter_uncertainty_pct || 0) / 100;
    const finalDriveUncertaintyPct = Math.max(0, this.state.vehicleSettings.final_drive_uncertainty_pct || 0) / 100;
    const gearUncertaintyPct = Math.max(0, this.state.vehicleSettings.gear_uncertainty_pct || 0) / 100;
    const wheelUncertaintyPct = combinedRelativeUncertainty(speedUncertaintyPct, tireUncertaintyPct);
    const driveUncertaintyPct = combinedRelativeUncertainty(wheelUncertaintyPct, finalDriveUncertaintyPct);
    const engineUncertaintyPct = combinedRelativeUncertainty(driveUncertaintyPct, gearUncertaintyPct);
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
    const bands = this.latestRotationalSpeeds?.order_bands;
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

  private renderSpectrum(): void {
    const fallbackFreq: number[] = [];
    const entries: SpectrumSeriesEntry[] = [];
    let targetFreq: number[] = [];

    const interpolateToTarget = (sourceFreq: number[], sourceVals: number[], desiredFreq: number[]): number[] => {
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
      const clientFreq = Array.isArray(spectrum.freq) && spectrum.freq.length ? spectrum.freq : fallbackFreq;
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

  private sendSelection(): void {
    if (this.state.ws) {
      this.state.ws.send({ client_id: this.state.selectedClientId });
    }
  }

  private queueRender(): void {
    if (this.state.renderQueued) return;
    this.state.renderQueued = true;
    window.requestAnimationFrame(() => {
      this.state.renderQueued = false;
      const now = Date.now();
      if (now - this.state.lastRenderTsMs < this.state.minRenderIntervalMs) {
        this.queueRender();
        return;
      }
      const payload = this.state.pendingPayload;
      if (!payload) return;
      this.state.pendingPayload = null;
      this.state.lastRenderTsMs = now;
      this.applyPayload(payload);
    });
  }

  private applyPayload(payload: unknown): void {
    let adapted;
    try {
      adapted = adaptServerPayload(payload);
    } catch (error) {
      this.state.payloadError = error instanceof Error ? error.message : this.t("ws.payload_error");
      this.state.hasSpectrumData = false;
      this.renderWsState();
      this.updateSpectrumOverlay();
      return;
    }

    this.state.payloadError = null;
    this.renderWsState();

    const prevSelected = this.state.selectedClientId;
    this.state.clients = adapted.clients;
    const hasFresh = this.features.dashboard.hasFreshSensorFrames(this.state.clients);
    const incomingSpectra = adapted.spectra
      ? {
        clients: Object.fromEntries(
          Object.entries(adapted.spectra.clients).map(([clientId, spectrum]) => [
            clientId,
            {
              freq: spectrum.freq,
              strength_metrics: spectrum.strength_metrics,
              combined: spectrum.combined,
            },
          ]),
        ),
      }
      : null;
    const spectrumTick = applySpectrumTick(this.state.spectra, this.state.hasSpectrumData, incomingSpectra);
    this.state.spectra = spectrumTick.spectra;
    this.features.realtime.updateClientSelection();
    this.features.realtime.maybeRenderSensorsSettingsList();
    this.features.realtime.renderLoggingStatus();
    if (prevSelected !== this.state.selectedClientId) {
      this.sendSelection();
    }
    this.state.speedMps = adapted.speed_mps;
    this.latestRotationalSpeeds = adapted.rotational_speeds;
    this.state.hasSpectrumData = spectrumTick.hasSpectrumData;
    this.renderSpeedReadout();
    this.features.dashboard.applyServerDiagnostics(adapted.diagnostics, hasFresh);
    const liveIntensity = this.features.dashboard.extractLiveLocationIntensity();
    const intensityToPlot = Object.keys(liveIntensity).length > 0
      ? liveIntensity
      : this.features.dashboard.extractConfirmedLocationIntensity();
    this.features.dashboard.pushCarMapSample(intensityToPlot);
    this.features.dashboard.renderCarMap();
    if (spectrumTick.hasNewSpectrumFrame) {
      this.renderSpectrum();
    } else {
      this.updateSpectrumOverlay();
    }
    this.features.realtime.renderStatus(this.state.clients.find((client) => client.id === this.state.selectedClientId));
  }

  private resetLiveSessionCounters(): void {
    this.state.strengthFrameTotalsByClient = {};
    this.state.carMapSamples = [];
  }

  private connectWs(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.state.ws = new WsClient({
      url: `${protocol}//${window.location.host}/ws`,
      onPayload: (payload) => {
        this.state.hasReceivedPayload = true;
        this.state.pendingPayload = payload;
        this.queueRender();
      },
      onStateChange: (nextState) => {
        this.state.wsState = nextState;
        this.renderWsState();
        this.updateSpectrumOverlay();
        if (nextState === "connected" || nextState === "no_data") {
          this.resetLiveSessionCounters();
          this.sendSelection();
        }
      },
    });
    this.state.ws.connect();
  }

  private activateMenuTabByIndex(index: number): void {
    if (!this.els.menuButtons.length) return;
    const safeIndex = ((index % this.els.menuButtons.length) + this.els.menuButtons.length) % this.els.menuButtons.length;
    const button = this.els.menuButtons[safeIndex];
    const viewId = button.dataset.view;
    if (!viewId) return;
    this.setActiveView(viewId);
    button.focus();
  }

  private bindMenuEvents(): void {
    this.els.menuButtons.forEach((button, index) => {
      const activate = (): void => {
        const viewId = button.dataset.view;
        if (viewId) this.setActiveView(viewId);
      };
      button.addEventListener("click", activate);
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
          return;
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          this.activateMenuTabByIndex(index + 1);
          return;
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          this.activateMenuTabByIndex(index - 1);
          return;
        }
        if (event.key === "Home") {
          event.preventDefault();
          this.activateMenuTabByIndex(0);
          return;
        }
        if (event.key === "End") {
          event.preventDefault();
          this.activateMenuTabByIndex(this.els.menuButtons.length - 1);
        }
      });
    });
  }

  private bindFeatureEvents(): void {
    this.features.settings.bindSettingsTabs();
    this.features.cars.bindWizardHandlers();
    this.features.update.bindUpdateHandlers();
    this.features.espFlash.bindHandlers();
    this.els.saveAnalysisBtn?.addEventListener("click", this.features.settings.saveAnalysisFromInputs);
    this.els.saveSpeedSourceBtn?.addEventListener("click", this.features.settings.saveSpeedSourceFromInputs);
    this.els.headerManualSpeedSaveBtn?.addEventListener("click", this.features.settings.saveHeaderManualSpeedFromInput);
    this.els.headerManualSpeedInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        this.features.settings.saveHeaderManualSpeedFromInput();
      }
    });
    this.els.startLoggingBtn?.addEventListener("click", this.features.realtime.startLogging);
    this.els.stopLoggingBtn?.addEventListener("click", this.features.realtime.stopLogging);
    if (this.els.strengthAutoScaleToggle) {
      this.els.strengthAutoScaleToggle.checked = this.state.strengthChartAutoScale;
      this.els.strengthAutoScaleToggle.addEventListener("change", () => {
        this.state.strengthChartAutoScale = this.els.strengthAutoScaleToggle!.checked;
      });
    }
    this.els.refreshHistoryBtn?.addEventListener("click", this.features.history.refreshHistory);
    this.els.deleteAllRunsBtn?.addEventListener("click", () => void this.features.history.deleteAllRuns());
  }

  private bindHistoryTableEvents(): void {
    this.els.historyTableBody?.addEventListener("click", (event) => {
      const target = event.target as HTMLElement;
      const actionElement = target?.closest?.("[data-run-action]") as HTMLElement | null;
      if (actionElement) {
        const action = actionElement.getAttribute("data-run-action");
        const runId = actionElement.getAttribute("data-run") || this.state.expandedRunId || "";
        if (action !== "download-raw") event.preventDefault();
        event.stopPropagation();
        void this.features.history.onHistoryTableAction(action || "", runId);
        return;
      }
      const rowElement = target?.closest?.('tr[data-run-row="1"]') as HTMLElement | null;
      if (rowElement) {
        this.features.history.toggleRunDetails(rowElement.getAttribute("data-run") || "");
      }
    });
  }

  private bindPreferenceEvents(): void {
    if (this.els.languageSelect) {
      this.els.languageSelect.value = this.state.lang;
      this.els.languageSelect.addEventListener("change", () => {
        this.saveLanguage(this.els.languageSelect!.value);
        this.applyLanguage(true);
      });
    }
    if (this.els.speedUnitSelect) {
      this.els.speedUnitSelect.value = this.state.speedUnit;
      this.els.speedUnitSelect.addEventListener("change", () => {
        this.saveSpeedUnit(this.els.speedUnitSelect!.value);
        this.renderSpeedReadout();
      });
    }
  }

  private bindUiEvents(): void {
    this.bindMenuEvents();
    this.bindFeatureEvents();
    this.bindHistoryTableEvents();
    this.bindPreferenceEvents();
  }

  private async hydratePersistedPreferences(): Promise<void> {
    try {
      const languageResponse = await getSettingsLanguage();
      if (languageResponse?.language) {
        this.state.lang = I18N.normalizeLang(languageResponse.language);
        this.applyLanguage(true);
      }
    } catch {
      // ignore
    }
    try {
      const speedUnitResponse = await getSettingsSpeedUnit();
      if (speedUnitResponse?.speedUnit) {
        this.state.speedUnit = this.normalizeSpeedUnit(speedUnitResponse.speedUnit);
        if (this.els.speedUnitSelect) {
          this.els.speedUnitSelect.value = this.state.speedUnit;
        }
        this.renderSpeedReadout();
      }
    } catch {
      // ignore
    }
  }

  private startBackgroundActivity(): void {
    void this.features.realtime.refreshLocationOptions();
    void this.features.settings.loadSpeedSourceFromServer();
    void this.features.settings.loadAnalysisSettingsFromServer();
    void this.features.settings.loadCarsFromServer();
    void this.features.realtime.refreshLoggingStatus();
    void this.features.history.refreshHistory();
    this.features.update.startPolling();
    this.features.espFlash.startPolling();
    this.features.settings.startGpsStatusPolling();
  }

  private startTransportMode(): void {
    const isDemoMode = new URLSearchParams(window.location.search).has("demo");
    if (isDemoMode) {
      runDemoMode({
        state: this.state,
        renderWsState: () => this.renderWsState(),
        applyPayload: (payload) => this.applyPayload(payload),
      });
      return;
    }
    this.connectWs();
  }
}
