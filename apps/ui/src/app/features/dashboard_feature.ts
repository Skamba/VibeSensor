import uPlot from "uplot";
import type { UiDomElements } from "../dom/ui_dom_registry";
import type { AppState, ClientRow } from "../state/ui_app_state";
import type { AdaptedPayload } from "../../server_payload";
import { createEmptyMatrix, normalizeStrengthBands } from "../../diagnostics";
import { sourceColumns } from "../../constants";
import { normalizeUnit, heatColor } from "./heat_utils";

export interface DashboardFeatureDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, any>) => string;
  fmt: (n: number, digits?: number) => string;
  escapeHtml: (value: unknown) => string;
  locationCodeForClient: (client: ClientRow) => string;
  carMapPositions: Record<string, { top: number; left: number }>;
  carMapWindowMs: number;
  metricField: string;
}

export interface DashboardFeature {
  renderVibrationLog(): void;
  renderMatrix(): void;
  applyServerDiagnostics(diagnostics: AdaptedPayload["diagnostics"], hasFreshFrames?: boolean): void;
  hasFreshSensorFrames(clients: ClientRow[]): boolean;
  extractLiveLocationIntensity(): Record<string, number>;
  pushCarMapSample(byLocation: Record<string, number>): void;
  renderCarMap(): void;
  resetLiveVibrationCounts(): void;
}

export function createDashboardFeature(ctx: DashboardFeatureDeps): DashboardFeature {
  const { state, els, t, fmt, carMapPositions, carMapWindowMs, metricField } = ctx;

  function pushCarMapSample(byLocation: Record<string, number>): void {
    const now = Date.now();
    state.carMapSamples.push({ ts: now, byLocation });
    const cutoff = now - carMapWindowMs;
    state.carMapSamples = state.carMapSamples.filter((s) => s.ts >= cutoff);
  }

  function carMapIntensityByLocation(): Record<string, number> {
    if (!state.carMapSamples.length) return {};
    const accum: Record<string, number[]> = {};
    for (const sample of state.carMapSamples) {
      for (const [loc, val] of Object.entries(sample.byLocation)) {
        if (!accum[loc]) accum[loc] = [];
        accum[loc].push(val);
      }
    }
    const result: Record<string, number> = {};
    for (const [loc, values] of Object.entries(accum)) {
      const sorted = [...values].sort((a, b) => a - b);
      const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
      result[loc] = sorted[idx];
    }
    return result;
  }

  function triggerCarMapPulse(locationCodes: string[]): void {
    for (const code of locationCodes) state.carMapPulseLocations.add(code);
    renderCarMap();
    setTimeout(() => {
      for (const code of locationCodes) state.carMapPulseLocations.delete(code);
      renderCarMap();
    }, 750);
  }

  function renderCarMap(): void {
    if (!els.liveCarMapDots) return;
    const intensity = carMapIntensityByLocation();
    const values = Object.values(intensity);
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 0;
    const dots: string[] = [];
    for (const [code, pos] of Object.entries(carMapPositions)) {
      const val = intensity[code];
      const hasVal = typeof val === "number" && Number.isFinite(val) && val > 0;
      const norm = hasVal ? normalizeUnit(val, min, max) : 0;
      const fill = hasVal ? heatColor(norm) : "var(--border)";
      const visible = hasVal ? " car-map-dot--visible" : "";
      const pulse = state.carMapPulseLocations.has(code) ? " car-map-dot--pulse" : "";
      dots.push(`<div class="car-map-dot${visible}${pulse}" style="top:${pos.top}%;left:${pos.left}%;background:${fill}" data-location="${code}"></div>`);
    }
    els.liveCarMapDots.innerHTML = dots.join("");
  }

  function extractLiveLocationIntensity(): Record<string, number> {
    const byLocation: Record<string, number> = {};
    if (!state.spectra?.clients || !state.clients?.length) return byLocation;
    for (const client of state.clients) {
      if (!client?.connected) continue;
      const code = ctx.locationCodeForClient(client);
      if (!code) continue;
      const spec = state.spectra.clients[client.id];
      if (!spec?.strength_metrics) continue;
      const amp = Number(spec.strength_metrics[metricField]);
      if (Number.isFinite(amp) && amp > 0) byLocation[code] = Math.max(byLocation[code] || 0, amp);
    }
    return byLocation;
  }

  function pushVibrationMessage(text: string): void {
    state.vibrationMessages.unshift({ ts: new Date().toLocaleTimeString(), text });
    state.vibrationMessages = state.vibrationMessages.slice(0, 80);
    renderVibrationLog();
  }

  function renderVibrationLog(): void {
    if (!els.vibrationLog) return;
    if (!state.vibrationMessages.length) {
      els.vibrationLog.innerHTML = `<div class="log-row">${ctx.escapeHtml(t("vibration.none"))}</div>`;
      return;
    }
    els.vibrationLog.innerHTML = state.vibrationMessages.map((m) => `<div class="log-row"><div class="log-time">${m.ts}</div>${m.text}</div>`).join("");
  }

  function tooltipForCell(sourceKey: string, severityKey: string): string {
    const source = sourceColumns.find((s) => s.key === sourceKey);
    const band = state.strengthBands.find((b) => b.key === severityKey);
    const cell = state.eventMatrix[sourceKey]?.[severityKey];
    if (!cell || cell.count === 0) return `${t(source?.labelKey || sourceKey)} / ${t(band?.labelKey || severityKey)}\n${t("tooltip.no_events")}`;
    const parts = [`${t(source?.labelKey || sourceKey)} / ${t(band?.labelKey || severityKey)}`, t("tooltip.total_events", { count: cell.count }), `Seconds: ${fmt(cell.seconds || 0, 1)}`];
    const entries = Object.entries(cell.contributors).sort((a, b) => b[1] - a[1]);
    if (entries.length) {
      parts.push(t("tooltip.by_sensor_scope"));
      for (const [name, cnt] of entries) parts.push(`- ${name}: ${cnt}`);
    }
    return parts.join("\n");
  }

  function showMatrixTooltip(text: string, x: number, y: number): void {
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

  function hideMatrixTooltip(): void {
    if (!els.matrixTooltip) return;
    els.matrixTooltip.style.display = "none";
  }

  function bindMatrixTooltips(): void {
    if (!els.vibrationMatrix) return;
    const cells = els.vibrationMatrix.querySelectorAll(".vib-cell");
    for (const cell of cells) {
      const sourceKey = cell.getAttribute("data-source");
      const severityKey = cell.getAttribute("data-severity");
      if (!sourceKey || !severityKey) continue;
      cell.addEventListener("mouseenter", (ev: Event) => {
        const me = ev as MouseEvent;
        showMatrixTooltip(tooltipForCell(sourceKey, severityKey), me.clientX, me.clientY);
      });
      cell.addEventListener("mousemove", (ev: Event) => {
        const me = ev as MouseEvent;
        showMatrixTooltip(tooltipForCell(sourceKey, severityKey), me.clientX, me.clientY);
      });
      cell.addEventListener("mouseleave", hideMatrixTooltip);
      cell.addEventListener("blur", hideMatrixTooltip);
    }
  }

  function renderMatrix(): void {
    if (!els.vibrationMatrix) return;
    hideMatrixTooltip();
    const header = `<thead><tr><th>${ctx.escapeHtml(t("matrix.amplitude_group"))}</th>${sourceColumns.map((s) => `<th>${ctx.escapeHtml(t(s.labelKey))}</th>`).join("")}</tr></thead>`;
    const bodyRows = [...state.strengthBands].sort((a, b) => b.min_db - a.min_db).map((band) => {
      const cells = sourceColumns.map((src) => {
        const val = state.eventMatrix?.[src.key]?.[band.key]?.count ?? 0;
        return `<td class="vib-cell" data-source="${src.key}" data-severity="${band.key}">${val}</td>`;
      }).join("");
      return `<tr><td>${ctx.escapeHtml(t(band.labelKey || band.key))}</td>${cells}</tr>`;
    }).join("");
    els.vibrationMatrix.innerHTML = `${header}<tbody>${bodyRows}</tbody>`;
    bindMatrixTooltips();
  }

  function hasFreshSensorFrames(clients: ClientRow[]): boolean {
    const rows = Array.isArray(clients) ? clients : [];
    let hasFresh = false;
    const nextTotals: Record<string, number> = {};
    for (const row of rows) {
      const clientId = row?.id;
      if (!clientId) continue;
      const framesTotal = Number(row?.frames_total ?? 0);
      if (!Number.isFinite(framesTotal)) continue;
      const prev = Number(state.strengthFrameTotalsByClient?.[clientId]);
      if (!Number.isFinite(prev)) {
        if (framesTotal > 0) hasFresh = true;
      } else if (framesTotal > prev) hasFresh = true;
      nextTotals[clientId] = framesTotal;
    }
    state.strengthFrameTotalsByClient = nextTotals;
    return hasFresh;
  }

  function yRangeFromBands(): [number, number] {
    const bands = state.strengthBands;
    if (!bands.length) return [0, 50];
    const min = Math.max(0, Math.floor(Math.min(...bands.map((band) => band.min_db)) - 4));
    const max = Math.ceil(Math.max(...bands.map((band) => band.min_db)) + 10);
    return [min, max];
  }

  function ensureStrengthChart(): void {
    if (!els.strengthChart || state.strengthPlot) return;
    const shadePlugin: uPlot.Plugin = { hooks: { drawClear: [
      (u: uPlot) => {
        const ctx2 = u.ctx;
        const ordered = [...state.strengthBands].sort((a, b) => a.min_db - b.min_db);
        for (let idx = 0; idx < ordered.length; idx++) {
          const band = ordered[idx];
          const nextMin = idx + 1 < ordered.length ? ordered[idx + 1].min_db : yRangeFromBands()[1];
          const y0 = u.valToPos(nextMin, "y", true);
          const y1 = u.valToPos(band.min_db, "y", true);
          ctx2.fillStyle = `hsla(${220 - idx * 35}, 70%, 55%, 0.08)`;
          ctx2.fillRect(u.bbox.left, y0, u.bbox.width, y1 - y0);
          ctx2.strokeStyle = "rgba(79,93,115,0.28)";
          ctx2.beginPath();
          ctx2.moveTo(u.bbox.left, y1);
          ctx2.lineTo(u.bbox.left + u.bbox.width, y1);
          ctx2.stroke();
          ctx2.fillStyle = "#4f5d73";
          ctx2.font = "11px Segoe UI";
          ctx2.fillText(band.key.toUpperCase(), u.bbox.left + u.bbox.width + 8, y1 + 4);
        }
      },
    ], setCursor: [
      (u: uPlot) => {
        const idx = u.cursor?.idx;
        if (idx == null || idx < 0) {
          if (els.strengthTooltip) els.strengthTooltip.style.display = "none";
          return;
        }
        const labels = ["wheel", "driveshaft", "engine", "other"];
        const lines = labels.map((label, i) => `${label}: ${fmt((u.data[i + 1]?.[idx]) || 0, 1)} dB`);
        if (els.strengthTooltip) {
          els.strengthTooltip.textContent = lines.join("\n");
          els.strengthTooltip.style.display = "block";
        }
      },
    ] } };
    state.strengthPlot = new uPlot({ title: "Strength over time", width: Math.max(320, Math.floor(els.strengthChart.getBoundingClientRect().width || 320)), height: 240, scales: { x: { time: false }, y: { range: yRangeFromBands() as uPlot.Range.MinMax } }, axes: [{ label: "s" }, { label: "Strength (dB over floor)" }], series: [{ label: "t" }, { label: "wheel", stroke: "#2563eb", width: 2 }, { label: "driveshaft", stroke: "#14b8a6", width: 2 }, { label: "engine", stroke: "#f59e0b", width: 2 }, { label: "other", stroke: "#8b5cf6", width: 2 }], plugins: [shadePlugin] }, [[], [], [], [], []], els.strengthChart);
    const resize = () => {
      if (!state.strengthPlot || !els.strengthChart) return;
      state.strengthPlot.setSize({ width: Math.max(320, Math.floor(els.strengthChart.getBoundingClientRect().width || 320)), height: 240 });
    };
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) resize(); });
  }

  function pushStrengthSample(bySource: Record<string, Record<string, any>>): void {
    ensureStrengthChart();
    if (!state.strengthPlot) return;
    const now = Date.now() / 1000;
    state.strengthHistory.t.push(now);
    for (const key of ["wheel", "driveshaft", "engine", "other"] as const) state.strengthHistory[key].push(bySource?.[key]?.strength_db || 0);
    while (state.strengthHistory.t.length && now - state.strengthHistory.t[0] > 60) {
      state.strengthHistory.t.shift();
      state.strengthHistory.wheel.shift();
      state.strengthHistory.driveshaft.shift();
      state.strengthHistory.engine.shift();
      state.strengthHistory.other.shift();
    }
    const t0 = state.strengthHistory.t[0] || now;
    const relT = state.strengthHistory.t.map((v) => v - t0);
    state.strengthPlot.setScale("y", { min: yRangeFromBands()[0], max: yRangeFromBands()[1] });
    state.strengthPlot.setData([relT, state.strengthHistory.wheel, state.strengthHistory.driveshaft, state.strengthHistory.engine, state.strengthHistory.other]);
  }

  function applyServerDiagnostics(diagnostics: AdaptedPayload["diagnostics"], hasFreshFrames = false): void {
    state.strengthBands = normalizeStrengthBands(diagnostics.strength_bands);
    if (diagnostics.matrix) state.eventMatrix = diagnostics.matrix;
    renderMatrix();
    if (!hasFreshFrames) return;
    const events = Array.isArray(diagnostics.events) ? diagnostics.events : [];
    const eventPulseLocations: string[] = [];
    if (events.length) {
      for (const ev of events.slice(0, 6)) {
        const labels = Array.isArray(ev.sensor_labels) ? ev.sensor_labels.join(", ") : (ev.sensor_label || "--");
        pushVibrationMessage(`Strength ${String(ev.severity_key || "l1").toUpperCase()} (${fmt(Number(ev.vibration_strength_db) || 0, 1)} dB) @ ${fmt(Number(ev.peak_hz) || 0, 2)} Hz | ${labels} | ${ev.class_key || "other"}`);
        const sensorLabels: string[] = Array.isArray(ev.sensor_labels) ? ev.sensor_labels : ev.sensor_label ? [String(ev.sensor_label)] : [];
        for (const label of sensorLabels) {
          for (const client of state.clients) {
            if ((client.name || client.id) === label) {
              const code = ctx.locationCodeForClient(client);
              if (code) eventPulseLocations.push(code);
            }
          }
        }
      }
    }
    if (eventPulseLocations.length) triggerCarMapPulse(eventPulseLocations);
    const bySource = (diagnostics.levels || {}).by_source || {};
    pushStrengthSample(bySource);
  }

  function resetLiveVibrationCounts(): void {
    state.eventMatrix = createEmptyMatrix();
    renderMatrix();
  }

  return {
    resetLiveVibrationCounts,
    renderVibrationLog,
    renderMatrix,
    applyServerDiagnostics,
    hasFreshSensorFrames,
    extractLiveLocationIntensity,
    pushCarMapSample,
    renderCarMap,
  };
}
