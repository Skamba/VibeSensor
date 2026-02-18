import "uplot/dist/uPlot.min.css";
import uPlot from "uplot";
import "./styles/app.css";
import * as I18N from "./i18n";
import type { CarRecord, CarLibraryModel, CarLibraryGearbox, CarLibraryTireOption } from "./api";
import {
  deleteHistoryRun as deleteHistoryRunApi,
  getAnalysisSettings,
  getCarLibraryBrands,
  getCarLibraryModels,
  getCarLibraryTypes,
  getClientLocations,
  getHistoryInsights,
  getLoggingStatus,
  getHistory,
  getSettingsCars,
  getSettingsSpeedSource,
  getSpeedOverride,
  identifyClient as identifyClientApi,
  historyExportUrl,
  removeClient as removeClientApi,
  historyReportPdfUrl,
  setAnalysisSettings,
  setClientLocation as setClientLocationApi,
  setSpeedOverride,
  startLoggingRun,
  stopLoggingRun,
  addSettingsCar,
  updateSettingsCar,
  deleteSettingsCar,
  setActiveSettingsCar,
  updateSettingsSpeedSource,
} from "./api";
import {
  defaultLocationCodes,
  palette,
  sourceColumns,
} from "./constants";
import { SpectrumChart } from "./spectrum";
import {
  createEmptyMatrix,
  normalizeStrengthBands,
  type StrengthBand,
} from "./diagnostics";
import { orderBandFills } from "./theme";
import { escapeHtml, fmt, fmtBytes, fmtTs, formatInt } from "./format";
import {
  combinedRelativeUncertainty,
  parseTireSpec,
  tireDiameterMeters,
  toleranceForOrder,
} from "./vehicle_math";
import { adaptServerPayload } from "./server_payload";
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
    refreshHistoryBtn: document.getElementById("refreshHistoryBtn"),
    deleteAllRunsBtn: document.getElementById("deleteAllRunsBtn"),
    historySummary: document.getElementById("historySummary"),
    historyTableBody: document.getElementById("historyTableBody"),
    sensorsSettingsBody: document.getElementById("sensorsSettingsBody"),
    lastSeen: document.getElementById("lastSeen"),
    dropped: document.getElementById("dropped"),
    framesTotal: document.getElementById("framesTotal"),
    linkState: document.getElementById("linkState"),
    specChartWrap: document.getElementById("specChartWrap"),
    specChart: document.getElementById("specChart"),
    spectrumOverlay: document.getElementById("spectrumOverlay"),
    legend: document.getElementById("legend"),
    bandLegend: document.getElementById("bandLegend"),
    strengthChart: document.getElementById("strengthChart"),
    strengthTooltip: document.getElementById("strengthTooltip"),
    liveCarMapDots: document.getElementById("liveCarMapDots"),
    // Analysis tab inputs
    wheelBandwidthInput: document.getElementById("wheelBandwidthInput"),
    driveshaftBandwidthInput: document.getElementById("driveshaftBandwidthInput"),
    engineBandwidthInput: document.getElementById("engineBandwidthInput"),
    speedUncertaintyInput: document.getElementById("speedUncertaintyInput"),
    tireDiameterUncertaintyInput: document.getElementById("tireDiameterUncertaintyInput"),
    finalDriveUncertaintyInput: document.getElementById("finalDriveUncertaintyInput"),
    gearUncertaintyInput: document.getElementById("gearUncertaintyInput"),
    minAbsBandHzInput: document.getElementById("minAbsBandHzInput"),
    maxBandHalfWidthInput: document.getElementById("maxBandHalfWidthInput"),
    saveAnalysisBtn: document.getElementById("saveAnalysisBtn"),
    // Car tab
    carListBody: document.getElementById("carListBody"),
    addCarBtn: document.getElementById("addCarBtn"),
    addCarWizard: document.getElementById("addCarWizard"),
    wizardCloseBtn: document.getElementById("wizardCloseBtn"),
    wizardBackBtn: document.getElementById("wizardBackBtn"),
    // Speed source tab
    manualSpeedInput: document.getElementById("manualSpeedInput"),
    saveSpeedSourceBtn: document.getElementById("saveSpeedSourceBtn"),
    // Settings sub-tabs
    settingsTabs: Array.from(document.querySelectorAll(".settings-tab")),
    settingsTabPanels: Array.from(document.querySelectorAll(".settings-tab-panel")),
    vibrationLog: document.getElementById("vibrationLog"),
    vibrationMatrix: document.getElementById("vibrationMatrix"),
    matrixTooltip: document.getElementById("matrixTooltip"),
  };

  const uiLanguageStorageKey = "vibesensor_ui_lang_v1";
  const settingsStorageKey = "vibesensor_vehicle_settings_v3";
  const speedUnitStorageKey = "vibesensor_speed_unit";

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
    runs: [],
    deleteAllRunsInFlight: false,
    expandedRunId: null,
    runDetailsById: {},
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
    },
    // Car management
    cars: [] as CarRecord[],
    activeCarId: null as string | null,
    // Speed source
    speedSource: "gps" as string,
    manualSpeedKph: null as number | null,
    chartBands: [],
    vibrationMessages: [],
    strengthBands: normalizeStrengthBands([]),
    eventMatrix: createEmptyMatrix(),
    pendingPayload: null,
    renderQueued: false,
    lastRenderTsMs: 0,
    minRenderIntervalMs: 100,
    sensorsSettingsSignature: "",
    locationCodes: defaultLocationCodes.slice(),
    hasSpectrumData: false,
    hasReceivedPayload: false,
    payloadError: null as string | null,
    strengthPlot: null,
    strengthHoverText: "",
    strengthFrameTotalsByClient: {},
    strengthHistory: {
      t: [],
      wheel: [],
      driveshaft: [],
      engine: [],
      other: [],
    },
    // Car map rolling window
    carMapSamples: [] as Array<{ ts: number; byLocation: Record<string, number> }>,
    carMapPulseLocations: new Set<string>(),
  };

  // Car map location positions (% from top-left of the car-map container).
  // Uses the report's canonical location codes from pi/vibesensor/locations.py.
  const CAR_MAP_POSITIONS: Record<string, { top: number; left: number }> = {
    front_left_wheel:     { top: 24, left: 15 },
    front_right_wheel:    { top: 24, left: 85 },
    rear_left_wheel:      { top: 72, left: 15 },
    rear_right_wheel:     { top: 72, left: 85 },
    engine_bay:           { top: 18, left: 50 },
    front_subframe:       { top: 30, left: 50 },
    transmission:         { top: 42, left: 50 },
    driveshaft_tunnel:    { top: 52, left: 50 },
    driver_seat:          { top: 44, left: 35 },
    front_passenger_seat: { top: 44, left: 65 },
    rear_left_seat:       { top: 60, left: 32 },
    rear_center_seat:     { top: 60, left: 50 },
    rear_right_seat:      { top: 60, left: 68 },
    rear_subframe:        { top: 72, left: 50 },
    trunk:                { top: 84, left: 50 },
  };

  const CAR_MAP_WINDOW_MS = 10_000;

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
    state.sensorsSettingsSignature = "";
    maybeRenderSensorsSettingsList(true);
    renderSpeedReadout();
    renderLoggingStatus();
    renderHistoryTable();
    renderVibrationLog();
    renderMatrix();
    renderWsState();
    if (state.spectrumPlot) {
      state.spectrumPlot.destroy();
      state.spectrumPlot = null;
      renderSpectrum();
    }
    if (forceReloadInsights && state.expandedRunId) {
      const runId = state.expandedRunId;
      const detail = state.runDetailsById?.[runId];
      const shouldReloadInsights = Boolean(detail?.insights);
      delete state.runDetailsById[runId];
      void loadRunPreview(runId, true).then(() => {
        if (shouldReloadInsights) {
          void loadRunInsights(runId, true);
        }
      });
    }
    updateSpectrumOverlay();
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
    } catch (_err) {
      // Ignore malformed local storage values.
    }
  }

  function saveVehicleSettings() {
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(state.vehicleSettings));
  }

  function syncSettingsInputs() {
    // Analysis tab inputs only (bandwidths + uncertainties)
    if (els.wheelBandwidthInput) els.wheelBandwidthInput.value = String(state.vehicleSettings.wheel_bandwidth_pct);
    if (els.driveshaftBandwidthInput) els.driveshaftBandwidthInput.value = String(state.vehicleSettings.driveshaft_bandwidth_pct);
    if (els.engineBandwidthInput) els.engineBandwidthInput.value = String(state.vehicleSettings.engine_bandwidth_pct);
    if (els.speedUncertaintyInput) els.speedUncertaintyInput.value = String(state.vehicleSettings.speed_uncertainty_pct);
    if (els.tireDiameterUncertaintyInput) els.tireDiameterUncertaintyInput.value = String(state.vehicleSettings.tire_diameter_uncertainty_pct);
    if (els.finalDriveUncertaintyInput) els.finalDriveUncertaintyInput.value = String(state.vehicleSettings.final_drive_uncertainty_pct);
    if (els.gearUncertaintyInput) els.gearUncertaintyInput.value = String(state.vehicleSettings.gear_uncertainty_pct);
    if (els.minAbsBandHzInput) els.minAbsBandHzInput.value = String(state.vehicleSettings.min_abs_band_hz);
    if (els.maxBandHalfWidthInput) els.maxBandHalfWidthInput.value = String(state.vehicleSettings.max_band_half_width_pct);
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

  function effectiveSpeedMps() {
    if (typeof state.speedMps === "number" && state.speedMps > 0) return state.speedMps;
    return null;
  }

  function renderSpeedReadout() {
    const unitLabel = selectedSpeedUnitLabel();
    if (typeof state.speedMps === "number") {
      const value = speedValueInSelectedUnit(state.speedMps);
      const isOverride = state.speedSource === "manual" && typeof state.manualSpeedKph === "number" && state.manualSpeedKph > 0;
      const key = isOverride ? "speed.override" : "speed.gps";
      els.speed.textContent = t(key, { value: fmt(value, 1), unit: unitLabel });
      return;
    }
    els.speed.textContent = t("speed.none", { unit: unitLabel });
  }

  function renderWsState() {
    if (state.payloadError) {
      setPillState(els.linkState, "bad", "Payload error");
      return;
    }
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
    if (state.payloadError) {
      els.spectrumOverlay.hidden = false;
      els.spectrumOverlay.textContent = state.payloadError;
      return;
    }
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
    if (!state.hasSpectrumData) {
      els.spectrumOverlay.hidden = false;
      els.spectrumOverlay.textContent = t("spectrum.empty");
      return;
    }
    els.spectrumOverlay.hidden = true;
    els.spectrumOverlay.textContent = "";
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
      row.innerHTML = `<span class="swatch" style="--swatch-color:${b.color}"></span><span>${b.label}</span>`;
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

  function locationCodeForClient(client) {
    const explicitCode = String(client?.location_code || client?.locationCode || "").trim();
    if (explicitCode && state.locationCodes.includes(explicitCode)) {
      return explicitCode;
    }

    const name = String(client?.name || "").trim();
    if (!name) return "";

    const normalizedName = name.toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    const shorthandMap: Record<string, string> = {
      "front left": "front_left_wheel",
      "front right": "front_right_wheel",
      "rear left": "rear_left_wheel",
      "rear right": "rear_right_wheel",
      "driver": "driver_seat",
    };
    for (const [token, code] of Object.entries(shorthandMap)) {
      if (normalizedName.includes(token) && state.locationCodes.includes(code)) {
        return code;
      }
    }

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

  function sensorsSettingsSignature() {
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

  function maybeRenderSensorsSettingsList(force = false) {
    const nextSig = sensorsSettingsSignature();
    if (!force && nextSig === state.sensorsSettingsSignature) return;
    state.sensorsSettingsSignature = nextSig;
    renderSensorsSettingsList();
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

  function renderSensorsSettingsList() {
    if (!els.sensorsSettingsBody) return;
    if (!state.clients.length) {
      els.sensorsSettingsBody.innerHTML = `<tr><td colspan="5">${escapeHtml(t("settings.sensors.no_sensors"))}</td></tr>`;
      return;
    }
    els.sensorsSettingsBody.innerHTML = state.clients
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

    els.sensorsSettingsBody.querySelectorAll(".row-location-select").forEach((select) => {
      select.addEventListener("change", async () => {
        const clientId = select.getAttribute("data-client-id");
        if (!clientId) return;
        const locationCode = select.value || "";
        await setClientLocation(clientId, locationCode);
      });
    });

    els.sensorsSettingsBody.querySelectorAll(".row-identify").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (btn.hasAttribute("disabled")) return;
        const clientId = btn.getAttribute("data-client-id");
        if (!clientId) return;
        await identifyClient(clientId);
      });
    });

    els.sensorsSettingsBody.querySelectorAll(".row-remove").forEach((btn) => {
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

  async function syncSpeedSourceToServer() {
    try {
      await updateSettingsSpeedSource({
        speedSource: state.speedSource,
        manualSpeedKph: state.manualSpeedKph,
      });
      // Also sync legacy speed-override endpoint
      if (state.speedSource === "manual" && state.manualSpeedKph != null) {
        await setSpeedOverride(state.manualSpeedKph);
      } else {
        await setSpeedOverride(null);
      }
    } catch (_err) {
      // Ignore transient API errors.
    }
  }

  async function loadSpeedSourceFromServer() {
    try {
      const payload = await getSettingsSpeedSource();
      if (payload && typeof payload === "object") {
        if (typeof payload.speedSource === "string") state.speedSource = payload.speedSource;
        state.manualSpeedKph = typeof payload.manualSpeedKph === "number" ? payload.manualSpeedKph : null;
        syncSpeedSourceInputs();
        renderSpeedReadout();
      }
    } catch (_err) {
      // Fallback to defaults.
    }
  }

  function syncSpeedSourceInputs() {
    const radios = document.querySelectorAll<HTMLInputElement>('input[name="speedSourceRadio"]');
    radios.forEach((r) => { r.checked = r.value === state.speedSource; });
    if (els.manualSpeedInput) {
      els.manualSpeedInput.value = state.manualSpeedKph != null ? String(state.manualSpeedKph) : "";
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

  async function loadAnalysisSettingsFromServer() {
    try {
      const serverSettings = await getAnalysisSettings();
      if (serverSettings && typeof serverSettings === "object") {
        for (const key of Object.keys(serverSettings)) {
          if (typeof serverSettings[key] === "number") {
            state.vehicleSettings[key] = serverSettings[key];
          }
        }
        saveVehicleSettings();
        syncSettingsInputs();
        renderSpectrum();
      }
    } catch (_err) {
      // Keep UI local defaults when server is unreachable.
    }
  }

  async function loadCarsFromServer() {
    try {
      const payload = await getSettingsCars();
      if (Array.isArray(payload?.cars)) {
        state.cars = payload.cars;
        state.activeCarId = payload.activeCarId || (payload.cars[0]?.id ?? null);
        syncCarSelector();
        syncActiveCarToInputs();
      }
    } catch (_err) {
      // Keep defaults.
    }
  }

  function syncCarSelector() {
    // Replaced by renderCarList
    renderCarList();
  }

  function renderCarList() {
    if (!els.carListBody) return;
    if (!state.cars.length) {
      els.carListBody.innerHTML = `<tr><td colspan="7">${escapeHtml(t("settings.car.no_cars"))}</td></tr>`;
      return;
    }
    els.carListBody.innerHTML = state.cars
      .map((car) => {
        const isActive = car.id === state.activeCarId;
        const a = car.aspects || {};
        const tireStr = `${a.tire_width_mm || "?"}/${a.tire_aspect_pct || "?"}R${a.rim_in || "?"}`;
        const driveStr = `${fmt(a.final_drive_ratio, 2)}`;
        const gearStr = `${fmt(a.current_gear_ratio, 2)}`;
        return `<tr data-car-id="${escapeHtml(car.id)}">
          <td><span class="car-active-pill ${isActive ? "active" : "inactive"}">${isActive ? escapeHtml(t("settings.car.active_label")) : escapeHtml(t("settings.car.inactive_label"))}</span></td>
          <td><strong>${escapeHtml(car.name)}</strong></td>
          <td>${escapeHtml(car.type)}</td>
          <td><code>${escapeHtml(tireStr)}</code></td>
          <td>${escapeHtml(driveStr)}</td>
          <td>${escapeHtml(gearStr)}</td>
          <td class="car-list-actions">${isActive ? "" : `<button class="btn btn--success car-activate-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.activate"))}</button>`}<button class="btn btn--danger car-delete-btn" data-car-id="${escapeHtml(car.id)}">${escapeHtml(t("settings.car.delete"))}</button></td>
        </tr>`;
      })
      .join("");

    els.carListBody.querySelectorAll(".car-activate-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const carId = btn.getAttribute("data-car-id");
        if (!carId) return;
        try {
          const result = await setActiveSettingsCar(carId);
          if (result?.cars) {
            state.cars = result.cars;
            state.activeCarId = result.activeCarId;
            syncActiveCarToInputs();
            renderCarList();
            renderSpectrum();
          }
        } catch (_err) {}
      });
    });

    els.carListBody.querySelectorAll(".car-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const carId = btn.getAttribute("data-car-id");
        if (!carId) return;
        const car = state.cars.find((c) => c.id === carId);
        if (state.cars.length <= 1) {
          window.alert(t("settings.car.cannot_delete_last"));
          return;
        }
        const ok = window.confirm(t("settings.car.delete_confirm", { name: car?.name || "" }));
        if (!ok) return;
        try {
          const result = await deleteSettingsCar(carId);
          if (result?.cars) {
            state.cars = result.cars;
            state.activeCarId = result.activeCarId;
            syncActiveCarToInputs();
            renderCarList();
            renderSpectrum();
          }
        } catch (_err) {}
      });
    });
  }

  function syncActiveCarToInputs() {
    const car = state.cars.find((c) => c.id === state.activeCarId);
    if (!car) return;
    // Push aspects into vehicleSettings
    if (car.aspects && typeof car.aspects === "object") {
      for (const key of Object.keys(car.aspects)) {
        if (typeof car.aspects[key] === "number") {
          state.vehicleSettings[key] = car.aspects[key];
        }
      }
    }
    saveVehicleSettings();
    syncSettingsInputs();
  }

  function renderLoggingStatus() {
    const status = state.loggingStatus || { enabled: false, current_file: null };
    const on = Boolean(status.enabled);
    const hasActiveClients = state.clients.some((client) => Boolean(client?.connected));
    setPillState(els.loggingStatus, on ? "ok" : "muted", on ? t("status.running") : t("status.stopped"));
    els.currentLogFile.textContent = t("status.current_file", { value: status.current_file || "--" });
    if (els.startLoggingBtn) {
      els.startLoggingBtn.disabled = !hasActiveClients;
    }
    if (els.stopLoggingBtn) {
      els.stopLoggingBtn.disabled = !hasActiveClients;
    }
  }

  async function refreshLoggingStatus() {
    try {
      state.loggingStatus = await getLoggingStatus();
      renderLoggingStatus();
    } catch (_err) {
      setPillState(els.loggingStatus, "bad", t("status.unavailable"));
    }
  }

  function resetLiveVibrationCounts() {
    state.eventMatrix = createEmptyMatrix();
    renderMatrix();
  }

  async function startLogging() {
    try {
      state.loggingStatus = await startLoggingRun();
      resetLiveVibrationCounts();
      renderLoggingStatus();
      await refreshHistory();
    } catch (_err) {}
  }

  async function stopLogging() {
    try {
      state.loggingStatus = await stopLoggingRun();
      renderLoggingStatus();
      await refreshHistory();
    } catch (_err) {}
  }

  function ensureRunDetail(runId) {
    if (!state.runDetailsById[runId]) {
      state.runDetailsById[runId] = {
        preview: null,
        previewLoading: false,
        previewError: "",
        insights: null,
        insightsLoading: false,
        insightsError: "",
        pdfLoading: false,
        pdfError: "",
      };
    }
    return state.runDetailsById[runId];
  }

  function collapseExpandedRun() {
    const previous = state.expandedRunId;
    state.expandedRunId = null;
    if (previous) {
      delete state.runDetailsById[previous];
    }
  }

  function normalizeLogLocationKey(location) {
    const raw = String(location || "")
      .toLowerCase()
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!raw) return "";
    if (raw.includes("front left") && raw.includes("wheel")) return "front-left wheel";
    if (raw.includes("front right") && raw.includes("wheel")) return "front-right wheel";
    if (raw.includes("rear left") && raw.includes("wheel")) return "rear-left wheel";
    if (raw.includes("rear right") && raw.includes("wheel")) return "rear-right wheel";
    if (raw.includes("engine")) return "engine bay";
    if (raw.includes("drive") && raw.includes("tunnel")) return "driveshaft tunnel";
    if (raw.includes("driver") && raw.includes("seat")) return "driver seat";
    if (raw.includes("trunk")) return "trunk";
    return raw;
  }

  function normalizeUnit(value, min, max) {
    if (!(typeof value === "number") || !Number.isFinite(value)) return 0;
    if (!(typeof min === "number") || !(typeof max === "number") || max <= min) return 1;
    return Math.max(0, Math.min(1, (value - min) / (max - min)));
  }

  function heatColor(norm) {
    const hue = Math.round(212 - (norm * 190));
    return `hsl(${hue} 76% 48%)`;
  }

  function metricFromLocationStat(row) {
    if (!row || typeof row !== "object") return null;
    return (
      Number(row.p95_intensity_g ?? row.p95 ?? row.mean_intensity_g ?? row.max_intensity_g) || null
    );
  }

  // ── Live car map ──────────────────────────────────────────────

  function pushCarMapSample(byLocation: Record<string, number>) {
    const now = Date.now();
    state.carMapSamples.push({ ts: now, byLocation });
    const cutoff = now - CAR_MAP_WINDOW_MS;
    state.carMapSamples = state.carMapSamples.filter((s) => s.ts >= cutoff);
  }

  function carMapIntensityByLocation(): Record<string, number> {
    if (!state.carMapSamples.length) return {};
    const accum: Record<string, number[]> = {};
    for (const sample of state.carMapSamples) {
      for (const [loc, val] of Object.entries(sample.byLocation) as Array<[string, number]>) {
        if (!accum[loc]) accum[loc] = [];
        accum[loc].push(val);
      }
    }
    const result: Record<string, number> = {};
    for (const [loc, values] of Object.entries(accum)) {
      // Use the same metric as the PDF report: p95 of accumulated intensities
      const sorted = [...values].sort((a, b) => a - b);
      const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
      result[loc] = sorted[idx];
    }
    return result;
  }

  function triggerCarMapPulse(locationCodes: string[]) {
    for (const code of locationCodes) {
      state.carMapPulseLocations.add(code);
    }
    renderCarMap();
    // Clear pulse after animation completes
    setTimeout(() => {
      for (const code of locationCodes) {
        state.carMapPulseLocations.delete(code);
      }
      renderCarMap();
    }, 750);
  }

  function renderCarMap() {
    if (!els.liveCarMapDots) return;
    const intensity = carMapIntensityByLocation();
    const values = Object.values(intensity);
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 0;

    const dots: string[] = [];
    for (const [code, pos] of Object.entries(CAR_MAP_POSITIONS)) {
      const val = intensity[code];
      const hasVal = typeof val === "number" && Number.isFinite(val) && val > 0;
      const norm = hasVal ? normalizeUnit(val, min, max) : 0;
      const fill = hasVal ? heatColor(norm) : "var(--border)";
      const visible = hasVal ? " car-map-dot--visible" : "";
      const pulse = state.carMapPulseLocations.has(code) ? " car-map-dot--pulse" : "";
      dots.push(
        `<div class="car-map-dot${visible}${pulse}" style="top:${pos.top}%;left:${pos.left}%;background:${fill}" data-location="${code}"></div>`
      );
    }
    els.liveCarMapDots.innerHTML = dots.join("");
  }

  function extractLiveLocationIntensity(): Record<string, number> {
    const byLocation: Record<string, number> = {};
    if (!state.spectra?.clients || !state.clients?.length) return byLocation;
    for (const client of state.clients) {
      if (!client?.connected) continue;
      const code = locationCodeForClient(client);
      if (!code) continue;
      const spec = state.spectra.clients[client.id];
      if (!spec?.strength_metrics) continue;
      // Use the same metric as the PDF: strength_peak_band_rms_amp_g
      const amp = Number(spec.strength_metrics.strength_peak_band_rms_amp_g);
      if (Number.isFinite(amp) && amp > 0) {
        byLocation[code] = Math.max(byLocation[code] || 0, amp);
      }
    }
    return byLocation;
  }

  function summarizeFindings(summary) {
    const findings = Array.isArray(summary?.findings) ? summary.findings : [];
    return findings.slice(0, 3);
  }

  function renderPreviewHeatmap(summary) {
    const positions = [
      { key: "front-left wheel", top: 23, left: 20 },
      { key: "front-right wheel", top: 23, left: 80 },
      { key: "rear-left wheel", top: 76, left: 20 },
      { key: "rear-right wheel", top: 76, left: 80 },
      { key: "engine bay", top: 30, left: 50 },
      { key: "driveshaft tunnel", top: 51, left: 50 },
      { key: "driver seat", top: 43, left: 40 },
      { key: "trunk", top: 86, left: 50 },
    ];
    const statsRows = Array.isArray(summary?.sensor_intensity_by_location)
      ? summary.sensor_intensity_by_location
      : [];
    const metricByLocation = {};
    for (const row of statsRows) {
      const key = normalizeLogLocationKey(row?.location);
      const metric = metricFromLocationStat(row);
      if (key && typeof metric === "number" && Number.isFinite(metric)) {
        metricByLocation[key] = metric;
      }
    }
    const values = Object.values(metricByLocation).filter((value) => typeof value === "number");
    const min = values.length ? Math.min(...values) : null;
    const max = values.length ? Math.max(...values) : null;
    const knownPositionKeys = new Set(positions.map((point) => point.key));
    const unmappedLocationKeys = Object.keys(metricByLocation).filter((key) => !knownPositionKeys.has(key));
    const dots = positions
      .map((point) => {
        const value = metricByLocation[point.key];
        const hasValue = typeof value === "number" && Number.isFinite(value);
        if (!hasValue) return "";
        const norm = normalizeUnit(value, min, max);
        const fill = heatColor(norm);
        const valueLabel = `${fmt(value, 4)} g`;
        return `<div class="mini-car-dot" style="top:${point.top}%;left:${point.left}%;background:${fill}" title="${escapeHtml(point.key)}: ${escapeHtml(valueLabel)}"></div>`;
      })
      .join("");
    const unmappedSummary = unmappedLocationKeys.length
      ? `<div class="subtle">${escapeHtml(unmappedLocationKeys.join(", "))}</div>`
      : "";
    return `
      <div class="mini-car-wrap">
        <div class="mini-car-title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        <div class="mini-car">${dots}</div>
        ${unmappedSummary}
      </div>
    `;
  }

  function renderPreviewStats(summary) {
    const rows = Array.isArray(summary?.sensor_intensity_by_location)
      ? summary.sensor_intensity_by_location
      : [];
    if (!rows.length) {
      return `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
    }
    const body = rows
      .map((row) => {
        const dropped = row?.dropped_frames_delta ?? row?.frames_dropped_delta;
        const overflow = row?.queue_overflow_drops_delta;
        return `
          <tr>
            <td>${escapeHtml(row.location || "--")}</td>
            <td class="numeric">${fmt(row.p50_intensity_g ?? row.p50, 4)}</td>
            <td class="numeric">${fmt(row.p95_intensity_g ?? row.p95, 4)}</td>
            <td class="numeric">${fmt(row.max_intensity_g, 4)}</td>
            <td class="numeric">${typeof dropped === "number" ? formatInt(dropped) : "--"}</td>
            <td class="numeric">${typeof overflow === "number" ? formatInt(overflow) : "--"}</td>
            <td class="numeric">${formatInt(row.sample_count ?? row.samples)}</td>
          </tr>`;
      })
      .join("");
    return `
      <div class="history-preview-stats">
        <div class="mini-car-title">${escapeHtml(t("history.preview_stats_title"))}</div>
        <table class="history-preview-table">
          <thead>
            <tr>
              <th>${escapeHtml(t("history.table.location"))}</th>
              <th class="numeric">p50</th>
              <th class="numeric">p95</th>
              <th class="numeric">max</th>
              <th class="numeric">${escapeHtml(t("history.table.dropped_delta"))}</th>
              <th class="numeric">${escapeHtml(t("history.table.overflow_delta"))}</th>
              <th class="numeric">${escapeHtml(t("history.table.samples"))}</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  function renderInsightsBlock(detail) {
    const findings = summarizeFindings(detail.insights);
    const ctaLabel = detail.insights ? t("history.reload_insights") : t("history.load_insights");
    const loading = detail.insightsLoading;
    const findingsMarkup = findings.length
      ? findings
          .map((finding) => {
            const source = finding?.suspected_source || t("report.missing");
            const confidence =
              typeof finding?.confidence_0_to_1 === "number" ? fmt(finding.confidence_0_to_1, 2) : "--";
            return `<li><strong>${escapeHtml(source)}</strong> (${escapeHtml(t("report.confidence", { value: confidence }))}) - ${escapeHtml(finding?.evidence_summary || "")}</li>`;
          })
          .join("")
      : `<li>${escapeHtml(t("report.no_findings_for_run"))}</li>`;
    return `
      <div class="history-insights-block">
        <div class="history-insights-actions">
          <button class="btn btn--primary" data-run-action="load-insights" ${loading ? "disabled" : ""}>${escapeHtml(loading ? t("history.loading_insights") : ctaLabel)}</button>
          ${detail.insightsError ? `<span class="history-inline-error">${escapeHtml(detail.insightsError)}</span>` : ""}
        </div>
        ${detail.insights ? `<ul class="history-findings-list">${findingsMarkup}</ul>` : ""}
      </div>
    `;
  }

  function renderRunDetailsRow(run, detail) {
    if (!detail) return "";
    const summary = detail.preview;
    const runSummary = summary
      ? [
          `${t("report.run_id")}: ${run.run_id}`,
          `${t("history.summary_created")}: ${fmtTs(summary.start_time_utc)}`,
          `${t("history.summary_updated")}: ${fmtTs(run.end_time_utc)}`,
          `${t("history.summary_size")}: ${fmt(summary.duration_s, 1)} s`,
          `${t("history.summary_sensor_count")}: ${formatInt(summary.sensor_count_used)}`,
        ].join(" · ")
      : "";
    let previewMarkup = "";
    if (detail.previewLoading) {
      previewMarkup = `<p class="subtle">${escapeHtml(t("history.loading_preview"))}</p>`;
    } else if (detail.previewError) {
      previewMarkup = `<p class="history-inline-error">${escapeHtml(detail.previewError)}</p>`;
    } else if (summary) {
      previewMarkup = `
        <div class="history-details-preview">
          ${renderPreviewHeatmap(summary)}
          ${renderPreviewStats(summary)}
        </div>
      `;
    } else {
      previewMarkup = `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
    }
    return `
      <tr class="history-details-row">
        <td colspan="4">
          <div class="history-details-card">
            ${runSummary ? `<div class="history-run-summary">${escapeHtml(runSummary)}</div>` : ""}
            ${previewMarkup}
            ${renderInsightsBlock(detail)}
          </div>
        </td>
      </tr>
    `;
  }

  function renderHistoryTable() {
    if (els.deleteAllRunsBtn) {
      els.deleteAllRunsBtn.disabled = state.deleteAllRunsInFlight || state.runs.length === 0;
    }
    if (!state.runs.length) {
      els.historySummary.textContent = t("history.none");
      els.historyTableBody.innerHTML = `<tr><td colspan="4">${escapeHtml(t("history.none_found"))}</td></tr>`;
      collapseExpandedRun();
      return;
    }
    if (state.expandedRunId && !state.runs.some((row) => row.run_id === state.expandedRunId)) {
      collapseExpandedRun();
    }
    els.historySummary.textContent = t("history.available_count", { count: state.runs.length });
    const rows = [];
    for (const run of state.runs) {
      const detail = ensureRunDetail(run.run_id);
      const pdfLabel = detail.pdfLoading ? t("history.generating_pdf") : t("history.generate_pdf");
      const rowError = detail.pdfError
        ? `<div class="history-inline-error">${escapeHtml(detail.pdfError)}</div>`
        : "";
      rows.push(`
        <tr class="history-row${state.expandedRunId === run.run_id ? " history-row--expanded" : ""}" data-run-row="1" data-run="${escapeHtml(run.run_id)}">
          <td>${escapeHtml(run.run_id)}</td>
          <td>${fmtTs(run.start_time_utc)}</td>
          <td class="numeric">${formatInt(run.sample_count)}</td>
          <td>
            <div class="table-actions">
              <button class="btn btn--success" data-run-action="download-pdf" data-run="${escapeHtml(run.run_id)}" ${detail.pdfLoading ? "disabled" : ""}>${escapeHtml(pdfLabel)}</button>
              <a class="btn btn--muted" href="${historyExportUrl(run.run_id)}" download="${escapeHtml(run.run_id)}" data-run-action="download-raw" data-run="${escapeHtml(run.run_id)}">${escapeHtml(t("history.export"))}</a>
              <button class="btn btn--danger" data-run-action="delete-run" data-run="${escapeHtml(run.run_id)}">${escapeHtml(t("history.delete"))}</button>
            </div>
            ${rowError}
          </td>
        </tr>`);
      if (state.expandedRunId === run.run_id) {
        rows.push(renderRunDetailsRow(run, detail));
      }
    }
    els.historyTableBody.innerHTML = rows.join("");
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
    maybeRenderSensorsSettingsList(true);
  }

  async function refreshHistory() {
    try {
      const payload = await getHistory();
      state.runs = Array.isArray(payload.runs) ? payload.runs : [];
      renderHistoryTable();
    } catch (_err) {
      state.runs = [];
      renderHistoryTable();
    }
  }

  async function deleteRun(runId) {
    if (!runId) return;
    const ok = window.confirm(t("history.delete_confirm", { name: runId }));
    if (!ok) return;
    try {
      await deleteHistoryRunApi(runId);
    } catch (err) {
      window.alert(err?.message || t("history.delete_failed"));
      return;
    }
    if (state.expandedRunId === runId) {
      collapseExpandedRun();
    }
    await refreshHistory();
  }

  async function deleteAllRuns() {
    const names = state.runs
      .map((row) => (row && typeof row.run_id === "string" ? row.run_id : ""))
      .filter((name) => Boolean(name));
    if (!names.length) return;
    const ok = window.confirm(t("history.delete_all_confirm", { count: names.length }));
    if (!ok) return;

    state.deleteAllRunsInFlight = true;
    renderHistoryTable();
    let deleted = 0;
    let failed = 0;
    let firstError = "";
    for (const name of names) {
      try {
        await deleteHistoryRunApi(name);
        deleted += 1;
        delete state.runDetailsById[name];
        if (state.expandedRunId === name) {
          collapseExpandedRun();
        }
      } catch (err) {
        failed += 1;
        if (!firstError) {
          firstError = err?.message || t("history.delete_failed");
        }
      }
    }
    state.deleteAllRunsInFlight = false;
    await refreshHistory();
    if (failed > 0) {
      const summary = t("history.delete_all_partial", {
        deleted,
        total: names.length,
        failed,
      });
      window.alert(firstError ? `${summary}\n${firstError}` : summary);
    }
  }

  async function loadRunPreview(runId, force = false) {
    if (!runId) return;
    const detail = ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) return;
    detail.previewLoading = true;
    detail.previewError = "";
    renderHistoryTable();
    try {
      detail.preview = await getHistoryInsights(runId, state.lang, false);
    } catch (err) {
      detail.previewError = err?.message || t("report.unable_load_insights");
    } finally {
      detail.previewLoading = false;
      renderHistoryTable();
    }
  }

  async function loadRunInsights(runId, force = false) {
    if (!runId) return;
    const detail = ensureRunDetail(runId);
    if (!force && detail.insightsLoading) return;
    detail.insightsLoading = true;
    detail.insightsError = "";
    renderHistoryTable();
    try {
      detail.insights = await getHistoryInsights(runId, state.lang, false);
    } catch (err) {
      detail.insightsError = err?.message || t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
      renderHistoryTable();
    }
  }

  function filenameFromDisposition(headerValue, fallback) {
    if (!headerValue) return fallback;
    const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
      return decodeURIComponent(utf8Match[1]);
    }
    const simpleMatch = headerValue.match(/filename="?([^";]+)"?/i);
    if (simpleMatch && simpleMatch[1]) {
      return simpleMatch[1];
    }
    return fallback;
  }

  async function downloadBlobFile(url, fallbackName) {
    const response = await fetch(url);
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (payload && typeof payload.detail === "string") {
          detail = payload.detail;
        }
      } catch (_err) {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    const fileName = filenameFromDisposition(
      response.headers.get("content-disposition"),
      fallbackName || "download.bin",
    );
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }

  async function downloadReportPdfForRun(runId) {
    const detail = ensureRunDetail(runId);
    if (detail.pdfLoading) return;
    detail.pdfLoading = true;
    detail.pdfError = "";
    renderHistoryTable();
    try {
      await downloadBlobFile(historyReportPdfUrl(runId, state.lang), `${runId}_report.pdf`);
    } catch (err) {
      detail.pdfError = err?.message || t("history.pdf_failed");
    } finally {
      detail.pdfLoading = false;
      renderHistoryTable();
    }
  }

  function toggleRunDetails(runId) {
    if (!runId) return;
    if (state.expandedRunId === runId) {
      collapseExpandedRun();
      renderHistoryTable();
      return;
    }
    collapseExpandedRun();
    state.expandedRunId = runId;
    renderHistoryTable();
    void loadRunPreview(runId);
  }

  async function onHistoryTableAction(action, runId) {
    if (!action || !runId) return;
    if (action === "download-pdf") {
      await downloadReportPdfForRun(runId);
      return;
    }
    if (action === "delete-run") {
      await deleteRun(runId);
      return;
    }
    if (action === "load-insights") {
      await loadRunInsights(runId, true);
    }
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
      state.vehicleSettings.min_abs_band_hz,
      state.vehicleSettings.max_band_half_width_pct,
    );
    const driveSpread = toleranceForOrder(
      state.vehicleSettings.driveshaft_bandwidth_pct,
      driveHz,
      driveUncertaintyPct,
      state.vehicleSettings.min_abs_band_hz,
      state.vehicleSettings.max_band_half_width_pct,
    );
    const engineSpread = toleranceForOrder(
      state.vehicleSettings.engine_bandwidth_pct,
      engineHz,
      engineUncertaintyPct,
      state.vehicleSettings.min_abs_band_hz,
      state.vehicleSettings.max_band_half_width_pct,
    );
    const out = [
      mk(t("bands.wheel_1x"), wheelHz, wheelSpread, orderBandFills.wheel1),
      mk(t("bands.wheel_2x"), wheelHz * 2, wheelSpread, orderBandFills.wheel2),
    ];
    const overlapTol = Math.max(0.03, driveUncertaintyPct + engineUncertaintyPct);
    if (Math.abs(driveHz - engineHz) / Math.max(1e-6, engineHz) < overlapTol) {
      out.push(
        mk(
          t("bands.driveshaft_engine_1x"),
          driveHz,
          Math.max(driveSpread, engineSpread),
          orderBandFills.driveshaftEngine1,
        ),
      );
    } else {
      out.push(mk(t("bands.driveshaft_1x"), driveHz, driveSpread, orderBandFills.driveshaft1));
      out.push(mk(t("bands.engine_1x"), engineHz, engineSpread, orderBandFills.engine1));
    }
    out.push(mk(t("bands.engine_2x"), engineHz * 2, engineSpread, orderBandFills.engine2));
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

  function tooltipForCell(sourceKey, severityKey) {
    const source = sourceColumns.find((s) => s.key === sourceKey);
    const band = state.strengthBands.find((b: StrengthBand) => b.key === severityKey);
    const cell = state.eventMatrix[sourceKey]?.[severityKey];
    if (!cell || cell.count === 0) {
      return `${t(source?.labelKey || sourceKey)} / ${t(band?.labelKey || severityKey)}\n${t("tooltip.no_events")}`;
    }
    const parts = [
      `${t(source?.labelKey || sourceKey)} / ${t(band?.labelKey || severityKey)}`,
      t("tooltip.total_events", { count: cell.count }),
      `Seconds: ${fmt(cell.seconds || 0, 1)}` ,
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
    const bodyRows = [...state.strengthBands].sort((a: StrengthBand, b: StrengthBand) => b.min_db - a.min_db)
      .map((band: StrengthBand) => {
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

  function hasFreshSensorFrames(clients) {
    const rows = Array.isArray(clients) ? clients : [];
    let hasFresh = false;
    const nextTotals = {};
    for (const row of rows) {
      const clientId = row?.id;
      if (!clientId) continue;
      const framesTotal = Number(row?.frames_total ?? 0);
      if (!Number.isFinite(framesTotal)) continue;
      const prev = Number(state.strengthFrameTotalsByClient?.[clientId]);
      if (!Number.isFinite(prev)) {
        if (framesTotal > 0) hasFresh = true;
      } else if (framesTotal > prev) {
        hasFresh = true;
      }
      nextTotals[clientId] = framesTotal;
    }
    state.strengthFrameTotalsByClient = nextTotals;
    return hasFresh;
  }

  function applyServerDiagnostics(diagnostics, hasFreshFrames = false) {
    state.strengthBands = normalizeStrengthBands(diagnostics.strength_bands);
    if (diagnostics.matrix) {
      state.eventMatrix = diagnostics.matrix;
    }
    renderMatrix();

    // Only process events and trigger car map pulses when sensors are
    // actively producing new data.  Without this guard stale buffered data
    // would keep generating UI events after sensors disconnect.
    if (!hasFreshFrames) return;

    const events = Array.isArray(diagnostics.events) ? diagnostics.events : [];
    const eventPulseLocations: string[] = [];
    if (events.length) {
      for (const ev of events.slice(0, 6)) {
        const labels = Array.isArray(ev.sensor_labels) ? ev.sensor_labels.join(", ") : (ev.sensor_label || "--");
        pushVibrationMessage(
          `Strength ${String(ev.severity_key || "l1").toUpperCase()} (${fmt(ev.severity_db || 0, 1)} dB) @ ${fmt(ev.peak_hz || 0, 2)} Hz | ${labels} | ${ev.class_key || "other"}`,
        );
        // Find location codes for pulse animation
        const sensorLabels = Array.isArray(ev.sensor_labels) ? ev.sensor_labels : ev.sensor_label ? [ev.sensor_label] : [];
        for (const label of sensorLabels) {
          for (const client of state.clients) {
            if ((client.name || client.id) === label) {
              const code = locationCodeForClient(client);
              if (code) eventPulseLocations.push(code);
            }
          }
        }
      }
    }
    if (eventPulseLocations.length) {
      triggerCarMapPulse(eventPulseLocations);
    }

    const levels = diagnostics.levels || {};
    const bySource = levels.by_source || {};
    if (hasFreshFrames) {
      pushStrengthSample(bySource);
    }
  }

  function yRangeFromBands(): [number, number] {
    const bands = state.strengthBands as StrengthBand[];
    if (!bands.length) return [0, 50];
    const min = Math.max(0, Math.floor(Math.min(...bands.map((band) => band.min_db)) - 4));
    const max = Math.ceil(Math.max(...bands.map((band) => band.min_db)) + 10);
    return [min, max];
  }

  function ensureStrengthChart() {
    if (!els.strengthChart) return;
    if (state.strengthPlot) return;
    const shadePlugin = {
      hooks: {
        drawClear: [
          (u) => {
            const ctx = u.ctx;
            const ordered = [...(state.strengthBands as StrengthBand[])].sort((a, b) => a.min_db - b.min_db);
            for (let idx = 0; idx < ordered.length; idx++) {
              const band = ordered[idx];
              const nextMin = idx + 1 < ordered.length ? ordered[idx + 1].min_db : yRangeFromBands()[1];
              const y0 = u.valToPos(nextMin, "y", true);
              const y1 = u.valToPos(band.min_db, "y", true);
              ctx.fillStyle = `hsla(${220 - idx * 35}, 70%, 55%, 0.08)`;
              ctx.fillRect(u.bbox.left, y0, u.bbox.width, y1 - y0);
              ctx.strokeStyle = "rgba(79,93,115,0.28)";
              ctx.beginPath();
              ctx.moveTo(u.bbox.left, y1);
              ctx.lineTo(u.bbox.left + u.bbox.width, y1);
              ctx.stroke();
              ctx.fillStyle = "#4f5d73";
              ctx.font = "11px Segoe UI";
              ctx.fillText(band.key.toUpperCase(), u.bbox.left + u.bbox.width + 8, y1 + 4);
            }
          },
        ],
        setCursor: [
          (u) => {
            const idx = u.cursor?.idx;
            if (idx == null || idx < 0) {
              if (els.strengthTooltip) els.strengthTooltip.style.display = "none";
              return;
            }
            const labels = ["wheel", "driveshaft", "engine", "other"];
            const lines = labels.map((label, i) => `${label}: ${fmt((u.data[i + 1]?.[idx] as number) || 0, 1)} dB`);
            if (els.strengthTooltip) {
              els.strengthTooltip.textContent = lines.join("\n");
              els.strengthTooltip.style.display = "block";
            }
          },
        ],
      },
    };
    state.strengthPlot = new uPlot(
      {
        title: "Strength over time",
        width: Math.max(320, Math.floor(els.strengthChart.getBoundingClientRect().width || 320)),
        height: 240,
        scales: { x: { time: false }, y: { range: yRangeFromBands() } },
        axes: [{ label: "s" }, { label: "Strength (dB over floor)" }],
        series: [
          { label: "t" },
          { label: "wheel", stroke: "#2563eb", width: 2 },
          { label: "driveshaft", stroke: "#14b8a6", width: 2 },
          { label: "engine", stroke: "#f59e0b", width: 2 },
          { label: "other", stroke: "#8b5cf6", width: 2 },
        ],
        plugins: [shadePlugin],
      },
      [[], [], [], [], []],
      els.strengthChart,
    );

    const resize = () => {
      if (!state.strengthPlot || !els.strengthChart) return;
      state.strengthPlot.setSize({ width: Math.max(320, Math.floor(els.strengthChart.getBoundingClientRect().width || 320)), height: 240 });
    };
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) resize();
    });
  }

  function pushStrengthSample(bySource) {
    ensureStrengthChart();
    if (!state.strengthPlot) return;
    const now = Date.now() / 1000;
    state.strengthHistory.t.push(now);
    for (const key of ["wheel", "driveshaft", "engine", "other"]) {
      const level = bySource?.[key];
      state.strengthHistory[key].push(level?.strength_db || 0);
    }
    const windowSeconds = 60;
    while (state.strengthHistory.t.length && now - state.strengthHistory.t[0] > windowSeconds) {
      state.strengthHistory.t.shift();
      state.strengthHistory.wheel.shift();
      state.strengthHistory.driveshaft.shift();
      state.strengthHistory.engine.shift();
      state.strengthHistory.other.shift();
    }
    const t0 = state.strengthHistory.t[0] || now;
    const relT = state.strengthHistory.t.map((v) => v - t0);
    state.strengthPlot.setScale("y", { min: yRangeFromBands()[0], max: yRangeFromBands()[1] });
    state.strengthPlot.setData([
      relT,
      state.strengthHistory.wheel,
      state.strengthHistory.driveshaft,
      state.strengthHistory.engine,
      state.strengthHistory.other,
    ]);
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
      if (!s || !Array.isArray(s.combined_spectrum_db_above_floor)) continue;
      const clientFreq = Array.isArray(s.freq) && s.freq.length ? s.freq : fallbackFreq;
      const n = Math.min(clientFreq.length, s.combined_spectrum_db_above_floor.length);
      if (!n) continue;
      let blended = s.combined_spectrum_db_above_floor.slice(0, n);
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
    state.hasSpectrumData = true;
    const minLen = Math.min(targetFreq.length, ...entries.map((e) => e.values.length));
    state.spectrumPlot.setData([targetFreq.slice(0, minLen), ...entries.map((e) => e.values.slice(0, minLen))]);
    updateSpectrumOverlay();
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
    let adapted;
    try {
      adapted = adaptServerPayload(payload);
    } catch (err) {
      state.payloadError = err instanceof Error ? err.message : "Invalid server payload.";
      state.hasSpectrumData = false;
      renderWsState();
      updateSpectrumOverlay();
      return;
    }
    state.payloadError = null;
    renderWsState();
    const prevSelected = state.selectedClientId;
    state.clients = adapted.clients;
    if (adapted.spectra) {
      state.spectra = {
        clients: Object.fromEntries(
          Object.entries(adapted.spectra.clients).map(([clientId, spectrum]: [string, any]) => [
            clientId,
            {
              freq: spectrum.freq,
              combined_spectrum_amp_g: spectrum.combined,
              combined_spectrum_db_above_floor: spectrum.combinedDbAboveFloor,
              strength_metrics: spectrum.strength_metrics,
            },
          ]),
        ),
      };
    }
    updateClientSelection();
    maybeRenderSensorsSettingsList();
    renderLoggingStatus();
    if (prevSelected !== state.selectedClientId) {
      sendSelection();
    }

    state.speedMps = adapted.speed_mps;
    if (adapted.spectra) {
      state.hasSpectrumData = (Object.values(adapted.spectra.clients) as Array<any>).some(
        (clientSpec) => clientSpec.freq.length > 0 && clientSpec.combined.length > 0,
      );
    }
    const hasFreshFrames = hasFreshSensorFrames(state.clients);
    applyServerDiagnostics(adapted.diagnostics, hasFreshFrames);
    renderSpeedReadout();
    // Update live car map with rolling intensity data
    const liveIntensity = extractLiveLocationIntensity();
    if (Object.keys(liveIntensity).length) {
      pushCarMapSample(liveIntensity);
    }
    renderCarMap();
    if (adapted.spectra) {
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
      maybeRenderSensorsSettingsList();
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
    maybeRenderSensorsSettingsList();
    renderLoggingStatus();
    if (prevSelected !== state.selectedClientId) {
      sendSelection();
    }
  }

  // -- Analysis tab save (bandwidths + uncertainty — NOT car-dependent) ---------

  function saveAnalysisFromInputs() {
    const wheelBandwidth = Number(els.wheelBandwidthInput?.value);
    const driveshaftBandwidth = Number(els.driveshaftBandwidthInput?.value);
    const engineBandwidth = Number(els.engineBandwidthInput?.value);
    const speedUncertainty = Number(els.speedUncertaintyInput?.value);
    const tireDiameterUncertainty = Number(els.tireDiameterUncertaintyInput?.value);
    const finalDriveUncertainty = Number(els.finalDriveUncertaintyInput?.value);
    const gearUncertainty = Number(els.gearUncertaintyInput?.value);
    const minAbsBandHz = Number(els.minAbsBandHzInput?.value);
    const maxBandHalfWidth = Number(els.maxBandHalfWidthInput?.value);
    const validBandwidths =
      wheelBandwidth > 0 && wheelBandwidth <= 40 &&
      driveshaftBandwidth > 0 && driveshaftBandwidth <= 40 &&
      engineBandwidth > 0 && engineBandwidth <= 40;
    const validUncertainty =
      speedUncertainty >= 0 && speedUncertainty <= 20 &&
      tireDiameterUncertainty >= 0 && tireDiameterUncertainty <= 20 &&
      finalDriveUncertainty >= 0 && finalDriveUncertainty <= 10 &&
      gearUncertainty >= 0 && gearUncertainty <= 20;
    const validBandLimits =
      minAbsBandHz >= 0 && minAbsBandHz <= 10 && maxBandHalfWidth > 0 && maxBandHalfWidth <= 25;
    if (!validBandwidths || !validUncertainty || !validBandLimits) return;

    state.vehicleSettings.wheel_bandwidth_pct = wheelBandwidth;
    state.vehicleSettings.driveshaft_bandwidth_pct = driveshaftBandwidth;
    state.vehicleSettings.engine_bandwidth_pct = engineBandwidth;
    state.vehicleSettings.speed_uncertainty_pct = speedUncertainty;
    state.vehicleSettings.tire_diameter_uncertainty_pct = tireDiameterUncertainty;
    state.vehicleSettings.final_drive_uncertainty_pct = finalDriveUncertainty;
    state.vehicleSettings.gear_uncertainty_pct = gearUncertainty;
    state.vehicleSettings.min_abs_band_hz = minAbsBandHz;
    state.vehicleSettings.max_band_half_width_pct = maxBandHalfWidth;
    saveVehicleSettings();
    void syncAnalysisSettingsToServer();
    renderSpectrum();
  }

  function saveSpeedSourceFromInputs() {
    const radios = document.querySelectorAll<HTMLInputElement>('input[name="speedSourceRadio"]');
    let src = "gps";
    radios.forEach((r) => { if (r.checked) src = r.value; });
    const manual = Number(els.manualSpeedInput?.value);
    state.speedSource = src;
    state.manualSpeedKph = (src === "manual" && manual > 0) ? manual : null;
    void syncSpeedSourceToServer();
    renderSpeedReadout();
  }

  // -- Settings sub-tab switching -----------------------------------------------

  function setActiveSettingsTab(tabId: string) {
    els.settingsTabs.forEach((tab) => {
      const isActive = tab.getAttribute("data-settings-tab") === tabId;
      tab.classList.toggle("active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
      tab.tabIndex = isActive ? 0 : -1;
    });
    els.settingsTabPanels.forEach((panel) => {
      const isActive = panel.id === tabId;
      panel.classList.toggle("active", isActive);
      panel.hidden = !isActive;
    });
  }

  els.settingsTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const tabId = tab.getAttribute("data-settings-tab");
      if (tabId) setActiveSettingsTab(tabId);
    });
  });

  // -- Add Car Wizard ---------------------------------------------------------

  const wizState = {
    step: 0,
    brand: "",
    carType: "",
    model: "",
    selectedModel: null as CarLibraryModel | null,
    selectedGearbox: null as CarLibraryGearbox | null,
    selectedTire: null as CarLibraryTireOption | null,
  };

  function openWizard() {
    wizState.step = 0;
    wizState.brand = "";
    wizState.carType = "";
    wizState.model = "";
    wizState.selectedModel = null;
    wizState.selectedGearbox = null;
    wizState.selectedTire = null;
    if (els.addCarWizard) els.addCarWizard.hidden = false;
    loadWizardStep();
  }

  function closeWizard() {
    if (els.addCarWizard) els.addCarWizard.hidden = true;
  }

  function buildWizardCarName(brand: string, model: string): string {
    if (brand) return `${brand} ${model || "Custom"}`;
    return model || "Custom Car";
  }

  const WIZARD_STEP_COUNT = 4;

  function loadWizardStep() {
    for (let i = 0; i < WIZARD_STEP_COUNT; i++) {
      const stepEl = document.getElementById(`wizardStep${i}`);
      if (stepEl) stepEl.classList.toggle("active", i === wizState.step);
    }
    document.querySelectorAll(".wizard-step-dot").forEach((dot) => {
      const s = Number(dot.getAttribute("data-step"));
      dot.classList.toggle("active", s === wizState.step);
      dot.classList.toggle("done", s < wizState.step);
    });
    if (els.wizardBackBtn) els.wizardBackBtn.style.display = wizState.step > 0 ? "" : "none";

    if (wizState.step === 0) loadBrandStep();
    else if (wizState.step === 1) loadTypeStep();
    else if (wizState.step === 2) loadModelStep();
    else if (wizState.step === 3) loadGearboxStep();
  }

  async function loadBrandStep() {
    const container = document.getElementById("wizardBrandList");
    if (!container) return;
    container.innerHTML = "<em>Loading...</em>";
    try {
      const data = await getCarLibraryBrands();
      container.innerHTML = (data.brands || [])
        .map((b) => `<button type="button" class="wiz-opt" data-value="${escapeHtml(b)}">${escapeHtml(b)}</button>`)
        .join("");
      container.querySelectorAll(".wiz-opt").forEach((btn) => {
        btn.addEventListener("click", () => {
          wizState.brand = btn.getAttribute("data-value") || "";
          wizState.step = 1;
          loadWizardStep();
        });
      });
    } catch (_err) {
      container.innerHTML = "<em>Could not load brands</em>";
    }
  }

  async function loadTypeStep() {
    const container = document.getElementById("wizardTypeList");
    if (!container) return;
    container.innerHTML = "<em>Loading...</em>";
    try {
      const data = await getCarLibraryTypes(wizState.brand);
      container.innerHTML = (data.types || [])
        .map((t2) => `<button type="button" class="wiz-opt" data-value="${escapeHtml(t2)}">${escapeHtml(t2)}</button>`)
        .join("");
      container.querySelectorAll(".wiz-opt").forEach((btn) => {
        btn.addEventListener("click", () => {
          wizState.carType = btn.getAttribute("data-value") || "";
          wizState.step = 2;
          loadWizardStep();
        });
      });
    } catch (_err) {
      container.innerHTML = "<em>Could not load types</em>";
    }
  }

  async function loadModelStep() {
    const container = document.getElementById("wizardModelList");
    if (!container) return;
    container.innerHTML = "<em>Loading...</em>";
    try {
      const data = await getCarLibraryModels(wizState.brand, wizState.carType);
      const models = data.models || [];
      container.innerHTML = models
        .map((m, idx) => {
          const tireStr = `${m.tire_width_mm}/${m.tire_aspect_pct}R${m.rim_in}`;
          return `<button type="button" class="wiz-opt" data-idx="${idx}">
            <span>${escapeHtml(m.model)}</span>
            <span class="wiz-opt-detail">${escapeHtml(tireStr)}</span>
          </button>`;
        })
        .join("");
      container.querySelectorAll(".wiz-opt").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.getAttribute("data-idx"));
          wizState.selectedModel = models[idx] || null;
          wizState.model = wizState.selectedModel?.model || "";
          wizState.selectedTire = null;
          wizState.step = 3;
          loadWizardStep();
        });
      });
    } catch (_err) {
      container.innerHTML = "<em>Could not load models</em>";
    }
  }

  function loadGearboxStep() {
    // -- Tire options section --
    const tireContainer = document.getElementById("wizardTireList");
    if (tireContainer) {
      const tireOptions = wizState.selectedModel?.tire_options || [];
      if (tireOptions.length > 0) {
        tireContainer.innerHTML = tireOptions
          .map((to, idx) => `<button type="button" class="wiz-opt${idx === 0 ? " selected" : ""}" data-tire-idx="${idx}">
            <span>${escapeHtml(to.name)}</span>
            <span class="wiz-opt-detail">${to.tire_width_mm}/${to.tire_aspect_pct}R${to.rim_in}</span>
          </button>`)
          .join("");
        // Auto-select first tire option
        const defaultTire = tireOptions[0];
        wizState.selectedTire = defaultTire;
        updateWizTireInputs(defaultTire);
        tireContainer.querySelectorAll(".wiz-opt").forEach((btn) => {
          btn.addEventListener("click", () => {
            const idx = Number(btn.getAttribute("data-tire-idx"));
            wizState.selectedTire = tireOptions[idx] || defaultTire;
            updateWizTireInputs(wizState.selectedTire);
            tireContainer.querySelectorAll(".wiz-opt").forEach((b) => b.classList.remove("selected"));
            btn.classList.add("selected");
          });
        });
      } else {
        tireContainer.innerHTML = "";
      }
    }

    // -- Gearbox options section --
    const container = document.getElementById("wizardGearboxList");
    if (!container) return;
    const gearboxes = wizState.selectedModel?.gearboxes || [];
    if (!gearboxes.length) {
      container.innerHTML = "<em>No pre-defined gearboxes. Enter specs manually below.</em>";
      return;
    }
    container.innerHTML = gearboxes
      .map((gb, idx) => `<button type="button" class="wiz-opt" data-idx="${idx}">
        <span>${escapeHtml(gb.name)}</span>
        <span class="wiz-opt-detail">FD: ${fmt(gb.final_drive_ratio, 2)} · Top Gear: ${fmt(gb.top_gear_ratio, 2)}</span>
      </button>`)
      .join("");
    container.querySelectorAll(".wiz-opt").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idx = Number(btn.getAttribute("data-idx"));
        const gb = gearboxes[idx];
        if (!gb) return;
        const tire = wizState.selectedTire || wizState.selectedModel;
        const carName = `${wizState.brand} ${wizState.model}`;
        await addCarFromWizard(carName, wizState.carType, {
          tire_width_mm: tire.tire_width_mm,
          tire_aspect_pct: tire.tire_aspect_pct,
          rim_in: tire.rim_in,
          final_drive_ratio: gb.final_drive_ratio,
          current_gear_ratio: gb.top_gear_ratio,
        });
      });
    });
  }

  function updateWizTireInputs(tire: CarLibraryTireOption | null) {
    const tw = document.getElementById("wizTireWidth") as HTMLInputElement;
    const ta = document.getElementById("wizTireAspect") as HTMLInputElement;
    const ri = document.getElementById("wizRim") as HTMLInputElement;
    if (tw && tire) tw.value = String(tire.tire_width_mm);
    if (ta && tire) ta.value = String(tire.tire_aspect_pct);
    if (ri && tire) ri.value = String(tire.rim_in);
  }

  async function addCarFromWizard(name: string, carType: string, aspects: Record<string, number>) {
    try {
      const fullAspects = { ...state.vehicleSettings, ...aspects };
      const result = await addSettingsCar({ name, type: carType, aspects: fullAspects });
      if (result?.cars) {
        state.cars = result.cars;
        const newCar = result.cars[result.cars.length - 1];
        if (newCar) {
          const setResult = await setActiveSettingsCar(newCar.id);
          if (setResult?.cars) {
            state.cars = setResult.cars;
            state.activeCarId = setResult.activeCarId;
          }
        }
        syncActiveCarToInputs();
        renderCarList();
        renderSpectrum();
      }
    } catch (_err) {}
    closeWizard();
  }

  // Wizard button handlers
  if (els.addCarBtn) {
    els.addCarBtn.addEventListener("click", openWizard);
  }
  if (els.wizardCloseBtn) {
    els.wizardCloseBtn.addEventListener("click", closeWizard);
  }
  if (els.wizardBackBtn) {
    els.wizardBackBtn.addEventListener("click", () => {
      if (wizState.step > 0) {
        wizState.step--;
        loadWizardStep();
      }
    });
  }

  // Custom brand/type/model buttons
  document.getElementById("wizardCustomBrandBtn")?.addEventListener("click", () => {
    const input = document.getElementById("wizardCustomBrand") as HTMLInputElement;
    const val = input?.value?.trim();
    if (!val) return;
    wizState.brand = val;
    wizState.step = 1;
    loadWizardStep();
  });

  document.getElementById("wizardCustomTypeBtn")?.addEventListener("click", () => {
    const input = document.getElementById("wizardCustomType") as HTMLInputElement;
    const val = input?.value?.trim();
    if (!val) return;
    wizState.carType = val;
    wizState.step = 2;
    loadWizardStep();
  });

  document.getElementById("wizardCustomModelBtn")?.addEventListener("click", () => {
    const input = document.getElementById("wizardCustomModel") as HTMLInputElement;
    const val = input?.value?.trim();
    if (!val) return;
    wizState.model = val;
    wizState.selectedModel = null;
    wizState.step = 3;
    loadWizardStep();
  });

  // Manual specs add button
  document.getElementById("wizardManualAddBtn")?.addEventListener("click", async () => {
    const tw = Number((document.getElementById("wizTireWidth") as HTMLInputElement)?.value);
    const ta = Number((document.getElementById("wizTireAspect") as HTMLInputElement)?.value);
    const ri = Number((document.getElementById("wizRim") as HTMLInputElement)?.value);
    const fd = Number((document.getElementById("wizFinalDrive") as HTMLInputElement)?.value);
    const gr = Number((document.getElementById("wizGearRatio") as HTMLInputElement)?.value);
    if (!(tw > 0 && ta > 0 && ri > 0 && fd > 0 && gr > 0)) return;
    const name = buildWizardCarName(wizState.brand, wizState.model);
    await addCarFromWizard(name, wizState.carType || "Custom", {
      tire_width_mm: tw,
      tire_aspect_pct: ta,
      rim_in: ri,
      final_drive_ratio: fd,
      current_gear_ratio: gr,
    });
  });

  // -- Analysis tab save button ------------------------------------------------

  if (els.saveAnalysisBtn) {
    els.saveAnalysisBtn.addEventListener("click", saveAnalysisFromInputs);
  }

  // -- Speed source save button ------------------------------------------------

  if (els.saveSpeedSourceBtn) {
    els.saveSpeedSourceBtn.addEventListener("click", saveSpeedSourceFromInputs);
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
  els.refreshHistoryBtn.addEventListener("click", refreshHistory);
  if (els.deleteAllRunsBtn) {
    els.deleteAllRunsBtn.addEventListener("click", () => {
      void deleteAllRuns();
    });
  }
  els.historyTableBody.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement | null;
    const actionEl = target?.closest?.("[data-run-action]");
    if (actionEl) {
      const action = actionEl.getAttribute("data-run-action");
      const runId = actionEl.getAttribute("data-run") || state.expandedRunId || "";
      if (action !== "download-raw") {
        ev.preventDefault();
      }
      ev.stopPropagation();
      void onHistoryTableAction(action, runId);
      return;
    }
    const rowEl = target?.closest?.('tr[data-run-row="1"]');
    if (rowEl) {
      const runId = rowEl.getAttribute("data-run") || "";
      toggleRunDetails(runId);
    }
  });
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

  loadVehicleSettings();
  syncSettingsInputs();
  applyLanguage(false);
  setActiveView("dashboardView");
  refreshLocationOptions();
  void loadSpeedSourceFromServer();
  void loadAnalysisSettingsFromServer();
  void loadCarsFromServer();
  refreshLoggingStatus();
  refreshHistory();

  // Demo mode: inject deterministic data for visual testing (activated via ?demo=1).
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  if (isDemoMode) {
    (function runDemoMode() {
      // Freeze WS state to "connected"
      state.wsState = "connected";
      renderWsState();

      const demoClients = [
        { id: "aabbcc001122", name: "Front Left Wheel", mac_address: "AA:BB:CC:00:11:22", connected: true, last_seen_age_ms: 42, dropped_frames: 0, frames_total: 8400 },
        { id: "aabbcc001133", name: "Front Right Wheel", mac_address: "AA:BB:CC:00:11:33", connected: true, last_seen_age_ms: 38, dropped_frames: 1, frames_total: 8395 },
        { id: "aabbcc001144", name: "Rear Left Wheel", mac_address: "AA:BB:CC:00:11:44", connected: true, last_seen_age_ms: 45, dropped_frames: 0, frames_total: 8388 },
        { id: "aabbcc001155", name: "Rear Right Wheel", mac_address: "AA:BB:CC:00:11:55", connected: true, last_seen_age_ms: 51, dropped_frames: 0, frames_total: 8401 },
        { id: "aabbcc001166", name: "Engine Bay", mac_address: "AA:BB:CC:00:11:66", connected: true, last_seen_age_ms: 39, dropped_frames: 2, frames_total: 8390 },
      ];

      // Generate deterministic spectrum frequencies (0-250 Hz)
      const freqCount = 256;
      const freqArr: number[] = [];
      for (let i = 0; i < freqCount; i++) freqArr.push((i / freqCount) * 250);

      function sineSpectrum(baseAmps: number[], peakHz: number, peakAmp: number): number[] {
        return freqArr.map((hz, i) => {
          const base = baseAmps[i % baseAmps.length] || 0.001;
          const dist = Math.abs(hz - peakHz);
          const peak = dist < 8 ? peakAmp * Math.exp(-dist * dist / 18) : 0;
          return base + peak;
        });
      }

      // Seeded base noise
      const baseNoise: number[] = [];
      let seed = 42;
      for (let i = 0; i < freqCount; i++) {
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        baseNoise.push(0.0008 + (seed % 100) * 0.00004);
      }

      const demoSpectra: Record<string, any> = {};
      // Pre-computed demo data per sensor (no runtime metric computation in UI).
      const peakConfigs = [
        { hz: 12.3, amp: 0.032, db: 15.1, bucket: "l2" }, // FL wheel
        { hz: 12.1, amp: 0.025, db: 14.0, bucket: "l2" }, // FR wheel
        { hz: 12.5, amp: 0.018, db: 12.6, bucket: "l2" }, // RL wheel
        { hz: 12.2, amp: 0.045, db: 16.5, bucket: "l2" }, // RR wheel — strongest
        { hz: 36.8, amp: 0.012, db: 10.8, bucket: "l2" }, // Engine
      ];
      demoClients.forEach((client, idx) => {
        const pk = peakConfigs[idx];
        const combined = sineSpectrum(baseNoise, pk.hz, pk.amp);
        const combinedDb = sineSpectrum(Array.from({ length: freqArr.length }, () => -22), pk.hz, pk.db);
        demoSpectra[client.id] = {
          freq: freqArr,
          combined_spectrum_amp_g: combined,
          combined_spectrum_db_above_floor: combinedDb,
          strength_metrics: {
            strength_peak_band_rms_amp_g: pk.amp * 0.8,
            strength_floor_amp_g: 0.001,
            strength_db: pk.db,
            strength_bucket: pk.bucket,
          },
        };
      });

      const demoStrengthBands = [
        { key: "l1", min_db: 0 },
        { key: "l2", min_db: 10 },
        { key: "l3", min_db: 18 },
        { key: "l4", min_db: 28 },
        { key: "l5", min_db: 40 },
      ];

      const demoPayload = {
        server_time: new Date().toISOString(),
        clients: demoClients,
        speed_mps: 22.2, // ~80 km/h
        spectra: { clients: demoSpectra },
        diagnostics: {
          strength_bands: demoStrengthBands,
          matrix: null,
          events: [],
          levels: { by_source: { wheel: 14.2, driveshaft: 8.1, engine: 6.5, other: 3.2 } },
        },
      };

      // Apply initial payload
      state.hasReceivedPayload = true;
      applyPayload(demoPayload);

      // After a short delay, inject an event to show the pulse animation
      const demoEventTimeout = setTimeout(() => {
        const eventPayload = {
          ...demoPayload,
          diagnostics: {
            ...demoPayload.diagnostics,
            events: [
              {
                severity_key: "l3",
                severity_db: 22.5,
                peak_hz: 12.2,
                class_key: "wheel",
                sensor_labels: ["Rear Right Wheel"],
              },
            ],
          },
        };
        applyPayload(eventPayload);
      }, 800);

      // Expose cleanup for tests
      (window as any).__vibesensorDemoCleanup = () => clearTimeout(demoEventTimeout);
    })();
  } else {
    connectWS();
  }
