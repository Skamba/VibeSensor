import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import "../styles/app.css";
import * as I18N from "../i18n";
import { defaultLocationCodes } from "../constants";
import { SpectrumChart } from "../spectrum";
import { escapeHtml, fmt, fmtTs, formatInt } from "../format";
import { combinedRelativeUncertainty, parseTireSpec, tireDiameterMeters, toleranceForOrder } from "../vehicle_math";
import { adaptServerPayload } from "../server_payload";
import type { AdaptedSpectrum } from "../server_payload";
import type { RotationalSpeeds } from "../server_payload";
import { WsClient } from "../ws";
import { METRIC_FIELDS } from "../generated/shared_contracts";
import { runDemoMode } from "../features/demo/runDemoMode";
import { chartSeriesPalette, orderBandFills } from "../theme";
import { createEmptyMatrix } from "../diagnostics";
import { getSettingsLanguage, setSettingsLanguage, getSettingsSpeedUnit, setSettingsSpeedUnit } from "../api/settings";
import { createUiDomRegistry } from "./dom/ui_dom_registry";
import { createAppState } from "./state/ui_app_state";
import { createHistoryFeature } from "./features/history_feature";
import { createRealtimeFeature } from "./features/realtime_feature";
import { createSettingsFeature } from "./features/settings_feature";
import { createCarsFeature } from "./features/cars_feature";
import { createDashboardFeature } from "./features/dashboard_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { AppState, ChartBand, ClientRow } from "./state/ui_app_state";
import type { UiDomElements } from "./dom/ui_dom_registry";

export function startUiApp(): void {
  const els: UiDomElements = createUiDomRegistry();
  const state: AppState = createAppState();

  const CAR_MAP_POSITIONS: Record<string, { top: number; left: number }> = {
    front_left_wheel: { top: 24, left: 15 }, front_right_wheel: { top: 24, left: 85 }, rear_left_wheel: { top: 72, left: 15 }, rear_right_wheel: { top: 72, left: 85 },
    engine_bay: { top: 18, left: 50 }, front_subframe: { top: 30, left: 50 }, transmission: { top: 42, left: 50 }, driveshaft_tunnel: { top: 52, left: 50 },
    driver_seat: { top: 44, left: 35 }, front_passenger_seat: { top: 44, left: 65 }, rear_left_seat: { top: 60, left: 32 }, rear_center_seat: { top: 60, left: 50 }, rear_right_seat: { top: 60, left: 68 }, rear_subframe: { top: 72, left: 50 }, trunk: { top: 84, left: 50 },
  };
  const SPECTRUM_DB_MIN = 0;
  const SPECTRUM_DB_MAX = 60;
  const SPECTRUM_DB_REFERENCE_AMP_G = 1e-4;
  const SPECTRUM_MIN_RENDER_AMP_G = 1e-6;

  function t(key: string, vars?: Record<string, any>): string { return I18N.get(state.lang, key, vars); }
  function normalizeSpeedUnit(raw: string): string { return raw === "mps" ? "mps" : "kmh"; }
  function saveSpeedUnit(unit: string): void { state.speedUnit = normalizeSpeedUnit(unit); void setSettingsSpeedUnit(state.speedUnit).catch(() => {}); }
  function speedValueInSelectedUnit(speedMps: number | null): number | null { if (!(typeof speedMps === "number") || !Number.isFinite(speedMps)) return null; return state.speedUnit === "mps" ? speedMps : speedMps * 3.6; }
  function selectedSpeedUnitLabel(): string { return state.speedUnit === "mps" ? t("speed.unit.mps") : t("speed.unit.kmh"); }
  function setStatValue(container: HTMLElement | null, value: string | number): void { const valueEl = container?.querySelector?.("[data-value]"); if (valueEl) valueEl.textContent = String(value); else if (container) container.textContent = String(value); }
  function setPillState(el: HTMLElement | null, variant: string, text: string): void { if (!el) return; el.className = `pill pill--${variant}`; el.textContent = text; }
  function colorForClient(index: number): string { return chartSeriesPalette[index % chartSeriesPalette.length]; }
  function effectiveSpeedMps(): number | null { return (typeof state.speedMps === "number" && state.speedMps > 0) ? state.speedMps : null; }

  function renderSpeedReadout(): void {
    if (!els.speed) return;
    const unitLabel = selectedSpeedUnitLabel();
    if (typeof state.speedMps === "number") {
      const value = speedValueInSelectedUnit(state.speedMps);
      const isManualSource = state.speedSource === "manual"
        && typeof state.manualSpeedKph === "number"
        && state.manualSpeedKph > 0;
      const isFallbackOverride = state.gpsFallbackActive
        || latestRotationalSpeeds?.basis_speed_source === "fallback_manual";
      const isOverride = isManualSource || isFallbackOverride;
      els.speed.textContent = t(isOverride ? "speed.override" : "speed.gps", { value: fmt(value!, 1), unit: unitLabel });
      return;
    }
    els.speed.textContent = t("speed.none", { unit: unitLabel });
  }

  let latestRotationalSpeeds: RotationalSpeeds | null = null;

  function rotationalSourceLabel(source: string | null): string {
    if (source === "manual") return t("dashboard.rotational.source.manual");
    if (source === "gps") return t("dashboard.rotational.source.gps");
    if (source === "obd2") return t("dashboard.rotational.source.obd2");
    if (source === "fallback_manual") return t("dashboard.rotational.source.fallback_manual");
    return t("dashboard.rotational.source.unknown");
  }

  function rotationalReasonText(reason: string | null): string {
    if (reason === "speed_unavailable") return t("dashboard.rotational.reason.speed_unavailable");
    if (reason === "invalid_vehicle_settings") return t("dashboard.rotational.reason.invalid_vehicle_settings");
    return t("dashboard.rotational.reason.not_available");
  }

  function rotationalModeText(mode: string | null): string {
    if (mode === "measured") return t("dashboard.rotational.mode.measured");
    if (mode === "calculated") return t("dashboard.rotational.mode.calculated");
    return t("dashboard.rotational.mode.unavailable");
  }

  function renderRotationalSpeeds(): void {
    if (!els.rotationalBasisSource) return;
    const rotational = latestRotationalSpeeds;
    const source = rotationalSourceLabel(rotational?.basis_speed_source ?? null);
    els.rotationalBasisSource.textContent = t("dashboard.rotational.basis_source", { source });

    const rows = [
      { valueEl: els.rotationalWheelValue, modeEl: els.rotationalWheelMode, value: rotational?.wheel ?? null },
      { valueEl: els.rotationalDriveshaftValue, modeEl: els.rotationalDriveshaftMode, value: rotational?.driveshaft ?? null },
      { valueEl: els.rotationalEngineValue, modeEl: els.rotationalEngineMode, value: rotational?.engine ?? null },
    ];

    let displayReason: string | null = null;
    for (const row of rows) {
      if (!row.valueEl || !row.modeEl) continue;
      const rpm = row.value?.rpm;
      row.valueEl.textContent = typeof rpm === "number" && Number.isFinite(rpm)
        ? t("dashboard.rotational.rpm", { value: fmt(rpm, 0) })
        : "--";
      row.modeEl.textContent = rotationalModeText(row.value?.mode ?? null);
      row.modeEl.className = "pill pill--muted rotational-speed-row__mode";
      if (!displayReason && !(typeof rpm === "number" && Number.isFinite(rpm)) && row.value?.reason) {
        displayReason = row.value.reason;
      }
    }

    if (!els.rotationalReason) return;
    if (displayReason) {
      els.rotationalReason.hidden = false;
      els.rotationalReason.textContent = rotationalReasonText(displayReason);
    } else {
      els.rotationalReason.hidden = true;
      els.rotationalReason.textContent = "";
    }

    // Assumptions panel: show speed source, tire spec, gear ratios, calculated Hz
    if (els.rotationalAssumptionsBody) {
      const vs = state.vehicleSettings;
      const speedVal = effectiveSpeedMps();
      const speedDisplay = speedValueInSelectedUnit(speedVal);
      const speedText = speedDisplay != null ? `${fmt(speedDisplay, 1)} ${selectedSpeedUnitLabel()}` : "--";
      const circumference = parseTireSpec({ widthMm: vs.tire_width_mm, aspect: vs.tire_aspect_pct, rimIn: vs.rim_in });
      const circumText = circumference ? `${fmt(Math.PI * tireDiameterMeters(circumference) * 1000, 0)} mm` : "--";
      const bands = rotational?.order_bands;
      const bandText = Array.isArray(bands) && bands.length
        ? bands.map((b) => `${b.key}: ${fmt(b.center_hz, 1)} Hz ±${fmt(b.tolerance * 100, 1)}%`).join(", ")
        : "--";
      els.rotationalAssumptionsBody.innerHTML = [
        `<div>${escapeHtml(t("dashboard.rotational.assumptions.speed_source"))}: ${escapeHtml(source)}</div>`,
        `<div>${escapeHtml(t("dashboard.rotational.assumptions.effective_speed"))}: ${escapeHtml(speedText)}</div>`,
        `<div>${escapeHtml(t("dashboard.rotational.assumptions.tire_circumference"))}: ${escapeHtml(circumText)}</div>`,
        `<div>${escapeHtml(t("dashboard.rotational.assumptions.final_drive"))}: ${escapeHtml(String(vs.final_drive_ratio))}</div>`,
        `<div>${escapeHtml(t("dashboard.rotational.assumptions.gear_ratio"))}: ${escapeHtml(String(vs.current_gear_ratio))}</div>`,
        `<div>${escapeHtml(t("dashboard.rotational.assumptions.order_bands"))}: ${escapeHtml(bandText)}</div>`,
      ].join("");
    }
  }

  function renderWsState(): void {
    if (state.payloadError) return setPillState(els.linkState, "bad", "Payload error");
    const keyByState: Record<string, string> = { connecting: "ws.connecting", connected: "ws.connected", reconnecting: "ws.reconnecting", stale: "ws.stale", no_data: "ws.no_data" };
    const variantByState: Record<string, string> = { connecting: "muted", connected: "ok", reconnecting: "warn", stale: "bad", no_data: "muted" };
    setPillState(els.linkState, variantByState[state.wsState] || "muted", t(keyByState[state.wsState] || "ws.connecting"));

    // Connection status banner
    const banner = els.connectionBanner;
    if (banner) {
      const bannerCfg: Record<string, { key: string; cls: string }> = {
        reconnecting: { key: "ws.banner.reconnecting", cls: "connection-banner--bad" },
        stale: { key: "ws.banner.stale", cls: "connection-banner--warn" },
        connecting: { key: "ws.banner.connecting", cls: "connection-banner--muted" },
      };
      const cfg = bannerCfg[state.wsState];
      if (cfg) {
        banner.hidden = false;
        banner.textContent = t(cfg.key);
        banner.className = `connection-banner ${cfg.cls}`;
      } else {
        banner.hidden = true;
        banner.textContent = "";
        banner.className = "connection-banner";
      }
    }

    // Dim dashboard content when data may be stale or connection is lost
    const wrap = document.querySelector(".wrap");
    if (wrap) {
      const degraded = state.wsState === "reconnecting" || state.wsState === "stale";
      wrap.classList.toggle("wrap--stale", degraded);
    }
  }

  function updateSpectrumOverlay(): void {
    if (!els.spectrumOverlay) return;
    if (state.payloadError) { els.spectrumOverlay.hidden = false; els.spectrumOverlay.textContent = state.payloadError; return; }
    if (!state.hasReceivedPayload && state.wsState === "connecting") { els.spectrumOverlay.hidden = false; els.spectrumOverlay.textContent = t("spectrum.loading"); return; }
    if (state.wsState === "connecting" || state.wsState === "reconnecting") { els.spectrumOverlay.hidden = false; els.spectrumOverlay.textContent = t("ws.connecting"); return; }
    if (state.wsState === "stale") { els.spectrumOverlay.hidden = false; els.spectrumOverlay.textContent = t("spectrum.stale"); return; }
    if (!state.hasSpectrumData) { els.spectrumOverlay.hidden = false; els.spectrumOverlay.textContent = t("spectrum.empty"); return; }
    els.spectrumOverlay.hidden = true;
    els.spectrumOverlay.textContent = "";
  }

  function setActiveView(viewId: string): void {
    const valid = els.views.some((v) => v.id === viewId);
    state.activeViewId = valid ? viewId : "dashboardView";
    for (const view of els.views) { const isActive = view.id === state.activeViewId; view.classList.toggle("active", isActive); view.hidden = !isActive; }
    for (const btn of els.menuButtons) {
      const isActive = btn.dataset.view === state.activeViewId;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-selected", isActive ? "true" : "false");
      btn.tabIndex = isActive ? 0 : -1;
    }
    if (state.activeViewId === "dashboardView" && state.spectrumPlot) state.spectrumPlot.resize();
  }

  // Create features — cross-feature callbacks use lazy references via closures.
  const historyFeature = createHistoryFeature({ state, els, t, escapeHtml, fmt, fmtTs, formatInt });
  const diagnosticsFeature = createDashboardFeature({ state, els, t, fmt, escapeHtml, locationCodeForClient: (c) => sensorsFeature.locationCodeForClient(c), carMapPositions: CAR_MAP_POSITIONS, carMapWindowMs: 10_000, metricField: METRIC_FIELDS.vibration_strength_db });
  const sensorsFeature = createRealtimeFeature({ state, els, t, escapeHtml, formatInt, setPillState, setStatValue, createEmptyMatrix, renderMatrix: () => diagnosticsFeature.renderMatrix(), sendSelection, refreshHistory: () => historyFeature.refreshHistory() });
  const vehicleFeature = createSettingsFeature({ state, els, t, escapeHtml, fmt, renderSpectrum, renderSpeedReadout });
  const wizardFeature = createCarsFeature({ els, escapeHtml, fmt, addCarFromWizard: vehicleFeature.addCarFromWizard });
  const updateFeature = createUpdateFeature({ els, t, escapeHtml });
  const espFlashFeature = createEspFlashFeature({ els, t, escapeHtml });

  function applyLanguage(forceReloadInsights = false): void {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (key) el.innerHTML = t(key);
    });
    if (els.languageSelect) els.languageSelect.value = state.lang;
    if (els.speedUnitSelect) els.speedUnitSelect.value = state.speedUnit;
    state.locationOptions = sensorsFeature.buildLocationOptions(state.locationCodes);
    state.sensorsSettingsSignature = "";
    sensorsFeature.maybeRenderSensorsSettingsList(true);
    renderSpeedReadout();
    renderRotationalSpeeds();
    sensorsFeature.renderLoggingStatus();
    historyFeature.renderHistoryTable();
    diagnosticsFeature.renderVibrationLog();
    diagnosticsFeature.renderMatrix();
    diagnosticsFeature.recreateStrengthChart();
    renderWsState();
    if (state.spectrumPlot) { state.spectrumPlot.destroy(); state.spectrumPlot = null; renderSpectrum(); }
    if (forceReloadInsights) historyFeature.reloadExpandedRunOnLanguageChange();
    updateSpectrumOverlay();
  }

  function vehicleOrdersHz() {
    const speed = effectiveSpeedMps();
    if (!(typeof speed === "number" && speed > 0)) return null;
    const tire = parseTireSpec({ widthMm: state.vehicleSettings.tire_width_mm, aspect: state.vehicleSettings.tire_aspect_pct, rimIn: state.vehicleSettings.rim_in });
    if (!tire) return null;
    const wheelHz = speed / (Math.PI * tireDiameterMeters(tire));
    const driveHz = wheelHz * state.vehicleSettings.final_drive_ratio;
    const engineHz = driveHz * state.vehicleSettings.current_gear_ratio;
    const speedUncertaintyPct = Math.max(0, state.vehicleSettings.speed_uncertainty_pct || 0) / 100;
    const tireUncertaintyPct = Math.max(0, state.vehicleSettings.tire_diameter_uncertainty_pct || 0) / 100;
    const finalDriveUncertaintyPct = Math.max(0, state.vehicleSettings.final_drive_uncertainty_pct || 0) / 100;
    const gearUncertaintyPct = Math.max(0, state.vehicleSettings.gear_uncertainty_pct || 0) / 100;
    const wheelUncertaintyPct = combinedRelativeUncertainty(speedUncertaintyPct, tireUncertaintyPct);
    const driveUncertaintyPct = combinedRelativeUncertainty(wheelUncertaintyPct, finalDriveUncertaintyPct);
    const engineUncertaintyPct = combinedRelativeUncertainty(driveUncertaintyPct, gearUncertaintyPct);
    return { wheelHz, driveHz, engineHz, wheelUncertaintyPct, driveUncertaintyPct, engineUncertaintyPct };
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

  function calculateBandsFromBackend(): ChartBand[] | null {
    const bands = latestRotationalSpeeds?.order_bands;
    if (!Array.isArray(bands) || !bands.length) return null;
    const out: ChartBand[] = [];
    for (const band of bands) {
      const center = Number(band.center_hz);
      const tol = Number(band.tolerance);
      if (!Number.isFinite(center) || center <= 0 || !Number.isFinite(tol)) continue;
      const color = bandKeyColors[band.key] || orderBandFills.wheel1;
      const labelKey = bandKeyLabels[band.key] || band.key;
      out.push({ label: t(labelKey), min_hz: Math.max(0, center * (1 - tol)), max_hz: center * (1 + tol), color });
    }
    return out.length ? out : null;
  }

  function calculateBands(): ChartBand[] {
    // Prefer backend-computed bands (single source of truth)
    const backendBands = calculateBandsFromBackend();
    if (backendBands) return backendBands;
    // Fallback to local calculation when backend bands are not available
    const orders = vehicleOrdersHz();
    if (!orders) return [];
    const mk = (label: string, center: number, spread: number, color: string): ChartBand => ({ label, min_hz: Math.max(0, center * (1 - spread)), max_hz: center * (1 + spread), color });
    const wheelSpread = toleranceForOrder(state.vehicleSettings.wheel_bandwidth_pct, orders.wheelHz, orders.wheelUncertaintyPct, state.vehicleSettings.min_abs_band_hz, state.vehicleSettings.max_band_half_width_pct);
    const driveSpread = toleranceForOrder(state.vehicleSettings.driveshaft_bandwidth_pct, orders.driveHz, orders.driveUncertaintyPct, state.vehicleSettings.min_abs_band_hz, state.vehicleSettings.max_band_half_width_pct);
    const engineSpread = toleranceForOrder(state.vehicleSettings.engine_bandwidth_pct, orders.engineHz, orders.engineUncertaintyPct, state.vehicleSettings.min_abs_band_hz, state.vehicleSettings.max_band_half_width_pct);
    const out: ChartBand[] = [mk(t("bands.wheel_1x"), orders.wheelHz, wheelSpread, orderBandFills.wheel1), mk(t("bands.wheel_2x"), orders.wheelHz * 2, wheelSpread, orderBandFills.wheel2)];
    const overlapTol = Math.max(0.03, orders.driveUncertaintyPct + orders.engineUncertaintyPct);
    if (Math.abs(orders.driveHz - orders.engineHz) / Math.max(1e-6, orders.engineHz) < overlapTol) out.push(mk(t("bands.driveshaft_engine_1x"), orders.driveHz, Math.max(driveSpread, engineSpread), orderBandFills.driveshaftEngine1));
    else { out.push(mk(t("bands.driveshaft_1x"), orders.driveHz, driveSpread, orderBandFills.driveshaft1)); out.push(mk(t("bands.engine_1x"), orders.engineHz, engineSpread, orderBandFills.engine1)); }
    out.push(mk(t("bands.engine_2x"), orders.engineHz * 2, engineSpread, orderBandFills.engine2));
    return out;
  }

  function bandPlugin(): uPlot.Plugin {
    return { hooks: { draw: [(u: uPlot) => { if (!state.chartBands.length) return; const ctx2 = u.ctx; const top = u.bbox.top; const height = u.bbox.height; for (const b of state.chartBands) { if (!(b.max_hz > b.min_hz)) continue; const x1 = u.valToPos(b.min_hz, "x", true); const x2 = u.valToPos(b.max_hz, "x", true); ctx2.fillStyle = b.color; ctx2.fillRect(x1, top, Math.max(1, x2 - x1), height); } }] } };
  }

  function recreateSpectrumPlot(seriesMeta: { id: string; label: string; color: string; values: number[] }[]): void {
    if (state.spectrumPlot) { state.spectrumPlot.destroy(); state.spectrumPlot = null; }
    state.spectrumPlot = new SpectrumChart(els.specChart!, els.spectrumOverlay, 360, els.specChartWrap);
    state.spectrumPlot.ensurePlot(seriesMeta, { title: t("chart.spectrum_title"), axisHz: t("chart.axis.hz"), axisAmplitude: t("chart.axis.amplitude") }, [bandPlugin()]);
  }

  function renderSpectrum(): void {
    const fallbackFreq: number[] = [];
    const entries: { id: string; label: string; color: string; values: number[] }[] = [];
    let targetFreq: number[] = [];
    const interpolateToTarget = (sourceFreq: number[], sourceVals: number[], desiredFreq: number[]): number[] => {
      if (!Array.isArray(sourceFreq) || !Array.isArray(sourceVals)) return [];
      if (!Array.isArray(desiredFreq) || !desiredFreq.length) return sourceVals.slice();
      if (sourceFreq.length !== sourceVals.length || sourceFreq.length < 2) return [];
      const out = new Array(desiredFreq.length); let j = 0;
      for (let i = 0; i < desiredFreq.length; i++) {
        const f = desiredFreq[i]; while (j + 1 < sourceFreq.length && sourceFreq[j + 1] < f) j++;
        if (j + 1 >= sourceFreq.length) { out[i] = sourceVals[sourceVals.length - 1]; continue; }
        const f0 = sourceFreq[j], f1 = sourceFreq[j + 1], v0 = sourceVals[j], v1 = sourceVals[j + 1];
        out[i] = f1 <= f0 ? v0 : v0 + ((v1 - v0) * ((f - f0) / (f1 - f0)));
      }
      return out;
    };
    for (const [i, client] of state.clients.entries()) {
      if (!client?.connected) continue;
      const s = state.spectra.clients?.[client.id];
      if (!s || !Array.isArray(s.combined)) continue;
      const clientFreq = Array.isArray(s.freq) && s.freq.length ? s.freq : fallbackFreq;
      const n = Math.min(clientFreq.length, s.combined.length);
      if (!n) continue;
      let blended = s.combined.slice(0, n); const freqSlice = clientFreq.slice(0, n);
      if (!targetFreq.length) targetFreq = freqSlice;
      else if (freqSlice.length !== targetFreq.length || freqSlice.some((v, idx) => Math.abs(v - targetFreq[idx]) > 1e-6)) blended = interpolateToTarget(freqSlice, blended, targetFreq);
      if (!blended.length) continue;
      entries.push({ id: client.id, label: client.name || client.id, color: colorForClient(i), values: blended });
    }
    const toDbAbsolute = (amp: number): number => {
      const safeAmp = Number.isFinite(amp) && amp > 0
        ? Math.max(amp, SPECTRUM_MIN_RENDER_AMP_G)
        : SPECTRUM_MIN_RENDER_AMP_G;
      const db = 20 * (Math.log10(safeAmp) - Math.log10(SPECTRUM_DB_REFERENCE_AMP_G));
      return Math.max(SPECTRUM_DB_MIN, Math.min(SPECTRUM_DB_MAX, db));
    };
    for (const entry of entries) entry.values = entry.values.map(toDbAbsolute);
    if (!state.spectrumPlot || state.spectrumPlot.getSeriesCount() !== entries.length + 1) recreateSpectrumPlot(entries);
    else state.spectrumPlot.ensurePlot(entries, { title: t("chart.spectrum_title"), axisHz: t("chart.axis.hz"), axisAmplitude: t("chart.axis.amplitude") }, [bandPlugin()]);
    state.spectrumPlot!.renderLegend(els.legend!, entries);
    state.chartBands = calculateBands();
    if (els.bandLegend) {
      els.bandLegend.innerHTML = "";
      for (const b of state.chartBands) {
        const row = document.createElement("div"); row.className = "legend-item";
        row.innerHTML = `<span class="swatch" style="--swatch-color:${escapeHtml(b.color)}"></span><span>${escapeHtml(b.label)}</span>`;
        els.bandLegend.appendChild(row);
      }
    }
    if (!targetFreq.length || !entries.length) { state.hasSpectrumData = false; state.spectrumPlot!.setData([[], ...entries.map(() => [] as number[])]); updateSpectrumOverlay(); return; }
    state.hasSpectrumData = true;
    const minLen = Math.min(targetFreq.length, ...entries.map((e) => e.values.length));
    state.spectrumPlot!.setData([targetFreq.slice(0, minLen), ...entries.map((e) => e.values.slice(0, minLen))]);
    updateSpectrumOverlay();
  }

  function sendSelection(): void { if (state.ws) state.ws.send({ client_id: state.selectedClientId }); }
  function queueRender(): void {
    if (state.renderQueued) return;
    state.renderQueued = true;
    window.requestAnimationFrame(() => {
      state.renderQueued = false;
      const now = Date.now();
      if (now - state.lastRenderTsMs < state.minRenderIntervalMs) return queueRender();
      const payload = state.pendingPayload;
      if (!payload) return;
      state.pendingPayload = null; state.lastRenderTsMs = now; applyPayload(payload);
    });
  }

  function applyPayload(payload: Record<string, any>): void {
    let adapted;
    try { adapted = adaptServerPayload(payload); }
    catch (err) { state.payloadError = err instanceof Error ? err.message : "Invalid server payload."; state.hasSpectrumData = false; renderWsState(); updateSpectrumOverlay(); return; }
    state.payloadError = null; renderWsState();
    const prevSelected = state.selectedClientId;
    state.clients = adapted.clients as unknown as ClientRow[];
    if (adapted.spectra) {
      state.spectra = { clients: Object.fromEntries(Object.entries(adapted.spectra.clients).map(([clientId, spectrum]: [string, AdaptedSpectrum]) => [clientId, { freq: spectrum.freq, strength_metrics: spectrum.strength_metrics as Record<string, any>, combined: spectrum.combined }])) };
    }
    sensorsFeature.updateClientSelection();
    sensorsFeature.maybeRenderSensorsSettingsList();
    sensorsFeature.renderLoggingStatus();
    if (prevSelected !== state.selectedClientId) sendSelection();
    state.speedMps = adapted.speed_mps;
    latestRotationalSpeeds = adapted.rotational_speeds;
    if (adapted.spectra) state.hasSpectrumData = Object.values(adapted.spectra.clients).some((clientSpec: AdaptedSpectrum) => clientSpec.freq.length > 0 && clientSpec.combined.length > 0);
    const hasFreshFrames = diagnosticsFeature.hasFreshSensorFrames(state.clients);
    diagnosticsFeature.applyServerDiagnostics(adapted.diagnostics, hasFreshFrames);
    renderSpeedReadout();
    renderRotationalSpeeds();
    // Prefer confirmed location intensity from backend diagnostics (by_location);
    // fall back to raw spectrum-derived intensity when by_location is empty.
    const confirmedIntensity = diagnosticsFeature.extractConfirmedLocationIntensity();
    const liveIntensity = Object.keys(confirmedIntensity).length
      ? confirmedIntensity
      : diagnosticsFeature.extractLiveLocationIntensity();
    if (Object.keys(liveIntensity).length) diagnosticsFeature.pushCarMapSample(liveIntensity);
    diagnosticsFeature.renderCarMap();
    if (adapted.spectra) renderSpectrum(); else updateSpectrumOverlay();
    sensorsFeature.renderStatus(state.clients.find((c) => c.id === state.selectedClientId));
  }

  function connectWS(): void {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    state.ws = new WsClient({
      url: `${proto}//${window.location.host}/ws`, staleAfterMs: 10000,
      onPayload: (payload) => { state.hasReceivedPayload = true; state.pendingPayload = payload; queueRender(); },
      onStateChange: (nextState) => { state.wsState = nextState; renderWsState(); updateSpectrumOverlay(); if (nextState === "connected" || nextState === "no_data") sendSelection(); },
    });
    state.ws.connect();
  }

  const saveLanguage = (lang: string): void => { state.lang = I18N.normalizeLang(lang); void setSettingsLanguage(state.lang).catch(() => {}); };
  const activateTabByIndex = (index: number): void => {
    if (!els.menuButtons.length) return;
    const safeIndex = ((index % els.menuButtons.length) + els.menuButtons.length) % els.menuButtons.length;
    const btn = els.menuButtons[safeIndex];
    const viewId = btn.dataset.view;
    if (!viewId) return;
    setActiveView(viewId); btn.focus();
  };

  els.menuButtons.forEach((btn, idx) => {
    const onActivate = (): void => { const viewId = btn.dataset.view; if (viewId) setActiveView(viewId); };
    btn.addEventListener("click", onActivate);
    btn.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onActivate(); return; }
      if (ev.key === "ArrowRight") { ev.preventDefault(); activateTabByIndex(idx + 1); return; }
      if (ev.key === "ArrowLeft") { ev.preventDefault(); activateTabByIndex(idx - 1); return; }
      if (ev.key === "Home") { ev.preventDefault(); activateTabByIndex(0); return; }
      if (ev.key === "End") { ev.preventDefault(); activateTabByIndex(els.menuButtons.length - 1); }
    });
  });

  vehicleFeature.bindSettingsTabs();
  wizardFeature.bindWizardHandlers();
  updateFeature.bindUpdateHandlers();
  espFlashFeature.bindHandlers();
  if (els.saveAnalysisBtn) els.saveAnalysisBtn.addEventListener("click", vehicleFeature.saveAnalysisFromInputs);
  if (els.saveSpeedSourceBtn) els.saveSpeedSourceBtn.addEventListener("click", vehicleFeature.saveSpeedSourceFromInputs);
  if (els.headerManualSpeedSaveBtn) {
    els.headerManualSpeedSaveBtn.addEventListener("click", vehicleFeature.saveHeaderManualSpeedFromInput);
  }
  if (els.headerManualSpeedInput) {
    els.headerManualSpeedInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") vehicleFeature.saveHeaderManualSpeedFromInput();
    });
  }
  if (els.startLoggingBtn) els.startLoggingBtn.addEventListener("click", sensorsFeature.startLogging);
  if (els.stopLoggingBtn) els.stopLoggingBtn.addEventListener("click", sensorsFeature.stopLogging);
  if (els.strengthAutoScaleToggle) {
    els.strengthAutoScaleToggle.checked = state.strengthChartAutoScale;
    els.strengthAutoScaleToggle.addEventListener("change", () => {
      state.strengthChartAutoScale = els.strengthAutoScaleToggle!.checked;
    });
  }
  if (els.refreshHistoryBtn) els.refreshHistoryBtn.addEventListener("click", historyFeature.refreshHistory);
  if (els.deleteAllRunsBtn) els.deleteAllRunsBtn.addEventListener("click", () => void historyFeature.deleteAllRuns());
  if (els.historyTableBody) els.historyTableBody.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    const actionEl = target?.closest?.("[data-run-action]") as HTMLElement | null;
    if (actionEl) {
      const action = actionEl.getAttribute("data-run-action");
      const runId = actionEl.getAttribute("data-run") || state.expandedRunId || "";
      if (action !== "download-raw") ev.preventDefault();
      ev.stopPropagation();
      void historyFeature.onHistoryTableAction(action || "", runId);
      return;
    }
    const rowEl = target?.closest?.('tr[data-run-row="1"]') as HTMLElement | null;
    if (rowEl) historyFeature.toggleRunDetails(rowEl.getAttribute("data-run") || "");
  });

  if (els.languageSelect) {
    els.languageSelect.value = state.lang;
    els.languageSelect.addEventListener("change", () => { saveLanguage(els.languageSelect!.value); applyLanguage(true); });
  }
  if (els.speedUnitSelect) {
    els.speedUnitSelect.value = state.speedUnit;
    els.speedUnitSelect.addEventListener("change", () => { saveSpeedUnit(els.speedUnitSelect!.value); renderSpeedReadout(); renderRotationalSpeeds(); });
  }

  vehicleFeature.syncSettingsInputs();
  // Load language and speed unit from server, then apply
  void (async () => {
    try {
      const langRes = await getSettingsLanguage();
      if (langRes?.language) { state.lang = I18N.normalizeLang(langRes.language); applyLanguage(true); }
    } catch (_e) { /* ignore */ }
    try {
      const unitRes = await getSettingsSpeedUnit();
      if (unitRes?.speedUnit) { state.speedUnit = normalizeSpeedUnit(unitRes.speedUnit); if (els.speedUnitSelect) els.speedUnitSelect.value = state.speedUnit; renderSpeedReadout(); renderRotationalSpeeds(); }
    } catch (_e) { /* ignore */ }
  })();
  applyLanguage(false);
  setActiveView("dashboardView");
  void sensorsFeature.refreshLocationOptions();
  void vehicleFeature.loadSpeedSourceFromServer();
  void vehicleFeature.loadAnalysisSettingsFromServer();
  void vehicleFeature.loadCarsFromServer();
  void sensorsFeature.refreshLoggingStatus();
  void historyFeature.refreshHistory();
  updateFeature.startPolling();
  espFlashFeature.startPolling();
  vehicleFeature.startGpsStatusPolling();

  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  if (isDemoMode) runDemoMode({ state, renderWsState, applyPayload });
  else connectWS();
}
