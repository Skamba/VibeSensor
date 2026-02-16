(() => {
  const els = {
    menuButtons: Array.from(document.querySelectorAll(".menu-btn")),
    views: Array.from(document.querySelectorAll(".view")),
    languageSelect: document.getElementById("languageSelect"),
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
    specChart: document.getElementById("specChart"),
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

  const I18N = window.VibeI18n || {
    normalizeLang: () => "en",
    get: (_lang, key) => key,
    getForAllLangs: (key) => [key],
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

  const state = {
    ws: null,
    lang: I18N.normalizeLang(window.localStorage.getItem(uiLanguageStorageKey) || "en"),
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
  };

  function t(key, vars) {
    return I18N.get(state.lang, key, vars);
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
    state.locationOptions = buildLocationOptions(state.locationCodes);
    state.clientsSettingsSignature = "";
    maybeRenderClientsSettingsList(true);
    renderSpeedReadout();
    renderLoggingStatus();
    renderLogsTable();
    renderReportSelect();
    renderVibrationLog();
    renderMatrix();
    els.linkState.textContent = t("ws.connecting");
    if (state.spectrumPlot) {
      state.spectrumPlot.destroy();
      state.spectrumPlot = null;
      renderSpectrum();
    }
    if (forceReloadInsights && state.selectedLogName) {
      void loadReportInsights();
    }
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
    }
  }

  function chartWidth(el) {
    return Math.max(320, Math.floor(el.getBoundingClientRect().width - 20));
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
    if (typeof state.speedMps === "number") {
      els.speed.textContent = t("speed.gps", { value: fmt(state.speedMps, 2) });
      return;
    }
    const spd = effectiveSpeedMps();
    els.speed.textContent = spd ? t("speed.override", { value: fmt(spd, 2) }) : t("speed.none");
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
    const series = [{ label: t("chart.axis.hz") }];
    for (const item of seriesMeta) {
      series.push({ label: item.label, stroke: item.color, width: 2 });
    }
    state.spectrumPlot = new uPlot(
      {
        title: t("chart.spectrum_title"),
        width: chartWidth(els.specChart),
        height: 360,
        scales: { x: { time: false } },
        axes: [{ label: t("chart.axis.hz") }, { label: t("chart.axis.amplitude") }],
        series,
        plugins: [bandPlugin()],
      },
      [[]],
      els.specChart,
    );
  }

  function renderLegend(seriesMeta) {
    els.legend.innerHTML = "";
    for (const item of seriesMeta) {
      const row = document.createElement("div");
      row.className = "legend-item";
      row.innerHTML = `<span class="swatch" style="background:${item.color}"></span><span>${item.label}</span>`;
      els.legend.appendChild(row);
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
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
        <td><button class="row-action row-identify" data-client-id="${escapeHtml(client.id)}"${connected ? "" : " disabled"}>${escapeHtml(t("actions.identify"))}</button></td>
        <td><button class="row-action warn row-remove" data-client-id="${escapeHtml(client.id)}">${escapeHtml(t("actions.remove"))}</button></td>
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
      els.lastSeen.textContent = t("status.last_seen_none");
      els.dropped.textContent = t("status.dropped", { value: "--" });
      els.framesTotal.textContent = t("status.frames_total", { value: "--" });
      return;
    }
    const age = clientRow.last_seen_age_ms ?? null;
    els.lastSeen.textContent =
      age === null ? t("status.last_seen_none") : t("status.last_seen", { value: `${age} ms ago` });
    els.dropped.textContent = t("status.dropped", { value: clientRow.dropped_frames ?? 0 });
    els.framesTotal.textContent = t("status.frames_total", { value: clientRow.frames_total ?? 0 });
  }

  async function apiJson(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      throw new Error(`${resp.status} ${resp.statusText}`);
    }
    return resp.json();
  }

  async function syncSpeedOverrideToServer(speedKmh) {
    const normalized = typeof speedKmh === "number" && speedKmh > 0 ? speedKmh : null;
    try {
      const payload = await apiJson("/api/speed-override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed_kmh: normalized }),
      });
      if (typeof payload?.speed_kmh === "number") {
        state.vehicleSettings.speed_override_kmh = payload.speed_kmh;
      }
    } catch (_err) {
      // Ignore transient API errors; UI can still use local override for charting.
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
      await apiJson("/api/analysis-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (_err) {
      // Keep UI local settings even if backend update fails transiently.
    }
  }

  function renderLoggingStatus() {
    const status = state.loggingStatus || { enabled: false, current_file: null };
    const on = Boolean(status.enabled);
    els.loggingStatus.textContent = on ? t("status.running") : t("status.stopped");
    els.loggingStatus.className = `badge ${on ? "on" : "off"}`;
    els.currentLogFile.textContent = t("status.current_file", { value: status.current_file || "--" });
  }

  async function refreshLoggingStatus() {
    try {
      state.loggingStatus = await apiJson("/api/logging/status");
      renderLoggingStatus();
    } catch (_err) {
      els.loggingStatus.textContent = t("status.unavailable");
      els.loggingStatus.className = "badge off";
    }
  }

  async function startLogging() {
    try {
      state.loggingStatus = await apiJson("/api/logging/start", { method: "POST" });
      renderLoggingStatus();
      await refreshLogs();
    } catch (_err) {}
  }

  async function stopLogging() {
    try {
      state.loggingStatus = await apiJson("/api/logging/stop", { method: "POST" });
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
      const payload = await apiJson("/api/client-locations");
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
        <td>${fmtBytes(row.size_bytes)}</td>
        <td>
          <button class="select-log-btn" data-log="${row.name}">${escapeHtml(t("logs.use_in_report"))}</button>
          <a href="/api/logs/${encodeURIComponent(row.name)}" target="_blank" rel="noopener">${escapeHtml(t("logs.raw"))}</a>
          <button class="warn delete-log-btn" data-log="${row.name}">${escapeHtml(t("logs.delete"))}</button>
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
      const payload = await apiJson("/api/logs");
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
    const resp = await fetch(`/api/logs/${encodeURIComponent(logName)}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      let message = t("logs.delete_failed");
      try {
        const payload = await resp.json();
        if (payload?.detail) message = String(payload.detail);
      } catch (_err) {}
      window.alert(message);
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
      const summary = await apiJson(
        `/api/logs/${encodeURIComponent(logName)}/insights?lang=${encodeURIComponent(state.lang)}`,
      );
      renderInsights(summary);
    } catch (_err) {
      els.reportInsights.textContent = t("report.unable_load_insights");
    }
  }

  function downloadReportPdf() {
    const logName = els.reportLogSelect.value;
    if (!logName) return;
    selectLog(logName);
    window.open(
      `/api/logs/${encodeURIComponent(logName)}/report.pdf?lang=${encodeURIComponent(state.lang)}`,
      "_blank",
      "noopener",
    );
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

  function severityLabelKey(severityKey) {
    const band = severityBands.find((entry) => entry.key === severityKey);
    return band ? band.labelKey : "matrix.severity.l1";
  }

  function causeLabel(classKey) {
    if (classKey === "wheel1") return t("cause.wheel1");
    if (classKey === "wheel2") return t("cause.wheel2");
    if (classKey === "shaft1") return t("cause.shaft1");
    if (classKey === "eng1") return t("cause.eng1");
    if (classKey === "eng2") return t("cause.eng2");
    if (classKey === "shaft_eng1") return t("cause.shaft_eng1");
    if (classKey === "road") return t("cause.road");
    return t("cause.other");
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
    const entries = Object.entries(cell.contributors).sort((a, b) => b[1] - a[1]);
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

  function applyDiagnostics(diagnostics) {
    state.eventMatrix = createEmptyMatrix();
    const matrix = diagnostics?.matrix;
    if (matrix && typeof matrix === "object") {
      for (const src of sourceColumns) {
        const sourceRow = matrix[src.key];
        if (!sourceRow || typeof sourceRow !== "object") continue;
        for (const band of severityBands) {
          const cell = sourceRow[band.key];
          if (!cell || typeof cell !== "object") continue;
          state.eventMatrix[src.key][band.key] = {
            count: Number(cell.count) || 0,
            contributors:
              cell.contributors && typeof cell.contributors === "object"
                ? { ...cell.contributors }
                : {},
          };
        }
      }
    }
    state.vibrationMessages = [];
    const events = Array.isArray(diagnostics?.events) ? diagnostics.events : [];
    for (const ev of events) {
      if (!ev || typeof ev !== "object") continue;
      const severityKey = String(ev.severity_key || "");
      if (!severityKey) continue;
      const severityText = t(severityLabelKey(severityKey));
      const classKey = String(ev.class_key || "other");
      const cause = causeLabel(classKey);
      if (ev.kind === "multi") {
        const labels = Array.isArray(ev.sensor_labels) ? ev.sensor_labels.join(", ") : "";
        pushVibrationMessage(
          t("msg.multi_detected", {
            count: Number(ev.sensor_count) || 0,
            labels,
            hz: fmt(Number(ev.peak_hz), 2),
            amp: fmt(Number(ev.peak_amp), 1),
            severity: severityText,
            cause,
          }),
        );
      } else {
        pushVibrationMessage(
          t("msg.single_detected", {
            sensor: String(ev.sensor_label || ev.sensor_id || ""),
            hz: fmt(Number(ev.peak_hz), 2),
            amp: fmt(Number(ev.peak_amp), 1),
            severity: severityText,
            cause,
          }),
        );
      }
    }
    renderVibrationLog();
    renderMatrix();
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
      let blended = Array.isArray(s.combined_spectrum_amp_g) ? s.combined_spectrum_amp_g.slice(0, n) : [];
      if (!blended.length) continue;
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

    if (!state.spectrumPlot || state.spectrumPlot.series.length !== entries.length + 1) {
      recreateSpectrumPlot(entries);
    }
    renderLegend(entries);
    state.chartBands = calculateBands();
    renderBandLegend();

    if (!targetFreq.length || !entries.length) {
      state.spectrumPlot.setData([[], ...entries.map(() => [])]);
      return;
    }
    const minLen = Math.min(targetFreq.length, ...entries.map((e) => e.values.length));
    const data = [targetFreq.slice(0, minLen)];
    for (const e of entries) data.push(e.values.slice(0, minLen));
    state.spectrumPlot.setData(data);
  }

  function sendSelection() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ client_id: state.selectedClientId }));
    }
  }

  function connectWS() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    state.ws = new WebSocket(`${proto}//${window.location.host}/ws`);
    state.ws.onopen = () => {
      els.linkState.textContent = t("ws.connected");
      els.linkState.className = "panel status-ok";
      sendSelection();
    };
    state.ws.onmessage = (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (_err) {
        return;
      }
      state.pendingPayload = payload;
      queueRender();
    };
    state.ws.onclose = () => {
      els.linkState.textContent = t("ws.reconnecting");
      els.linkState.className = "panel status-bad";
      window.setTimeout(connectWS, 1200);
    };
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
    renderSpeedReadout();
    if (payload.spectra) {
      renderSpectrum();
    }
    applyDiagnostics(payload.diagnostics || {});
    const row = state.clients.find((c) => c.id === state.selectedClientId);
    renderStatus(row);
  }

  async function setClientLocation(clientId, locationCode) {
    if (!clientId) return;
    if (!locationCode) return;
    const existing = state.clients.find((c) => c.id === clientId);
    if (existing && locationCodeForClient(existing) === locationCode) return;
    const resp = await fetch(`/api/clients/${encodeURIComponent(clientId)}/location`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ location_code: locationCode }),
    });
    if (!resp.ok) {
      let message = t("actions.set_location_failed");
      try {
        const payload = await resp.json();
        if (payload?.detail) message = String(payload.detail);
      } catch (_err) {}
      window.alert(message);
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
    await fetch(`/api/clients/${encodeURIComponent(clientId)}/identify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration_ms: 1500 }),
    });
  }

  async function removeClient(clientId) {
    if (!clientId) return;
    const ok = window.confirm(t("actions.remove_client_confirm", { id: clientId }));
    if (!ok) return;
    const resp = await fetch(`/api/clients/${encodeURIComponent(clientId)}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      let message = t("actions.remove_client_failed");
      try {
        const payload = await resp.json();
        if (payload?.detail) message = String(payload.detail);
      } catch (_err) {}
      window.alert(message);
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

  els.menuButtons.forEach((btn) => {
    const onActivate = () => {
      const viewId = btn.dataset.view;
      if (viewId) setActiveView(viewId);
    };
    btn.addEventListener("click", onActivate);
    btn.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        onActivate();
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
  els.speedOverrideInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      applySpeedOverrideFromInput();
    }
  });
  els.saveSettingsBtn.addEventListener("click", saveSettingsFromInputs);
  window.addEventListener("resize", () => {
    if (state.spectrumPlot) state.spectrumPlot.setSize({ width: chartWidth(els.specChart), height: 360 });
  });

  loadVehicleSettings();
  syncSettingsInputs();
  applyLanguage(false);
  setActiveView("dashboardView");
  refreshLocationOptions();
  void syncAnalysisSettingsToServer();
  void syncSpeedOverrideToServer(state.vehicleSettings.speed_override_kmh);
  refreshLoggingStatus();
  refreshLogs();
  connectWS();
})();
