import "uplot/dist/uPlot.min.css";
import * as I18N from "./i18n";
import {
  deleteLog as deleteLogApi,
  getClientLocations,
  getLogInsights,
  getLoggingStatus,
  getLogs,
  getSpeedOverride,
  identifyClient as identifyClientApi,
  logDownloadUrl,
  removeClient as removeClientApi,
  reportPdfUrl,
  setAnalysisSettings,
  setClientLocation as setClientLocationApi,
  setSpeedOverride,
  startLoggingRun,
  stopLoggingRun,
} from "./api";
import { SpectrumChart } from "./spectrum";
import { WsClient, type WsUiState } from "./ws";
  const els: any = {
    menuButtons: Array.from(document.querySelectorAll(".menu-btn")),
    views: Array.from(document.querySelectorAll(".view")),
    languageSelect: document.getElementById("languageSelect"),
    speedUnitSelect: document.getElementById("speedUnitSelect"),
    speed: document.getElementById("speed"),
    loggingStatus: document.getElementById("loggingStatus"),
    currentLogFile: document.getElementById("currentLogFile"),
    startLoggingBtn: document.getElementById("startLoggingBtn"),
    stopLoggingBtn: document.getElementById("stopLoggingBtn"),
    refreshLogsBtn: document.getElementById("refreshLogsBtn"),
    logsSummary: document.getElementById("logsSummary"),
    logsTableBody: document.getElementById("logsTableBody"),
    reportLogSelect: document.getElementById("reportLogSelect"),
    loadInsightsBtn: document.getElementById("loadInsightsBtn"),
    downloadReportBtn: document.getElementById("downloadReportBtn"),
    reportInsights: document.getElementById("reportInsights"),
    clientsSettingsBody: document.getElementById("clientsSettingsBody"),
    lastSeen: document.getElementById("lastSeen"),
    dropped: document.getElementById("dropped"),
    framesTotal: document.getElementById("framesTotal"),
    linkState: document.getElementById("linkState"),
    specChartWrap: document.getElementById("specChartWrap"),
    specChart: document.getElementById("specChart"),
    spectrumOverlay: document.getElementById("spectrumOverlay"),
    legend: document.getElementById("legend"),
    bandLegend: document.getElementById("bandLegend"),
    tireWidthInput: document.getElementById("tireWidthInput"),
    tireAspectInput: document.getElementById("tireAspectInput"),
    rimInput: document.getElementById("rimInput"),
    finalDriveInput: document.getElementById("finalDriveInput"),
    gearRatioInput: document.getElementById("gearRatioInput"),
    wheelBandwidthInput: document.getElementById("wheelBandwidthInput"),
    driveshaftBandwidthInput: document.getElementById("driveshaftBandwidthInput"),
    engineBandwidthInput: document.getElementById("engineBandwidthInput"),
    speedUncertaintyInput: document.getElementById("speedUncertaintyInput"),
    tireDiameterUncertaintyInput: document.getElementById("tireDiameterUncertaintyInput"),
    finalDriveUncertaintyInput: document.getElementById("finalDriveUncertaintyInput"),
    gearUncertaintyInput: document.getElementById("gearUncertaintyInput"),
    minAbsBandHzInput: document.getElementById("minAbsBandHzInput"),
    maxBandHalfWidthInput: document.getElementById("maxBandHalfWidthInput"),
    speedOverrideInput: document.getElementById("speedOverrideInput"),
    applySpeedOverrideBtn: document.getElementById("applySpeedOverrideBtn"),
    saveSettingsBtn: document.getElementById("saveSettingsBtn"),
    vibrationLog: document.getElementById("vibrationLog"),
    vibrationMatrix: document.getElementById("vibrationMatrix"),
    matrixTooltip: document.getElementById("matrixTooltip"),
  };

  const uiLanguageStorageKey = "vibesensor_ui_lang_v1";
  const palette = ["#e63946", "#2a9d8f", "#3a86ff", "#f4a261", "#7b2cbf", "#1d3557", "#ff006e"];
  const defaultLocationCodes = [
    "front_left_wheel",
    "front_right_wheel",
    "rear_left_wheel",
    "rear_right_wheel",
    "transmission",
    "driveshaft_tunnel",
    "engine_bay",
    "front_subframe",
    "rear_subframe",
    "driver_seat",
    "front_passenger_seat",
    "rear_left_seat",
    "rear_center_seat",
    "rear_right_seat",
    "trunk",
  ];
  const settingsStorageKey = "vibesensor_vehicle_settings_v3";
  const speedUnitStorageKey = "vibesensor_speed_unit";
  const bandToleranceModelVersion = 2;
  const treadWearModel = {
    // 10/32 in (~7.9 mm) new to 2/32 in (~1.6 mm) legal minimum.
    new_tread_mm: 7.9,
    worn_tread_mm: 1.6,
    safety_margin_pct: 0.3,
  };
  const sourceColumns = [
    { key: "engine", labelKey: "matrix.source.engine" },
    { key: "driveshaft", labelKey: "matrix.source.driveshaft" },
    { key: "wheel", labelKey: "matrix.source.wheel" },
    { key: "other", labelKey: "matrix.source.other" },
  ];
  const severityBands = [
    { key: "l5", labelKey: "matrix.severity.l5", minDb: 40, maxDb: Number.POSITIVE_INFINITY },
    { key: "l4", labelKey: "matrix.severity.l4", minDb: 34, maxDb: 40 },
    { key: "l3", labelKey: "matrix.severity.l3", minDb: 28, maxDb: 34 },
    { key: "l2", labelKey: "matrix.severity.l2", minDb: 22, maxDb: 28 },
    { key: "l1", labelKey: "matrix.severity.l1", minDb: 16, maxDb: 22 },
  ];
  const multiSyncWindowMs = 500;
  const multiFreqBinHz = 1.5;

  const state: any = {
    ws: null,
    wsState: "connecting" as WsUiState,
    lang: I18N.normalizeLang(window.localStorage.getItem(uiLanguageStorageKey) || "en"),
    speedUnit: normalizeSpeedUnit(window.localStorage.getItem(speedUnitStorageKey) || "kmh"),
    clients: [],
    selectedClientId: null,
    spectrumPlot: null,
    spectra: { freq: [], clients: {} },
    speedMps: null,
    activeViewId: "dashboardView",
    logs: [],
    selectedLogName: null,
    loggingStatus: { enabled: false, current_file: null },
    locationOptions: [],
    vehicleSettings: {
      tire_width_mm: 285,
      tire_aspect_pct: 30,
      rim_in: 21,
      final_drive_ratio: 3.08,
      current_gear_ratio: 0.64,
      wheel_bandwidth_pct: 6.0,
      driveshaft_bandwidth_pct: 5.6,
      engine_bandwidth_pct: 6.2,
      speed_uncertainty_pct: 0.6,
      tire_diameter_uncertainty_pct: 1.2,
      final_drive_uncertainty_pct: 0.2,
      gear_uncertainty_pct: 0.5,
      min_abs_band_hz: 0.4,
      max_band_half_width_pct: 8.0,
      band_tolerance_model_version: bandToleranceModelVersion,
      speed_override_kmh: 100,
    },
    chartBands: [],
    vibrationMessages: [],
    lastDetectionByClient: {},
    lastDetectionGlobal: {},
    recentDetectionEvents: [],
    eventMatrix: createEmptyMatrix(),
    pendingPayload: null,
    renderQueued: false,
    lastRenderTsMs: 0,
    minRenderIntervalMs: 100,
    clientsSettingsSignature: "",
    locationCodes: defaultLocationCodes.slice(),
    hasSpectrumData: false,
    hasReceivedPayload: false,
  };

  function t(key: string, vars?: Record<string, unknown>) {
    return I18N.get(state.lang, key, vars);
  }

  function normalizeSpeedUnit(raw) {
    return raw === "mps" ? "mps" : "kmh";
  }

  function saveSpeedUnit(unit) {
    state.speedUnit = normalizeSpeedUnit(unit);
    window.localStorage.setItem(speedUnitStorageKey, state.speedUnit);
  }

  function speedValueInSelectedUnit(speedMps) {
    if (!(typeof speedMps === "number") || !Number.isFinite(speedMps)) return null;
    if (state.speedUnit === "mps") return speedMps;
    return speedMps * 3.6;
  }

  function selectedSpeedUnitLabel() {
    return state.speedUnit === "mps" ? t("speed.unit.mps") : t("speed.unit.kmh");
  }

  function locationLabelForLang(lang, code) {
    return I18N.get(lang, `location.${code}`, { code });
  }

  function locationLabel(code) {
    return locationLabelForLang(state.lang, code);
  }

  function buildLocationOptions(codes) {
    return codes.map((code) => ({ code, label: locationLabel(code) }));
  }

  function translateStaticDom() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      el.innerHTML = t(key);
    });
  }

  function saveLanguage(lang) {
    state.lang = I18N.normalizeLang(lang);
    window.localStorage.setItem(uiLanguageStorageKey, state.lang);
  }

  function applyLanguage(forceReloadInsights = false) {
    translateStaticDom();
    if (els.languageSelect) {
      els.languageSelect.value = state.lang;
    }
    if (els.speedUnitSelect) {
      els.speedUnitSelect.value = state.speedUnit;
    }
    state.locationOptions = buildLocationOptions(state.locationCodes);
    state.clientsSettingsSignature = "";
    maybeRenderClientsSettingsList(true);
    renderSpeedReadout();
    renderLoggingStatus();
    renderLogsTable();
    renderReportSelect();
    renderVibrationLog();
    renderMatrix();
    renderWsState();
    if (state.spectrumPlot) {
      state.spectrumPlot.destroy();
      state.spectrumPlot = null;
      renderSpectrum();
    }
    if (forceReloadInsights && state.selectedLogName) {
      void loadReportInsights();
    }
    updateSpectrumOverlay();
  }

  Object.assign(state.vehicleSettings, buildRecommendedBandDefaults(state.vehicleSettings));

  function createEmptyMatrix() {
    const matrix = {};
    for (const src of sourceColumns) {
      matrix[src.key] = {};
      for (const band of severityBands) {
        matrix[src.key][band.key] = { count: 0, contributors: {} };
      }
    }
    return matrix;
  }

  function loadVehicleSettings() {
    try {
      const raw = window.localStorage.getItem(settingsStorageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (typeof parsed !== "object" || !parsed) return;
      if (typeof parsed.tire_width_mm === "number") state.vehicleSettings.tire_width_mm = parsed.tire_width_mm;
      if (typeof parsed.tire_aspect_pct === "number") state.vehicleSettings.tire_aspect_pct = parsed.tire_aspect_pct;
      if (typeof parsed.rim_in === "number") state.vehicleSettings.rim_in = parsed.rim_in;
      if (typeof parsed.final_drive_ratio === "number") {
        state.vehicleSettings.final_drive_ratio = parsed.final_drive_ratio;
      }
      if (typeof parsed.current_gear_ratio === "number") {
        state.vehicleSettings.current_gear_ratio = parsed.current_gear_ratio;
      }
      if (typeof parsed.wheel_bandwidth_pct === "number") {
        state.vehicleSettings.wheel_bandwidth_pct = parsed.wheel_bandwidth_pct;
      }
      if (typeof parsed.driveshaft_bandwidth_pct === "number") {
        state.vehicleSettings.driveshaft_bandwidth_pct = parsed.driveshaft_bandwidth_pct;
      }
      if (typeof parsed.engine_bandwidth_pct === "number") {
        state.vehicleSettings.engine_bandwidth_pct = parsed.engine_bandwidth_pct;
      }
      if (typeof parsed.speed_uncertainty_pct === "number") {
        state.vehicleSettings.speed_uncertainty_pct = parsed.speed_uncertainty_pct;
      }
      if (typeof parsed.tire_diameter_uncertainty_pct === "number") {
        state.vehicleSettings.tire_diameter_uncertainty_pct = parsed.tire_diameter_uncertainty_pct;
      }
      if (typeof parsed.final_drive_uncertainty_pct === "number") {
        state.vehicleSettings.final_drive_uncertainty_pct = parsed.final_drive_uncertainty_pct;
      }
      if (typeof parsed.gear_uncertainty_pct === "number") {
        state.vehicleSettings.gear_uncertainty_pct = parsed.gear_uncertainty_pct;
      }
      if (typeof parsed.min_abs_band_hz === "number") {
        state.vehicleSettings.min_abs_band_hz = parsed.min_abs_band_hz;
      }
      if (typeof parsed.max_band_half_width_pct === "number") {
        state.vehicleSettings.max_band_half_width_pct = parsed.max_band_half_width_pct;
      }
      if (typeof parsed.band_tolerance_model_version === "number") {
        state.vehicleSettings.band_tolerance_model_version = parsed.band_tolerance_model_version;
      }
      if (typeof parsed.speed_override_kmh === "number") {
        state.vehicleSettings.speed_override_kmh = parsed.speed_override_kmh;
      }
      if ((state.vehicleSettings.band_tolerance_model_version || 0) < bandToleranceModelVersion) {
        Object.assign(state.vehicleSettings, buildRecommendedBandDefaults(state.vehicleSettings));
      }
      state.vehicleSettings.band_tolerance_model_version = bandToleranceModelVersion;
    } catch (_err) {
      // Ignore malformed local storage values.
    }
  }

  function saveVehicleSettings() {
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(state.vehicleSettings));
  }

  function syncSettingsInputs() {
    els.tireWidthInput.value = String(state.vehicleSettings.tire_width_mm);
    els.tireAspectInput.value = String(state.vehicleSettings.tire_aspect_pct);
    els.rimInput.value = String(state.vehicleSettings.rim_in);
    els.finalDriveInput.value = String(state.vehicleSettings.final_drive_ratio);
    els.gearRatioInput.value = String(state.vehicleSettings.current_gear_ratio);
    els.wheelBandwidthInput.value = String(state.vehicleSettings.wheel_bandwidth_pct);
    els.driveshaftBandwidthInput.value = String(state.vehicleSettings.driveshaft_bandwidth_pct);
    els.engineBandwidthInput.value = String(state.vehicleSettings.engine_bandwidth_pct);
    els.speedUncertaintyInput.value = String(state.vehicleSettings.speed_uncertainty_pct);
    els.tireDiameterUncertaintyInput.value = String(state.vehicleSettings.tire_diameter_uncertainty_pct);
    els.finalDriveUncertaintyInput.value = String(state.vehicleSettings.final_drive_uncertainty_pct);
    els.gearUncertaintyInput.value = String(state.vehicleSettings.gear_uncertainty_pct);
    els.minAbsBandHzInput.value = String(state.vehicleSettings.min_abs_band_hz);
    els.maxBandHalfWidthInput.value = String(state.vehicleSettings.max_band_half_width_pct);
    els.speedOverrideInput.value = String(state.vehicleSettings.speed_override_kmh);
  }

  function fmt(n, digits = 2) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "--";
    return n.toFixed(digits);
  }

  function fmtBytes(bytes) {
    if (!(typeof bytes === "number") || bytes < 0) return "--";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function fmtTs(iso) {
    if (!iso) return "--";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  function formatInt(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "--";
    return new Intl.NumberFormat().format(Math.round(value));
  }

  function setStatValue(container, value) {
    const valueEl = container?.querySelector?.("[data-value]");
    if (valueEl) {
      valueEl.textContent = String(value);
      return;
    }
    if (container) {
      container.textContent = String(value);
    }
  }

  function setPillState(el, variant, text) {
    if (!el) return;
    el.className = `pill pill--${variant}`;
    el.textContent = text;
  }

  function setActiveView(viewId) {
    const valid = els.views.some((v) => v.id === viewId);
    state.activeViewId = valid ? viewId : "dashboardView";
    for (const view of els.views) {
      const isActive = view.id === state.activeViewId;
      view.classList.toggle("active", isActive);
      view.hidden = !isActive;
    }
    for (const btn of els.menuButtons) {
      const isActive = btn.dataset.view === state.activeViewId;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-selected", isActive ? "true" : "false");
      btn.tabIndex = isActive ? 0 : -1;
    }
    if (state.activeViewId === "dashboardView" && state.spectrumPlot) {
      state.spectrumPlot.resize();
    }
  }

  function colorForClient(index) {
    return palette[index % palette.length];
  }

  function parseTireSpec(raw) {
    if (!raw || typeof raw !== "object") return null;
    const widthMm = Number(raw.widthMm);
    const aspect = Number(raw.aspect);
    const rimIn = Number(raw.rimIn);
    if (!(widthMm > 0 && aspect >= 0 && rimIn > 0)) return null;
    return { widthMm, aspect, rimIn };
  }

  function tireDiameterMeters(spec) {
    const sidewallMm = spec.widthMm * (spec.aspect / 100);
    const diameterMm = spec.rimIn * 25.4 + sidewallMm * 2;
    return diameterMm / 1000;
  }

  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }

  function round1(n) {
    return Math.round(n * 10) / 10;
  }

  function rssPct(...parts) {
    let sumSq = 0;
    for (const p of parts) {
      if (typeof p === "number" && p > 0) sumSq += p * p;
    }
    return Math.sqrt(sumSq);
  }

  function buildRecommendedBandDefaults(vehicleSettings) {
    const tire = parseTireSpec({
      widthMm: vehicleSettings.tire_width_mm,
      aspect: vehicleSettings.tire_aspect_pct,
      rimIn: vehicleSettings.rim_in,
    });
    const diameterMm = tire ? tireDiameterMeters(tire) * 1000 : 700;
    const treadLossMm = Math.max(0, treadWearModel.new_tread_mm - treadWearModel.worn_tread_mm);
    const wearSpanPct = (2 * treadLossMm * 100) / Math.max(100, diameterMm);
    const tireUncertaintyPct = clamp((wearSpanPct / 2) + treadWearModel.safety_margin_pct, 0.6, 2.5);
    const speedUncertaintyPct = 0.6;
    const finalDriveUncertaintyPct = 0.2;
    const gearUncertaintyPct = 0.5;

    const wheelUncPct = rssPct(speedUncertaintyPct, tireUncertaintyPct);
    const driveshaftUncPct = rssPct(wheelUncPct, finalDriveUncertaintyPct);
    const engineUncPct = rssPct(driveshaftUncPct, gearUncertaintyPct);

    const wheelBandwidthPct = clamp(2 * ((wheelUncPct * 1.2) + 1.0), 4.0, 12.0);
    const driveshaftBandwidthPct = clamp(2 * ((driveshaftUncPct * 1.2) + 0.9), 4.0, 11.0);
    const engineBandwidthPct = clamp(2 * ((engineUncPct * 1.2) + 1.0), 4.5, 12.0);

    return {
      wheel_bandwidth_pct: round1(wheelBandwidthPct),
      driveshaft_bandwidth_pct: round1(driveshaftBandwidthPct),
      engine_bandwidth_pct: round1(engineBandwidthPct),
      speed_uncertainty_pct: speedUncertaintyPct,
      tire_diameter_uncertainty_pct: round1(tireUncertaintyPct),
      final_drive_uncertainty_pct: finalDriveUncertaintyPct,
      gear_uncertainty_pct: gearUncertaintyPct,
      min_abs_band_hz: 0.4,
      max_band_half_width_pct: 8.0,
      band_tolerance_model_version: bandToleranceModelVersion,
    };
  }

  function effectiveSpeedMps() {
    if (typeof state.speedMps === "number" && state.speedMps > 0) return state.speedMps;
    const overrideMps = (state.vehicleSettings.speed_override_kmh || 0) / 3.6;
    if (overrideMps > 0) return overrideMps;
    return null;
  }

  function renderSpeedReadout() {
    const unitLabel = selectedSpeedUnitLabel();
    if (typeof state.speedMps === "number") {
      const value = speedValueInSelectedUnit(state.speedMps);
      els.speed.textContent = t("speed.gps", { value: fmt(value, 1), unit: unitLabel });
      return;
    }
    const spd = effectiveSpeedMps();
    if (spd) {
      const value = speedValueInSelectedUnit(spd);
      els.speed.textContent = t("speed.override", { value: fmt(value, 1), unit: unitLabel });
      return;
    }
    els.speed.textContent = t("speed.none", { unit: unitLabel });
  }

  function renderWsState() {
    const keyByState = {
      connecting: "ws.connecting",
      connected: "ws.connected",
      reconnecting: "ws.reconnecting",
      stale: "ws.stale",
      no_data: "ws.no_data",
    };
    const key = keyByState[state.wsState] || "ws.connecting";
    const variantByState = {
      connecting: "muted",
      connected: "ok",
      reconnecting: "warn",
      stale: "bad",
      no_data: "muted",
    };
    setPillState(els.linkState, variantByState[state.wsState] || "muted", t(key));
  }

  function updateSpectrumOverlay() {
    if (!els.spectrumOverlay) return;
    if (!state.hasReceivedPayload && state.wsState === "connecting") {
      els.spectrumOverlay.hidden = false;
      els.spectrumOverlay.textContent = t("spectrum.loading");
      return;
    }
    if (state.wsState === "connecting" || state.wsState === "reconnecting") {
      els.spectrumOverlay.hidden = false;
      els.spectrumOverlay.textContent = t("ws.connecting");
      return;
    }
    if (state.wsState === "stale") {
      els.spectrumOverlay.hidden = false;
      els.spectrumOverlay.textContent = t("spectrum.stale");
      return;
    }
    if (!state.hasSpectrumData || state.wsState === "no_data") {
      els.spectrumOverlay.hidden = false;
      els.spectrumOverlay.textContent = t("spectrum.empty");
      return;
    }
    els.spectrumOverlay.hidden = true;
    els.spectrumOverlay.textContent = "";
  }

  function combinedRelativeUncertainty(...parts) {
    let sumSq = 0;
    for (const p of parts) {
      if (typeof p === "number" && p > 0) sumSq += p * p;
    }
    return Math.sqrt(sumSq);
  }

  function toleranceForOrder(baseBandwidthPct, orderHz, uncertaintyPct) {
    const baseHalfRel = Math.max(0, Number(baseBandwidthPct) || 0) / 200.0;
    const absFloor = Math.max(0, state.vehicleSettings.min_abs_band_hz || 0) / Math.max(1, orderHz);
    const maxHalfRel = Math.max(0.005, (state.vehicleSettings.max_band_half_width_pct || 0) / 100.0);
    const combined = Math.sqrt(baseHalfRel * baseHalfRel + uncertaintyPct * uncertaintyPct);
    return Math.min(maxHalfRel, Math.max(combined, absFloor));
  }

  function bandPlugin() {
    return {
      hooks: {
        draw: [
          (u) => {
            if (!state.chartBands.length) return;
            const ctx = u.ctx;
            const top = u.bbox.top;
            const height = u.bbox.height;
            for (const b of state.chartBands) {
              if (!(b.max_hz > b.min_hz)) continue;
              const x1 = u.valToPos(b.min_hz, "x", true);
              const x2 = u.valToPos(b.max_hz, "x", true);
              ctx.fillStyle = b.color;
              ctx.fillRect(x1, top, Math.max(1, x2 - x1), height);
            }
          },
        ],
      },
    };
  }

  function renderBandLegend() {
    if (!els.bandLegend) return;
    if (!state.chartBands.length) {
      els.bandLegend.innerHTML = "";
      return;
    }
    els.bandLegend.innerHTML = "";
    for (const b of state.chartBands) {
      const row = document.createElement("div");
      row.className = "legend-item";
      row.innerHTML = `<span class="swatch" style="background:${b.color}"></span><span>${b.label}</span>`;
      els.bandLegend.appendChild(row);
    }
  }

  function vehicleOrdersHz() {
    const speed = effectiveSpeedMps();
    if (!(typeof speed === "number" && speed > 0)) return null;
    const tire = parseTireSpec({
      widthMm: state.vehicleSettings.tire_width_mm,
      aspect: state.vehicleSettings.tire_aspect_pct,
      rimIn: state.vehicleSettings.rim_in,
    });
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
    return {
      wheelHz,
      driveHz,
      engineHz,
      wheelUncertaintyPct,
      driveUncertaintyPct,
      engineUncertaintyPct,
    };
  }

  function recreateSpectrumPlot(seriesMeta) {
    if (state.spectrumPlot) {
      state.spectrumPlot.destroy();
      state.spectrumPlot = null;
    }
    state.spectrumPlot = new SpectrumChart(els.specChart, els.spectrumOverlay, 360, els.specChartWrap);
    state.spectrumPlot.ensurePlot(
      seriesMeta,
      {
        title: t("chart.spectrum_title"),
        axisHz: t("chart.axis.hz"),
        axisAmplitude: t("chart.axis.amplitude"),
      },
      [bandPlugin()],
    );
  }

  function renderLegend(seriesMeta) {
    if (!state.spectrumPlot) return;
    state.spectrumPlot.renderLegend(els.legend, seriesMeta);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function locationCodeForClient(client) {
    const name = String(client?.name || "").trim();
    if (!name) return "";
    for (const code of state.locationCodes) {
      const labels = I18N.getForAllLangs(`location.${code}`);
      if (labels.some((label) => label === name)) return code;
    }
    const match = state.locationOptions.find((loc) => loc.label === name);
    return match ? match.code : "";
  }

  function locationOptionsMarkup(selectedCode) {
    const opts = [`<option value="">${escapeHtml(t("settings.select_location"))}</option>`];
    for (const loc of state.locationOptions) {
      const selectedAttr = loc.code === selectedCode ? " selected" : "";
      opts.push(
        `<option value="${escapeHtml(loc.code)}"${selectedAttr}>${escapeHtml(loc.label)}</option>`,
      );
    }
    return opts.join("");
  }

  function clientsSettingsSignature() {
    const clientPart = state.clients
      .map((client) => {
        const connected = client.connected ? "1" : "0";
        return `${client.id}|${client.name || ""}|${client.mac_address || ""}|${connected}`;
      })
      .join("||");
    const locationPart = state.locationOptions
      .map((loc) => `${loc.code}|${loc.label}`)
      .join("||");
    return `${clientPart}##${locationPart}`;
  }

  function maybeRenderClientsSettingsList(force = false) {
    const nextSig = clientsSettingsSignature();
    if (!force && nextSig === state.clientsSettingsSignature) return;
    state.clientsSettingsSignature = nextSig;
    renderClientsSettingsList();
  }

  function updateClientSelection() {
    const current = state.selectedClientId;
    const firstConnected = state.clients.find((c) => Boolean(c.connected));
    if (!state.selectedClientId && state.clients.length > 0) {
      state.selectedClientId = firstConnected ? firstConnected.id : state.clients[0].id;
    }
    if (current && state.clients.some((c) => c.id === current)) {
      state.selectedClientId = current;
    }
    if (state.selectedClientId && !state.clients.some((c) => c.id === state.selectedClientId)) {
      state.selectedClientId = firstConnected
        ? firstConnected.id
        : state.clients.length
          ? state.clients[0].id
          : null;
    }
  }

  function renderClientsSettingsList() {
    if (!els.clientsSettingsBody) return;
    if (!state.clients.length) {
      els.clientsSettingsBody.innerHTML = `<tr><td colspan="5">${escapeHtml(t("settings.no_clients"))}</td></tr>`;
      return;
    }
    els.clientsSettingsBody.innerHTML = state.clients
      .map((client) => {
        const selectedCode = locationCodeForClient(client);
        const connected = Boolean(client.connected);
        const statusText = connected ? t("status.online") : t("status.offline");
        const statusClass = connected ? "online" : "offline";
        const macAddress = client.mac_address || client.id;
        return `
      <tr data-client-id="${escapeHtml(client.id)}">
        <td>
          <strong>${escapeHtml(client.name || client.id)}</strong>
          <div class="subtle">${escapeHtml(client.id)}</div>
          <div class="status-pill ${statusClass}">${statusText}</div>
        </td>
        <td><code>${escapeHtml(macAddress)}</code></td>
        <td>
          <select class="row-location-select" data-client-id="${escapeHtml(client.id)}">
            ${locationOptionsMarkup(selectedCode)}
          </select>
        </td>
        <td><button class="btn btn--primary row-identify" data-client-id="${escapeHtml(client.id)}"${connected ? "" : " disabled"}>${escapeHtml(t("actions.identify"))}</button></td>
        <td><button class="btn btn--danger row-remove" data-client-id="${escapeHtml(client.id)}">${escapeHtml(t("actions.remove"))}</button></td>
      </tr>`;
      })
      .join("");

    els.clientsSettingsBody.querySelectorAll(".row-location-select").forEach((select) => {
      select.addEventListener("change", async () => {
        const clientId = select.getAttribute("data-client-id");
        if (!clientId) return;
        const locationCode = select.value || "";
        await setClientLocation(clientId, locationCode);
      });
    });

    els.clientsSettingsBody.querySelectorAll(".row-identify").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (btn.hasAttribute("disabled")) return;
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await identifyClient(clientId);
      });
    });

    els.clientsSettingsBody.querySelectorAll(".row-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await removeClient(clientId);
      });
    });
  }

  function renderStatus(clientRow) {
    if (!clientRow) {
      setStatValue(els.lastSeen, "--");
      setStatValue(els.dropped, "--");
      setStatValue(els.framesTotal, "--");
      return;
    }
    const age = clientRow.last_seen_age_ms ?? null;
    const ageSuffix = state.lang === "nl" ? "ms geleden" : "ms ago";
    const ageValue = age === null ? "--" : `${formatInt(Math.max(0, age))} ${ageSuffix}`;
    setStatValue(els.lastSeen, ageValue);
    setStatValue(els.dropped, formatInt(clientRow.dropped_frames ?? 0));
    setStatValue(els.framesTotal, formatInt(clientRow.frames_total ?? 0));
  }

  async function syncSpeedOverrideToServer(speedKmh) {
    const normalized = typeof speedKmh === "number" && speedKmh > 0 ? speedKmh : null;
    try {
      const payload = await setSpeedOverride(normalized);
      if (typeof payload?.speed_kmh === "number") {
        state.vehicleSettings.speed_override_kmh = payload.speed_kmh;
        els.speedOverrideInput.value = String(payload.speed_kmh);
      }
    } catch (_err) {
      // Ignore transient API errors; UI can still use local override for charting.
    }
  }

  async function loadSpeedOverrideFromServer() {
    try {
      const payload = await getSpeedOverride();
      if (typeof payload?.speed_kmh === "number") {
        state.vehicleSettings.speed_override_kmh = payload.speed_kmh;
        saveVehicleSettings();
        syncSettingsInputs();
        renderSpeedReadout();
      }
    } catch (_err) {
      // Fallback to local override when backend value is unavailable.
    }
  }

  async function syncAnalysisSettingsToServer() {
    const payload = {
      tire_width_mm: state.vehicleSettings.tire_width_mm,
      tire_aspect_pct: state.vehicleSettings.tire_aspect_pct,
      rim_in: state.vehicleSettings.rim_in,
      final_drive_ratio: state.vehicleSettings.final_drive_ratio,
      current_gear_ratio: state.vehicleSettings.current_gear_ratio,
    };
    try {
      await setAnalysisSettings(payload);
    } catch (_err) {
      // Keep UI local settings even if backend update fails transiently.
    }
  }

  function renderLoggingStatus() {
    const status = state.loggingStatus || { enabled: false, current_file: null };
    const on = Boolean(status.enabled);
    setPillState(els.loggingStatus, on ? "ok" : "muted", on ? t("status.running") : t("status.stopped"));
    els.currentLogFile.textContent = t("status.current_file", { value: status.current_file || "--" });
  }

  async function refreshLoggingStatus() {
    try {
      state.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
    }
  }

  async function startLogging() {
    try {
      state.loggingStatus = await startLoggingRun();
      renderLoggingStatus();
      await refreshLogs();
    } catch (_err) {}
  }

  async function stopLogging() {
    try {
      state.loggingStatus = await stopLoggingRun();
      renderLoggingStatus();
      await refreshLogs();
    } catch (_err) {}
  }

  function selectLog(logName) {
    state.selectedLogName = logName || null;
    if (state.selectedLogName) {
      els.reportLogSelect.value = state.selectedLogName;
    }
  }

  function renderReportSelect() {
    els.reportLogSelect.innerHTML = "";
    if (!state.logs.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = t("logs.no_available");
      els.reportLogSelect.appendChild(opt);
      state.selectedLogName = null;
      return;
    }
    for (const row of state.logs) {
      const opt = document.createElement("option");
      opt.value = row.name;
      opt.textContent = row.name;
      els.reportLogSelect.appendChild(opt);
    }
    if (!state.selectedLogName || !state.logs.some((l) => l.name === state.selectedLogName)) {
      state.selectedLogName = state.logs[0].name;
    }
    els.reportLogSelect.value = state.selectedLogName;
  }

  async function refreshLocationOptions() {
    try {
      const payload = await getClientLocations();
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row) => row?.code).filter((code) => typeof code === "string")
        : [];
      state.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    } catch (_err) {
      state.locationCodes = defaultLocationCodes.slice();
      state.locationOptions = buildLocationOptions(state.locationCodes);
    }
    maybeRenderClientsSettingsList(true);
  }

  function renderLogsTable() {
    if (!state.logs.length) {
      els.logsSummary.textContent = t("logs.none");
      els.logsTableBody.innerHTML = `<tr><td colspan="4">${escapeHtml(t("logs.none_found"))}</td></tr>`;
      renderReportSelect();
      return;
    }
    els.logsSummary.textContent = t("logs.available_count", { count: state.logs.length });
    els.logsTableBody.innerHTML = state.logs
      .map(
        (row) => `
      <tr>
        <td>${row.name}</td>
        <td>${fmtTs(row.updated_at)}</td>
        <td class="numeric">${fmtBytes(row.size_bytes)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn--primary select-log-btn" data-log="${row.name}">${escapeHtml(t("logs.use_in_report"))}</button>
            <a class="btn btn--muted" href="${logDownloadUrl(row.name)}" target="_blank" rel="noopener">${escapeHtml(t("logs.raw"))}</a>
            <button class="btn btn--danger delete-log-btn" data-log="${row.name}">${escapeHtml(t("logs.delete"))}</button>
          </div>
        </td>
      </tr>`,
      )
      .join("");
    els.logsTableBody.querySelectorAll(".select-log-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const logName = btn.dataset.log || null;
        selectLog(logName);
        setActiveView("reportView");
      });
    });
    els.logsTableBody.querySelectorAll(".delete-log-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const logName = btn.dataset.log || "";
        await deleteLog(logName);
      });
    });
    renderReportSelect();
  }

  async function refreshLogs() {
    try {
      const payload = await getLogs();
      state.logs = Array.isArray(payload.logs) ? payload.logs : [];
      renderLogsTable();
    } catch (_err) {
      state.logs = [];
      renderLogsTable();
    }
  }

  async function deleteLog(logName) {
    if (!logName) return;
    const ok = window.confirm(t("logs.delete_confirm", { name: logName }));
    if (!ok) return;
    try {
      await deleteLogApi(logName);
    } catch (err) {
      window.alert(err?.message || t("logs.delete_failed"));
      return;
    }
    if (state.selectedLogName === logName) {
      state.selectedLogName = null;
    }
    await refreshLogs();
  }

  function renderInsights(summary) {
    if (!summary || typeof summary !== "object") {
      els.reportInsights.textContent = t("report.no_insights");
      return;
    }
    const findings = Array.isArray(summary.findings) ? summary.findings : [];
    const topFindings = findings
      .slice(0, 4)
      .map((f) => {
        const confidence = typeof f.confidence_0_to_1 === "number" ? fmt(f.confidence_0_to_1, 2) : "0.00";
        const source = f.suspected_source || "unknown";
        const detail = f.evidence_summary || "";
        return `<p><strong>${source}</strong> (${escapeHtml(t("report.confidence", { value: confidence }))}): ${detail}</p>`;
      })
      .join("");
    const speedCoverage = summary?.data_quality?.speed_coverage || {};
    const speedPct =
      typeof speedCoverage.non_null_pct === "number"
        ? `${fmt(speedCoverage.non_null_pct, 1)}%`
        : t("report.missing");
    const speedMin =
      typeof speedCoverage.min_kmh === "number" ? fmt(speedCoverage.min_kmh, 1) : t("report.missing");
    const speedMax =
      typeof speedCoverage.max_kmh === "number" ? fmt(speedCoverage.max_kmh, 1) : t("report.missing");
    const rawSampleRate =
      typeof summary.raw_sample_rate_hz === "number"
        ? `${fmt(summary.raw_sample_rate_hz, 1)} Hz`
        : t("report.missing");
    const skippedReason =
      typeof summary.speed_breakdown_skipped_reason === "string"
        ? `<p><strong>${escapeHtml(t("report.speed_analysis"))}:</strong> ${summary.speed_breakdown_skipped_reason}</p>`
        : "";
    els.reportInsights.innerHTML = `
      <p><strong>${escapeHtml(t("report.file"))}:</strong> ${summary.file_name || "--"}</p>
      <p><strong>${escapeHtml(t("report.run_id"))}:</strong> ${summary.run_id || t("report.missing")}</p>
      <p><strong>${escapeHtml(t("report.duration"))}:</strong> ${fmt(summary.duration_s, 1)} s</p>
      <p><strong>${escapeHtml(t("report.rows"))}:</strong> ${summary.rows || 0}</p>
      <p><strong>${escapeHtml(t("report.raw_sample_rate"))}:</strong> ${rawSampleRate}</p>
      <p><strong>${escapeHtml(t("report.speed_coverage"))}:</strong> ${speedPct} (${speedMin}-${speedMax} km/h)</p>
      <hr />
      ${skippedReason}
      ${topFindings || `<p>${escapeHtml(t("report.no_findings_for_run"))}</p>`}
    `;
  }

  async function loadReportInsights() {
    const logName = els.reportLogSelect.value;
    if (!logName) return;
    selectLog(logName);
    try {
      const summary = await getLogInsights(logName, state.lang);
      renderInsights(summary);
    } catch (_err) {
      els.reportInsights.textContent = t("report.unable_load_insights");
    }
  }

  function downloadReportPdf() {
    const logName = els.reportLogSelect.value;
    if (!logName) return;
    selectLog(logName);
    window.open(reportPdfUrl(logName, state.lang), "_blank", "noopener");
  }

  function calculateBands() {
    const orders = vehicleOrdersHz();
    if (!orders) return [];
    const {
      wheelHz,
      driveHz,
      engineHz,
      wheelUncertaintyPct,
      driveUncertaintyPct,
      engineUncertaintyPct,
    } = orders;
    const mk = (label, center, spread, color) => ({
      label,
      min_hz: Math.max(0, center * (1 - spread)),
      max_hz: center * (1 + spread),
      color,
    });
    const wheelSpread = toleranceForOrder(
      state.vehicleSettings.wheel_bandwidth_pct,
      wheelHz,
      wheelUncertaintyPct,
    );
    const driveSpread = toleranceForOrder(
      state.vehicleSettings.driveshaft_bandwidth_pct,
      driveHz,
      driveUncertaintyPct,
    );
    const engineSpread = toleranceForOrder(
      state.vehicleSettings.engine_bandwidth_pct,
      engineHz,
      engineUncertaintyPct,
    );
    const out = [
      mk(t("bands.wheel_1x"), wheelHz, wheelSpread, "rgba(42,157,143,0.14)"),
      mk(t("bands.wheel_2x"), wheelHz * 2, wheelSpread, "rgba(42,157,143,0.11)"),
    ];
    const overlapTol = Math.max(0.03, driveUncertaintyPct + engineUncertaintyPct);
    if (Math.abs(driveHz - engineHz) / Math.max(1e-6, engineHz) < overlapTol) {
      out.push(
        mk(
          t("bands.driveshaft_engine_1x"),
          driveHz,
          Math.max(driveSpread, engineSpread),
          "rgba(120,95,180,0.15)",
        ),
      );
    } else {
      out.push(mk(t("bands.driveshaft_1x"), driveHz, driveSpread, "rgba(58,134,255,0.14)"));
      out.push(mk(t("bands.engine_1x"), engineHz, engineSpread, "rgba(230,57,70,0.14)"));
    }
    out.push(mk(t("bands.engine_2x"), engineHz * 2, engineSpread, "rgba(230,57,70,0.11)"));
    return out;
  }

  function pushVibrationMessage(text) {
    state.vibrationMessages.unshift({ ts: new Date().toLocaleTimeString(), text });
    state.vibrationMessages = state.vibrationMessages.slice(0, 80);
    renderVibrationLog();
  }

  function renderVibrationLog() {
    if (!state.vibrationMessages.length) {
      els.vibrationLog.innerHTML = `<div class="log-row">${escapeHtml(t("vibration.none"))}</div>`;
      return;
    }
    els.vibrationLog.innerHTML = state.vibrationMessages
      .map((m) => `<div class="log-row"><div class="log-time">${m.ts}</div>${m.text}</div>`)
      .join("");
  }

  function classifyPeak(peakHz) {
    const orders = vehicleOrdersHz();
    const candidates = [];
    if (orders) {
      const {
        wheelHz,
        driveHz,
        engineHz,
        wheelUncertaintyPct,
        driveUncertaintyPct,
        engineUncertaintyPct,
      } = orders;
      const wheelTol = toleranceForOrder(
        state.vehicleSettings.wheel_bandwidth_pct,
        wheelHz,
        wheelUncertaintyPct,
      );
      const driveTol = toleranceForOrder(
        state.vehicleSettings.driveshaft_bandwidth_pct,
        driveHz,
        driveUncertaintyPct,
      );
      const engineTol = toleranceForOrder(
        state.vehicleSettings.engine_bandwidth_pct,
        engineHz,
        engineUncertaintyPct,
      );
      candidates.push({
        cause: t("cause.wheel1"),
        hz: wheelHz,
        tol: wheelTol,
        key: "wheel1",
      });
      candidates.push({
        cause: t("cause.wheel2"),
        hz: wheelHz * 2,
        tol: wheelTol,
        key: "wheel2",
      });
      const overlapTol = Math.max(0.03, driveUncertaintyPct + engineUncertaintyPct);
      if (Math.abs(driveHz - engineHz) / Math.max(1e-6, engineHz) < overlapTol) {
        candidates.push({
          cause: t("cause.shaft_eng1"),
          hz: driveHz,
          tol: Math.max(driveTol, engineTol),
          key: "shaft_eng1",
        });
      } else {
        candidates.push({
          cause: t("cause.shaft1"),
          hz: driveHz,
          tol: driveTol,
          key: "shaft1",
        });
        candidates.push({
          cause: t("cause.eng1"),
          hz: engineHz,
          tol: engineTol,
          key: "eng1",
        });
      }
      candidates.push({
        cause: t("cause.eng2"),
        hz: engineHz * 2,
        tol: engineTol,
        key: "eng2",
      });
    }
    let best = null;
    let bestErr = Number.POSITIVE_INFINITY;
    for (const c of candidates) {
      if (!(c.hz > 0.2)) continue;
      const relErr = Math.abs(peakHz - c.hz) / c.hz;
      if (relErr <= c.tol && relErr < bestErr) {
        best = c;
        bestErr = relErr;
      }
    }
    if (best) return best;
    if (peakHz >= 3 && peakHz <= 12) return { cause: t("cause.road"), key: "road" };
    return { cause: t("cause.other"), key: "other" };
  }

  function sourceKeysFromClassKey(classKey) {
    if (classKey === "shaft_eng1") return ["driveshaft", "engine"];
    if (classKey === "eng1" || classKey === "eng2") return ["engine"];
    if (classKey === "shaft1") return ["driveshaft"];
    if (classKey === "wheel1" || classKey === "wheel2") return ["wheel"];
    return ["other"];
  }

  function severityFromPeak(peakAmp, floorAmp, sensorCount) {
    const db = 20 * Math.log10((Math.max(0, peakAmp) + 1) / (Math.max(0, floorAmp) + 1));
    // Multi-sensor synchronous detections are stronger indicators than single-sensor events.
    const adjustedDb = sensorCount >= 2 ? db + 2 : db;
    for (const band of severityBands) {
      if (adjustedDb >= band.minDb && adjustedDb < band.maxDb) {
        return { key: band.key, labelKey: band.labelKey, db: adjustedDb };
      }
    }
    return null;
  }

  function updateMatrixCell(sourceKey, severityKey, contributorLabel) {
    const src = state.eventMatrix[sourceKey];
    if (!src) return;
    const cell = src[severityKey];
    if (!cell) return;
    cell.count += 1;
    cell.contributors[contributorLabel] = (cell.contributors[contributorLabel] || 0) + 1;
  }

  function updateMatrixCells(sourceKeys, severityKey, contributorLabel) {
    for (const key of sourceKeys) updateMatrixCell(key, severityKey, contributorLabel);
  }

  function tooltipForCell(sourceKey, severityKey) {
    const source = sourceColumns.find((s) => s.key === sourceKey);
    const band = severityBands.find((b) => b.key === severityKey);
    const cell = state.eventMatrix[sourceKey]?.[severityKey];
    if (!cell || cell.count === 0) {
      return `${t(source?.labelKey || sourceKey)} / ${t(band?.labelKey || severityKey)}\n${t("tooltip.no_events")}`;
    }
    const parts = [
      `${t(source?.labelKey || sourceKey)} / ${t(band?.labelKey || severityKey)}`,
      t("tooltip.total_events", { count: cell.count }),
    ];
    const entries = (Object.entries(cell.contributors) as Array<[string, number]>).sort(
      (a, b) => b[1] - a[1],
    );
    if (entries.length) {
      parts.push(t("tooltip.by_sensor_scope"));
      for (const [name, cnt] of entries) parts.push(`- ${name}: ${cnt}`);
    }
    return parts.join("\n");
  }

  function showMatrixTooltip(text, x, y) {
    if (!els.matrixTooltip) return;
    els.matrixTooltip.textContent = text;
    els.matrixTooltip.style.display = "block";
    const pad = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const rect = els.matrixTooltip.getBoundingClientRect();
    let left = x + pad;
    let top = y + pad;
    if (left + rect.width > vw - 8) left = Math.max(8, x - rect.width - pad);
    if (top + rect.height > vh - 8) top = Math.max(8, y - rect.height - pad);
    els.matrixTooltip.style.left = `${left}px`;
    els.matrixTooltip.style.top = `${top}px`;
  }

  function hideMatrixTooltip() {
    if (!els.matrixTooltip) return;
    els.matrixTooltip.style.display = "none";
  }

  function bindMatrixTooltips() {
    if (!els.vibrationMatrix) return;
    const cells = els.vibrationMatrix.querySelectorAll(".vib-cell");
    for (const cell of cells) {
      const sourceKey = cell.getAttribute("data-source");
      const severityKey = cell.getAttribute("data-severity");
      if (!sourceKey || !severityKey) continue;
      cell.addEventListener("mouseenter", (ev) => {
        const text = tooltipForCell(sourceKey, severityKey);
        showMatrixTooltip(text, ev.clientX, ev.clientY);
      });
      cell.addEventListener("mousemove", (ev) => {
        const text = tooltipForCell(sourceKey, severityKey);
        showMatrixTooltip(text, ev.clientX, ev.clientY);
      });
      cell.addEventListener("mouseleave", hideMatrixTooltip);
      cell.addEventListener("blur", hideMatrixTooltip);
    }
  }

  function renderMatrix() {
    if (!els.vibrationMatrix) return;
    hideMatrixTooltip();
    const header = `<thead><tr><th>${escapeHtml(t("matrix.amplitude_group"))}</th>${sourceColumns
      .map((s) => `<th>${escapeHtml(t(s.labelKey))}</th>`)
      .join("")}</tr></thead>`;
    const bodyRows = severityBands
      .map((band) => {
        const cells = sourceColumns
          .map((src) => {
            const val = state.eventMatrix[src.key][band.key].count;
            return `<td class="vib-cell" data-source="${src.key}" data-severity="${band.key}">${val}</td>`;
          })
          .join("");
        return `<tr><td>${escapeHtml(t(band.labelKey))}</td>${cells}</tr>`;
      })
      .join("");
    els.vibrationMatrix.innerHTML = `${header}<tbody>${bodyRows}</tbody>`;
    bindMatrixTooltips();
  }

  function pushRecentEvents(events, nowTs) {
    for (const ev of events) {
      state.recentDetectionEvents.push({
        ts: nowTs,
        sensorId: ev.sensorId,
        sensorLabel: ev.sensorLabel,
        peakHz: ev.peakHz,
        peakAmp: ev.peakAmp,
        floorAmp: ev.floorAmp,
        cls: ev.cls,
      });
    }
    const cutoff = nowTs - multiSyncWindowMs;
    state.recentDetectionEvents = state.recentDetectionEvents.filter((ev) => ev.ts >= cutoff);
  }

  function buildMultiGroupsFromWindow() {
    const grouped = new Map<string, Map<string, any>>();
    for (const ev of state.recentDetectionEvents) {
      const freqBin = Math.round(ev.peakHz / multiFreqBinHz);
      const gKey = `${ev.cls.key}:${freqBin}`;
      if (!grouped.has(gKey)) grouped.set(gKey, new Map());
      const sensorMap = grouped.get(gKey)!;
      const prev = sensorMap.get(ev.sensorId);
      if (!prev || ev.ts > prev.ts) sensorMap.set(ev.sensorId, ev);
    }
    return grouped;
  }

  function renderSpectrum() {
    const fallbackFreq = Array.isArray(state.spectra.freq) ? state.spectra.freq : [];
    const entries = [];
    let targetFreq = [];

    function interpolateToTarget(sourceFreq, sourceVals, desiredFreq) {
      if (!Array.isArray(sourceFreq) || !Array.isArray(sourceVals)) return [];
      if (!Array.isArray(desiredFreq) || !desiredFreq.length) return sourceVals.slice();
      if (sourceFreq.length !== sourceVals.length || sourceFreq.length < 2) return [];

      const out = new Array(desiredFreq.length);
      let j = 0;
      for (let i = 0; i < desiredFreq.length; i++) {
        const f = desiredFreq[i];
        while (j + 1 < sourceFreq.length && sourceFreq[j + 1] < f) {
          j++;
        }
        if (j + 1 >= sourceFreq.length) {
          out[i] = sourceVals[sourceVals.length - 1];
          continue;
        }
        const f0 = sourceFreq[j];
        const f1 = sourceFreq[j + 1];
        const v0 = sourceVals[j];
        const v1 = sourceVals[j + 1];
        if (f1 <= f0) {
          out[i] = v0;
          continue;
        }
        const t = (f - f0) / (f1 - f0);
        out[i] = v0 + ((v1 - v0) * t);
      }
      return out;
    }

    for (const [i, client] of state.clients.entries()) {
      const s = state.spectra.clients?.[client.id];
      if (!s || !Array.isArray(s.x) || !Array.isArray(s.y) || !Array.isArray(s.z)) continue;
      const clientFreq = Array.isArray(s.freq) && s.freq.length ? s.freq : fallbackFreq;
      const n = Math.min(clientFreq.length, s.x.length, s.y.length, s.z.length);
      if (!n) continue;
      let blended = new Array(n);
      for (let j = 0; j < n; j++) {
        blended[j] = Math.sqrt((s.x[j] * s.x[j] + s.y[j] * s.y[j] + s.z[j] * s.z[j]) / 3.0);
      }
      const freqSlice = clientFreq.slice(0, n);
      if (!targetFreq.length) {
        targetFreq = freqSlice;
      } else if (
        freqSlice.length !== targetFreq.length ||
        freqSlice.some((v, idx) => Math.abs(v - targetFreq[idx]) > 1e-6)
      ) {
        blended = interpolateToTarget(freqSlice, blended, targetFreq);
      }
      if (!blended.length) continue;
      entries.push({
        id: client.id,
        label: client.name || client.id,
        color: colorForClient(i),
        values: blended,
      });
    }

    if (!state.spectrumPlot || state.spectrumPlot.getSeriesCount() !== entries.length + 1) {
      recreateSpectrumPlot(entries);
    } else {
      state.spectrumPlot.ensurePlot(
        entries,
        {
          title: t("chart.spectrum_title"),
          axisHz: t("chart.axis.hz"),
          axisAmplitude: t("chart.axis.amplitude"),
        },
        [bandPlugin()],
      );
    }
    renderLegend(entries);
    state.chartBands = calculateBands();
    renderBandLegend();

    if (!targetFreq.length || !entries.length) {
      state.hasSpectrumData = false;
      state.spectrumPlot.setData([[], ...entries.map(() => [])]);
      updateSpectrumOverlay();
      return;
    }
    const minLen = Math.min(targetFreq.length, ...entries.map((e) => e.values.length));
    const data = [targetFreq.slice(0, minLen)];
    for (const e of entries) data.push(e.values.slice(0, minLen));
    state.hasSpectrumData = true;
    state.spectrumPlot.setData(data);
    updateSpectrumOverlay();
    detectVibrationEvents(data, entries);
  }

  function detectVibrationEvents(data, entries) {
    const freq = data[0] || [];
    if (!freq.length) return;
    const sensorEvents = [];

    for (let s = 0; s < entries.length; s++) {
      const vals = data[s + 1];
      if (!Array.isArray(vals) || vals.length < 10) continue;
      const floor = vals.slice(5).sort((a, b) => a - b)[Math.floor(Math.max(1, vals.length - 5) / 2)] || 0;
      const localMaxima = [];
      for (let i = 2; i < vals.length - 2; i++) {
        if (vals[i] > vals[i - 1] && vals[i] >= vals[i + 1]) localMaxima.push(i);
      }
      localMaxima.sort((a, b) => vals[b] - vals[a]);
      const chosen = [];
      for (const idx of localMaxima) {
        if (chosen.length >= 4) break;
        if (vals[idx] <= Math.max(40, floor * 2.6)) continue;
        // Avoid selecting harmonic duplicates that are too close.
        if (chosen.some((j) => Math.abs(freq[j] - freq[idx]) < 1.2)) continue;
        chosen.push(idx);
      }
      for (const idx of chosen) {
        const peakAmp = vals[idx];
        const peakHz = freq[idx];
        const cls = classifyPeak(peakHz);
        sensorEvents.push({
          sensorId: entries[s].id,
          sensorLabel: entries[s].label,
          peakHz,
          peakAmp,
          floorAmp: floor,
          cls,
        });
      }
    }

    const now = Date.now();
    if (!sensorEvents.length) {
      pushRecentEvents([], now);
      return;
    }
    pushRecentEvents(sensorEvents, now);
    const usedSensors = new Set();

    // Group across a sliding time window so slightly out-of-sync sensors still combine.
    const grouped = buildMultiGroupsFromWindow();

    for (const [gKey, sensorMap] of grouped.entries()) {
      const group = Array.from(sensorMap.values());
      if (group.length < 2) continue;
      let sumHz = 0;
      let sumAmp = 0;
      let sumFloor = 0;
      const labels = [];
      for (const ev of group) {
        usedSensors.add(ev.sensorId);
        sumHz += ev.peakHz;
        sumAmp += ev.peakAmp;
        sumFloor += ev.floorAmp;
        labels.push(ev.sensorLabel);
      }
      const avgHz = sumHz / group.length;
      const avgAmp = sumAmp / group.length;
      const avgFloor = sumFloor / group.length;
      const prevGlobal = state.lastDetectionGlobal[gKey];
      if (prevGlobal && now - prevGlobal.ts < 3000 && Math.abs(prevGlobal.hz - avgHz) < 1.2) continue;
      state.lastDetectionGlobal[gKey] = { ts: now, hz: avgHz };
      const sev = severityFromPeak(avgAmp, avgFloor, group.length);
      if (!sev) continue;
      const srcKeys = sourceKeysFromClassKey(group[0].cls.key);
      updateMatrixCells(srcKeys, sev.key, `combined(${labels.join(", ")})`);
      pushVibrationMessage(
        t("msg.multi_detected", {
          count: group.length,
          labels: labels.join(", "),
          hz: fmt(avgHz, 2),
          amp: fmt(avgAmp, 1),
          severity: t(sev.labelKey),
          cause: group[0].cls.cause,
        }),
      );
    }

    for (const ev of sensorEvents) {
      if (usedSensors.has(ev.sensorId)) continue;
      const key = `${ev.sensorId}:${ev.cls.key}`;
      const prev = state.lastDetectionByClient[key];
      if (prev && now - prev.ts < 3500 && Math.abs(prev.hz - ev.peakHz) < 1.0) continue;
      state.lastDetectionByClient[key] = { ts: now, hz: ev.peakHz };
      const sev = severityFromPeak(ev.peakAmp, ev.floorAmp, 1);
      if (!sev) continue;
      const srcKeys = sourceKeysFromClassKey(ev.cls.key);
      updateMatrixCells(srcKeys, sev.key, ev.sensorLabel);
      pushVibrationMessage(
        t("msg.single_detected", {
          sensor: ev.sensorLabel,
          hz: fmt(ev.peakHz, 2),
          amp: fmt(ev.peakAmp, 1),
          severity: t(sev.labelKey),
          cause: ev.cls.cause,
        }),
      );
    }
    renderMatrix();
  }

  function sendSelection() {
    if (state.ws) {
      state.ws.send({ client_id: state.selectedClientId });
    }
  }

  function connectWS() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    state.ws = new WsClient({
      url: `${proto}//${window.location.host}/ws`,
      staleAfterMs: 3000,
      onPayload: (payload) => {
        state.hasReceivedPayload = true;
        state.pendingPayload = payload;
        queueRender();
      },
      onStateChange: (nextState) => {
        state.wsState = nextState;
        renderWsState();
        updateSpectrumOverlay();
        if (nextState === "connected" || nextState === "no_data") {
          sendSelection();
        }
      },
    });
    state.ws.connect();
  }

  function queueRender() {
    if (state.renderQueued) return;
    state.renderQueued = true;
    window.requestAnimationFrame(() => {
      state.renderQueued = false;
      const now = Date.now();
      if (now - state.lastRenderTsMs < state.minRenderIntervalMs) {
        queueRender();
        return;
      }
      const payload = state.pendingPayload;
      if (!payload) return;
      state.pendingPayload = null;
      state.lastRenderTsMs = now;
      applyPayload(payload);
    });
  }

  function applyPayload(payload) {
    const prevSelected = state.selectedClientId;
    state.clients = payload.clients || [];
    if (payload.spectra) {
      state.spectra = payload.spectra;
    }
    updateClientSelection();
    maybeRenderClientsSettingsList();
    if (prevSelected !== state.selectedClientId) {
      sendSelection();
    }

    if (typeof payload.speed_mps === "number") {
      state.speedMps = payload.speed_mps;
    } else {
      state.speedMps = null;
    }
    state.hasSpectrumData =
      Boolean(payload?.spectra?.clients) && Object.keys(payload.spectra.clients || {}).length > 0;
    renderSpeedReadout();
    if (payload.spectra) {
      renderSpectrum();
    } else {
      updateSpectrumOverlay();
    }
    const row = state.clients.find((c) => c.id === state.selectedClientId);
    renderStatus(row);
  }

  async function setClientLocation(clientId, locationCode) {
    if (!clientId) return;
    if (!locationCode) return;
    const existing = state.clients.find((c) => c.id === clientId);
    if (existing && locationCodeForClient(existing) === locationCode) return;
    try {
      await setClientLocationApi(clientId, locationCode);
    } catch (err) {
      window.alert(err?.message || t("actions.set_location_failed"));
      return;
    }
    const selected = state.locationOptions.find((loc) => loc.code === locationCode);
    if (selected) {
      const client = state.clients.find((c) => c.id === clientId);
      if (client) client.name = selected.label;
      maybeRenderClientsSettingsList();
    }
  }

  async function identifyClient(clientId) {
    if (!clientId) return;
    await identifyClientApi(clientId, 1500);
  }

  async function removeClient(clientId) {
    if (!clientId) return;
    const ok = window.confirm(t("actions.remove_client_confirm", { id: clientId }));
    if (!ok) return;
    try {
      await removeClientApi(clientId);
    } catch (err) {
      window.alert(err?.message || t("actions.remove_client_failed"));
      return;
    }

    const prevSelected = state.selectedClientId;
    state.clients = state.clients.filter((c) => c.id !== clientId);
    if (state.selectedClientId === clientId) {
      state.selectedClientId = null;
    }
    updateClientSelection();
    maybeRenderClientsSettingsList();
    if (prevSelected !== state.selectedClientId) {
      sendSelection();
    }
  }

  function saveSettingsFromInputs() {
    const parsed = parseTireSpec({
      widthMm: Number(els.tireWidthInput.value),
      aspect: Number(els.tireAspectInput.value),
      rimIn: Number(els.rimInput.value),
    });
    const finalDrive = Number(els.finalDriveInput.value);
    const gear = Number(els.gearRatioInput.value);
    const wheelBandwidth = Number(els.wheelBandwidthInput.value);
    const driveshaftBandwidth = Number(els.driveshaftBandwidthInput.value);
    const engineBandwidth = Number(els.engineBandwidthInput.value);
    const speedUncertainty = Number(els.speedUncertaintyInput.value);
    const tireDiameterUncertainty = Number(els.tireDiameterUncertaintyInput.value);
    const finalDriveUncertainty = Number(els.finalDriveUncertaintyInput.value);
    const gearUncertainty = Number(els.gearUncertaintyInput.value);
    const minAbsBandHz = Number(els.minAbsBandHzInput.value);
    const maxBandHalfWidth = Number(els.maxBandHalfWidthInput.value);
    const speedOverride = Number(els.speedOverrideInput.value);
    const validBandwidths =
      wheelBandwidth > 0 &&
      wheelBandwidth <= 40 &&
      driveshaftBandwidth > 0 &&
      driveshaftBandwidth <= 40 &&
      engineBandwidth > 0 &&
      engineBandwidth <= 40;
    const validUncertainty =
      speedUncertainty >= 0 &&
      speedUncertainty <= 20 &&
      tireDiameterUncertainty >= 0 &&
      tireDiameterUncertainty <= 20 &&
      finalDriveUncertainty >= 0 &&
      finalDriveUncertainty <= 10 &&
      gearUncertainty >= 0 &&
      gearUncertainty <= 20;
    const validBandLimits =
      minAbsBandHz >= 0 && minAbsBandHz <= 10 && maxBandHalfWidth > 0 && maxBandHalfWidth <= 25;
    if (
      !parsed ||
      !(finalDrive > 0 && gear > 0) ||
      !(speedOverride >= 0) ||
      !validBandwidths ||
      !validUncertainty ||
      !validBandLimits
    ) {
      return;
    }

    state.vehicleSettings.tire_width_mm = parsed.widthMm;
    state.vehicleSettings.tire_aspect_pct = parsed.aspect;
    state.vehicleSettings.rim_in = parsed.rimIn;
    state.vehicleSettings.final_drive_ratio = finalDrive;
    state.vehicleSettings.current_gear_ratio = gear;
    state.vehicleSettings.wheel_bandwidth_pct = wheelBandwidth;
    state.vehicleSettings.driveshaft_bandwidth_pct = driveshaftBandwidth;
    state.vehicleSettings.engine_bandwidth_pct = engineBandwidth;
    state.vehicleSettings.speed_uncertainty_pct = speedUncertainty;
    state.vehicleSettings.tire_diameter_uncertainty_pct = tireDiameterUncertainty;
    state.vehicleSettings.final_drive_uncertainty_pct = finalDriveUncertainty;
    state.vehicleSettings.gear_uncertainty_pct = gearUncertainty;
    state.vehicleSettings.min_abs_band_hz = minAbsBandHz;
    state.vehicleSettings.max_band_half_width_pct = maxBandHalfWidth;
    state.vehicleSettings.band_tolerance_model_version = bandToleranceModelVersion;
    state.vehicleSettings.speed_override_kmh = speedOverride;
    saveVehicleSettings();
    void syncAnalysisSettingsToServer();
    void syncSpeedOverrideToServer(state.vehicleSettings.speed_override_kmh);
    renderSpectrum();
    renderSpeedReadout();
  }

  function applySpeedOverrideFromInput() {
    const speedOverride = Number(els.speedOverrideInput.value);
    if (!(speedOverride >= 0)) return;
    state.vehicleSettings.speed_override_kmh = speedOverride;
    saveVehicleSettings();
    void syncSpeedOverrideToServer(state.vehicleSettings.speed_override_kmh);
    renderSpectrum();
    renderSpeedReadout();
  }

  function activateTabByIndex(index) {
    if (!els.menuButtons.length) return;
    const safeIndex = ((index % els.menuButtons.length) + els.menuButtons.length) % els.menuButtons.length;
    const btn = els.menuButtons[safeIndex];
    const viewId = btn.dataset.view;
    if (!viewId) return;
    setActiveView(viewId);
    btn.focus();
  }

  els.menuButtons.forEach((btn, idx) => {
    const onActivate = () => {
      const viewId = btn.dataset.view;
      if (viewId) setActiveView(viewId);
    };
    btn.addEventListener("click", onActivate);
    btn.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        onActivate();
        return;
      }
      if (ev.key === "ArrowRight") {
        ev.preventDefault();
        activateTabByIndex(idx + 1);
        return;
      }
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        activateTabByIndex(idx - 1);
        return;
      }
      if (ev.key === "Home") {
        ev.preventDefault();
        activateTabByIndex(0);
        return;
      }
      if (ev.key === "End") {
        ev.preventDefault();
        activateTabByIndex(els.menuButtons.length - 1);
      }
    });
  });
  els.startLoggingBtn.addEventListener("click", startLogging);
  els.stopLoggingBtn.addEventListener("click", stopLogging);
  els.refreshLogsBtn.addEventListener("click", refreshLogs);
  els.reportLogSelect.addEventListener("change", () => selectLog(els.reportLogSelect.value || null));
  els.loadInsightsBtn.addEventListener("click", loadReportInsights);
  els.downloadReportBtn.addEventListener("click", downloadReportPdf);
  if (els.applySpeedOverrideBtn) {
    els.applySpeedOverrideBtn.addEventListener("click", applySpeedOverrideFromInput);
  }
  if (els.languageSelect) {
    els.languageSelect.value = state.lang;
    els.languageSelect.addEventListener("change", () => {
      saveLanguage(els.languageSelect.value);
      applyLanguage(true);
    });
  }
  if (els.speedUnitSelect) {
    els.speedUnitSelect.value = state.speedUnit;
    els.speedUnitSelect.addEventListener("change", () => {
      saveSpeedUnit(els.speedUnitSelect.value);
      renderSpeedReadout();
    });
  }
  els.speedOverrideInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      applySpeedOverrideFromInput();
    }
  });
  els.saveSettingsBtn.addEventListener("click", saveSettingsFromInputs);

  loadVehicleSettings();
  syncSettingsInputs();
  applyLanguage(false);
  setActiveView("dashboardView");
  refreshLocationOptions();
  void loadSpeedOverrideFromServer();
  void syncAnalysisSettingsToServer();
  void syncSpeedOverrideToServer(state.vehicleSettings.speed_override_kmh);
  refreshLoggingStatus();
  refreshLogs();
  connectWS();
