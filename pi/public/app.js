(() => {
  const els = {
    speed: document.getElementById("speed"),
    clientSelect: document.getElementById("clientSelect"),
    renameInput: document.getElementById("renameInput"),
    renameBtn: document.getElementById("renameBtn"),
    identifyBtn: document.getElementById("identifyBtn"),
    lastSeen: document.getElementById("lastSeen"),
    dropped: document.getElementById("dropped"),
    framesTotal: document.getElementById("framesTotal"),
    linkState: document.getElementById("linkState"),
    specChart: document.getElementById("specChart"),
    legend: document.getElementById("legend"),
    bandLegend: document.getElementById("bandLegend"),
    settingsToggle: document.getElementById("settingsToggle"),
    settingsPanel: document.getElementById("settingsPanel"),
    tireWidthInput: document.getElementById("tireWidthInput"),
    tireAspectInput: document.getElementById("tireAspectInput"),
    rimInput: document.getElementById("rimInput"),
    finalDriveInput: document.getElementById("finalDriveInput"),
    gearRatioInput: document.getElementById("gearRatioInput"),
    speedOverrideInput: document.getElementById("speedOverrideInput"),
    saveSettingsBtn: document.getElementById("saveSettingsBtn"),
    vibrationLog: document.getElementById("vibrationLog"),
    vibrationMatrix: document.getElementById("vibrationMatrix"),
    matrixTooltip: document.getElementById("matrixTooltip"),
  };

  const palette = ["#e63946", "#2a9d8f", "#3a86ff", "#f4a261", "#7b2cbf", "#1d3557", "#ff006e"];
  const settingsStorageKey = "vibesensor_vehicle_settings_v3";
  const sourceColumns = [
    { key: "engine", label: "Engine" },
    { key: "driveshaft", label: "Drive Shaft" },
    { key: "wheel", label: "Wheel/Tire" },
    { key: "other", label: "Other/Road" },
  ];
  const severityBands = [
    { key: "l5", label: "L5 Critical (>=40 dB)", minDb: 40, maxDb: Number.POSITIVE_INFINITY },
    { key: "l4", label: "L4 Severe (34-40 dB)", minDb: 34, maxDb: 40 },
    { key: "l3", label: "L3 Elevated (28-34 dB)", minDb: 28, maxDb: 34 },
    { key: "l2", label: "L2 Moderate (22-28 dB)", minDb: 22, maxDb: 28 },
    { key: "l1", label: "L1 Slight (16-22 dB)", minDb: 16, maxDb: 22 },
  ];
  const multiSyncWindowMs = 500;
  const multiFreqBinHz = 1.5;
  const orderUncertainty = {
    speed_pct: 0.03,
    tire_diameter_pct: 0.03,
    final_drive_pct: 0.015,
    gear_ratio_pct: 0.015,
    min_abs_hz: 0.8,
    max_rel_tol: 0.25,
  };

  const state = {
    ws: null,
    clients: [],
    selectedClientId: null,
    spectrumPlot: null,
    spectra: { freq: [], clients: {} },
    speedMps: null,
    vehicleSettings: {
      tire_width_mm: 285,
      tire_aspect_pct: 30,
      rim_in: 21,
      final_drive_ratio: 3.08,
      current_gear_ratio: 0.64,
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
  };

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
      if (typeof parsed.speed_override_kmh === "number") {
        state.vehicleSettings.speed_override_kmh = parsed.speed_override_kmh;
      }
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
    els.speedOverrideInput.value = String(state.vehicleSettings.speed_override_kmh);
  }

  function fmt(n, digits = 2) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "--";
    return n.toFixed(digits);
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

  function effectiveSpeedMps() {
    if (typeof state.speedMps === "number" && state.speedMps > 0) return state.speedMps;
    const overrideMps = (state.vehicleSettings.speed_override_kmh || 0) / 3.6;
    if (overrideMps > 0) return overrideMps;
    return null;
  }

  function combinedRelativeMargin(...parts) {
    let total = 0;
    for (const p of parts) {
      if (typeof p === "number" && p > 0) total += p;
    }
    return total;
  }

  function toleranceForOrder(baseTol, orderHz, uncertaintyPct) {
    const absFloor = orderUncertainty.min_abs_hz / Math.max(1, orderHz);
    return Math.min(orderUncertainty.max_rel_tol, Math.max(baseTol + uncertaintyPct, absFloor));
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
    const wheelUncertaintyPct = combinedRelativeMargin(orderUncertainty.speed_pct, orderUncertainty.tire_diameter_pct);
    const driveUncertaintyPct = combinedRelativeMargin(wheelUncertaintyPct, orderUncertainty.final_drive_pct);
    const engineUncertaintyPct = combinedRelativeMargin(driveUncertaintyPct, orderUncertainty.gear_ratio_pct);
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
    const series = [{ label: "Hz" }];
    for (const item of seriesMeta) {
      series.push({ label: item.label, stroke: item.color, width: 2 });
    }
    state.spectrumPlot = new uPlot(
      {
        title: "Multi-Sensor Blended Spectrum",
        width: chartWidth(els.specChart),
        height: 360,
        scales: { x: { time: false } },
        axes: [{ label: "Hz" }, { label: "Amplitude" }],
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

  function updateClientSelect() {
    const current = state.selectedClientId;
    els.clientSelect.innerHTML = "";
    for (const client of state.clients) {
      const option = document.createElement("option");
      option.value = client.id;
      option.textContent = `${client.name} (${client.id})`;
      els.clientSelect.appendChild(option);
    }
    if (!state.selectedClientId && state.clients.length > 0) {
      state.selectedClientId = state.clients[0].id;
    }
    if (current && state.clients.some((c) => c.id === current)) {
      state.selectedClientId = current;
    }
    if (state.selectedClientId) {
      els.clientSelect.value = state.selectedClientId;
    }
  }

  function renderStatus(clientRow) {
    if (!clientRow) {
      els.lastSeen.textContent = "Last seen: --";
      els.dropped.textContent = "Dropped frames: --";
      els.framesTotal.textContent = "Frames total: --";
      return;
    }
    const age = clientRow.last_seen_age_ms ?? null;
    els.lastSeen.textContent = age === null ? "Last seen: --" : `Last seen: ${age} ms ago`;
    els.dropped.textContent = `Dropped frames: ${clientRow.dropped_frames ?? 0}`;
    els.framesTotal.textContent = `Frames total: ${clientRow.frames_total ?? 0}`;
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
    const wheelSpread = toleranceForOrder(0.12, wheelHz, wheelUncertaintyPct);
    const driveSpread = toleranceForOrder(0.1, driveHz, driveUncertaintyPct);
    const engineSpread = toleranceForOrder(0.1, engineHz, engineUncertaintyPct);
    const out = [
      mk("Wheel 1x", wheelHz, wheelSpread, "rgba(42,157,143,0.14)"),
      mk("Wheel 2x", wheelHz * 2, wheelSpread, "rgba(42,157,143,0.11)"),
    ];
    const overlapTol = Math.max(0.03, driveUncertaintyPct + engineUncertaintyPct);
    if (Math.abs(driveHz - engineHz) / Math.max(1e-6, engineHz) < overlapTol) {
      out.push(mk("Driveshaft+Engine 1x", driveHz, Math.max(driveSpread, engineSpread), "rgba(120,95,180,0.15)"));
    } else {
      out.push(mk("Driveshaft 1x", driveHz, driveSpread, "rgba(58,134,255,0.14)"));
      out.push(mk("Engine 1x", engineHz, engineSpread, "rgba(230,57,70,0.14)"));
    }
    out.push(mk("Engine 2x", engineHz * 2, engineSpread, "rgba(230,57,70,0.11)"));
    return out;
  }

  function pushVibrationMessage(text) {
    state.vibrationMessages.unshift({ ts: new Date().toLocaleTimeString(), text });
    state.vibrationMessages = state.vibrationMessages.slice(0, 80);
    renderVibrationLog();
  }

  function renderVibrationLog() {
    if (!state.vibrationMessages.length) {
      els.vibrationLog.innerHTML = `<div class="log-row">No significant vibration events yet.</div>`;
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
      const wheelTol = toleranceForOrder(0.14, wheelHz, wheelUncertaintyPct);
      const driveTol = toleranceForOrder(0.12, driveHz, driveUncertaintyPct);
      const engineTol = toleranceForOrder(0.12, engineHz, engineUncertaintyPct);
      candidates.push({
        cause: "Wheel/Tire imbalance or radial force variation",
        hz: wheelHz,
        tol: wheelTol,
        key: "wheel1",
      });
      candidates.push({
        cause: "Tire non-uniformity or wheel resonance",
        hz: wheelHz * 2,
        tol: wheelTol,
        key: "wheel2",
      });
      const overlapTol = Math.max(0.03, driveUncertaintyPct + engineUncertaintyPct);
      if (Math.abs(driveHz - engineHz) / Math.max(1e-6, engineHz) < overlapTol) {
        candidates.push({
          cause: "Driveshaft/Engine 1x overlap (same order in current gear)",
          hz: driveHz,
          tol: Math.max(driveTol, engineTol),
          key: "shaft_eng1",
        });
      } else {
        candidates.push({
          cause: "Drive shaft imbalance or driveline angle issue",
          hz: driveHz,
          tol: driveTol,
          key: "shaft1",
        });
        candidates.push({
          cause: "Engine order vibration (mount/combustion/accessory related)",
          hz: engineHz,
          tol: engineTol,
          key: "eng1",
        });
      }
      candidates.push({
        cause: "Engine second-order vibration (common in 4-cylinder NVH)",
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
    if (peakHz >= 3 && peakHz <= 12) return { cause: "Road input / suspension or body resonance", key: "road" };
    return { cause: "Further diagnostics needed", key: "other" };
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
        return { key: band.key, label: band.label, db: adjustedDb };
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
      return `${source?.label || sourceKey} / ${band?.label || severityKey}\nNo events yet.`;
    }
    const parts = [`${source?.label || sourceKey} / ${band?.label || severityKey}`, `Total events: ${cell.count}`];
    const entries = Object.entries(cell.contributors).sort((a, b) => b[1] - a[1]);
    if (entries.length) {
      parts.push("By sensor scope:");
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
    const header = (
      `<thead><tr><th>Amplitude Group</th>` +
      `${sourceColumns.map((s) => `<th>${s.label}</th>`).join("")}</tr></thead>`
    );
    const bodyRows = severityBands
      .map((band) => {
        const cells = sourceColumns
          .map((src) => {
            const val = state.eventMatrix[src.key][band.key].count;
            return `<td class="vib-cell" data-source="${src.key}" data-severity="${band.key}">${val}</td>`;
          })
          .join("");
        return `<tr><td>${band.label}</td>${cells}</tr>`;
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
    const grouped = new Map();
    for (const ev of state.recentDetectionEvents) {
      const freqBin = Math.round(ev.peakHz / multiFreqBinHz);
      const gKey = `${ev.cls.key}:${freqBin}`;
      if (!grouped.has(gKey)) grouped.set(gKey, new Map());
      const sensorMap = grouped.get(gKey);
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
        `Strong multi-sensor vibration detected on ${group.length} sensors [${labels.join(", ")}]. ` +
          `Frequency and amplitude are ${fmt(avgHz, 2)} Hz and ${fmt(avgAmp, 1)}. ` +
          `Severity: ${sev.label}. Most likely cause: ${group[0].cls.cause}.`,
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
        `Vibration detected by sensor ${ev.sensorLabel}. ` +
          `Frequency and amplitude are ${fmt(ev.peakHz, 2)} Hz and ${fmt(ev.peakAmp, 1)}. ` +
          `Severity: ${sev.label}. Most likely cause: ${ev.cls.cause}.`,
      );
    }
    renderMatrix();
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
      els.linkState.textContent = "WS: connected";
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
      els.linkState.textContent = "WS: reconnecting...";
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
    state.clients = payload.clients || [];
    if (payload.spectra) {
      state.spectra = payload.spectra;
    }
    updateClientSelect();

    if (typeof payload.speed_mps === "number") {
      state.speedMps = payload.speed_mps;
      els.speed.textContent = `Speed: ${fmt(payload.speed_mps, 2)} m/s (GPS)`;
    } else {
      state.speedMps = null;
      const spd = effectiveSpeedMps();
      els.speed.textContent = spd ? `Speed: ${fmt(spd, 2)} m/s (Override)` : "Speed: -- m/s";
    }
    if (payload.spectra) {
      renderSpectrum();
    }
    const row = state.clients.find((c) => c.id === state.selectedClientId);
    renderStatus(row);
  }

  async function renameClient() {
    if (!state.selectedClientId) return;
    const name = els.renameInput.value.trim();
    if (!name) return;
    await fetch(`/api/clients/${state.selectedClientId}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    els.renameInput.value = "";
  }

  async function identifyClient() {
    if (!state.selectedClientId) return;
    await fetch(`/api/clients/${state.selectedClientId}/identify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration_ms: 1500 }),
    });
  }

  function saveSettingsFromInputs() {
    const parsed = parseTireSpec({
      widthMm: Number(els.tireWidthInput.value),
      aspect: Number(els.tireAspectInput.value),
      rimIn: Number(els.rimInput.value),
    });
    const finalDrive = Number(els.finalDriveInput.value);
    const gear = Number(els.gearRatioInput.value);
    const speedOverride = Number(els.speedOverrideInput.value);
    if (!parsed || !(finalDrive > 0 && gear > 0) || !(speedOverride >= 0)) return;

    state.vehicleSettings.tire_width_mm = parsed.widthMm;
    state.vehicleSettings.tire_aspect_pct = parsed.aspect;
    state.vehicleSettings.rim_in = parsed.rimIn;
    state.vehicleSettings.final_drive_ratio = finalDrive;
    state.vehicleSettings.current_gear_ratio = gear;
    state.vehicleSettings.speed_override_kmh = speedOverride;
    saveVehicleSettings();
    renderSpectrum();
  }

  els.clientSelect.addEventListener("change", () => {
    state.selectedClientId = els.clientSelect.value;
    sendSelection();
  });
  els.renameBtn.addEventListener("click", renameClient);
  els.identifyBtn.addEventListener("click", identifyClient);
  els.saveSettingsBtn.addEventListener("click", saveSettingsFromInputs);
  els.settingsToggle.addEventListener("click", () => {
    els.settingsPanel.classList.toggle("open");
  });
  window.addEventListener("resize", () => {
    if (state.spectrumPlot) state.spectrumPlot.setSize({ width: chartWidth(els.specChart), height: 360 });
  });

  loadVehicleSettings();
  syncSettingsInputs();
  renderVibrationLog();
  renderMatrix();
  connectWS();
})();
