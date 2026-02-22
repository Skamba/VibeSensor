import type { UiDomElements } from "../dom/ui_dom_registry";
import type { AppState } from "../state/ui_app_state";
import {
  deleteHistoryRun as deleteHistoryRunApi,
  getHistory,
  getHistoryInsights,
  historyExportUrl,
  historyReportPdfUrl,
} from "../../api";
import { normalizeUnit, heatColor } from "./heat_utils";

export interface HistoryFeatureDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, any>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}

export interface HistoryFeature {
  renderHistoryTable(): void;
  refreshHistory(): Promise<void>;
  deleteAllRuns(): Promise<void>;
  onHistoryTableAction(action: string, runId: string): Promise<void>;
  toggleRunDetails(runId: string): void;
  reloadExpandedRunOnLanguageChange(): void;
}

export function createHistoryFeature(ctx: HistoryFeatureDeps): HistoryFeature {
  const { state, els, t, escapeHtml, fmt, fmtTs, formatInt } = ctx;
  const DOWNLOAD_REVOKE_DELAY_MS = 1000;

  function ensureRunDetail(runId: string) {
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

  function collapseExpandedRun(): void {
    const previous = state.expandedRunId;
    state.expandedRunId = null;
    if (previous) {
      delete state.runDetailsById[previous];
    }
  }

  function summarizeFindings(summary: Record<string, any> | null): unknown[] {
    const findings = Array.isArray(summary?.findings) ? summary!.findings : [];
    return findings.slice(0, 3);
  }

  function normalizeLogLocationKey(location: string): string {
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

  function metricFromLocationStat(row: Record<string, any>): number | null {
    if (!row || typeof row !== "object") return null;
    return (
      Number(row.p95_intensity_g ?? row.p95 ?? row.mean_intensity_g ?? row.max_intensity_g) || null
    );
  }

  function renderPreviewHeatmap(summary: Record<string, any>): string {
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
    const metricByLocation: Record<string, number> = {};
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
        const norm = normalizeUnit(value, min!, max!);
        const fill = heatColor(norm);
        const valueLabel = `${fmt(value, 4)} g`;
        return `<div class="mini-car-dot" style="top:${point.top}%;left:${point.left}%;background:${fill}" title="${escapeHtml(point.key)}: ${escapeHtml(valueLabel)}"></div>`;
      })
      .join("");
    const unmappedSummary = unmappedLocationKeys.length
      ? `<div class="subtle">${escapeHtml(unmappedLocationKeys.join(", "))}</div>`
      : "";
    return `\n      <div class="mini-car-wrap">\n        <div class="mini-car-title">${escapeHtml(t("history.preview_heatmap_title"))}</div>\n        <div class="mini-car">${dots}</div>\n        ${unmappedSummary}\n      </div>\n    `;
  }

  function renderPreviewStats(summary: Record<string, any>): string {
    const rows = Array.isArray(summary?.sensor_intensity_by_location)
      ? summary.sensor_intensity_by_location
      : [];
    if (!rows.length) {
      return `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
    }
    const body = rows
      .map((row: Record<string, any>) => {
        const dropped = row?.dropped_frames_delta ?? row?.frames_dropped_delta;
        const overflow = row?.queue_overflow_drops_delta;
        return `\n          <tr>\n            <td>${escapeHtml(row.location || "--")}</td>\n            <td class="numeric">${fmt(row.p50_intensity_g ?? row.p50, 4)}</td>\n            <td class="numeric">${fmt(row.p95_intensity_g ?? row.p95, 4)}</td>\n            <td class="numeric">${fmt(row.max_intensity_g, 4)}</td>\n            <td class="numeric">${typeof dropped === "number" ? formatInt(dropped) : "--"}</td>\n            <td class="numeric">${typeof overflow === "number" ? formatInt(overflow) : "--"}</td>\n            <td class="numeric">${formatInt(row.sample_count ?? row.samples)}</td>\n          </tr>`;
      })
      .join("");
    return `\n      <div class="history-preview-stats">\n        <div class="mini-car-title">${escapeHtml(t("history.preview_stats_title"))}</div>\n        <table class="history-preview-table">\n          <thead>\n            <tr>\n              <th>${escapeHtml(t("history.table.location"))}</th>\n              <th class="numeric">p50</th>\n              <th class="numeric">p95</th>\n              <th class="numeric">max</th>\n              <th class="numeric">${escapeHtml(t("history.table.dropped_delta"))}</th>\n              <th class="numeric">${escapeHtml(t("history.table.overflow_delta"))}</th>\n              <th class="numeric">${escapeHtml(t("history.table.samples"))}</th>\n            </tr>\n          </thead>\n          <tbody>${body}</tbody>\n        </table>\n      </div>\n    `;
  }

  function renderInsightsBlock(detail: Record<string, any>): string {
    const findings = summarizeFindings(detail.insights as Record<string, any> | null);
    const ctaLabel = detail.insights ? t("history.reload_insights") : t("history.load_insights");
    const loading = detail.insightsLoading;
    const findingsMarkup = findings.length
      ? findings
          .map((finding: Record<string, any>) => {
            const source = finding?.suspected_source || t("report.missing");
            const confidence = typeof finding?.confidence_0_to_1 === "number" ? fmt(finding.confidence_0_to_1, 2) : "--";
            return `<li><strong>${escapeHtml(source)}</strong> (${escapeHtml(t("report.confidence", { value: confidence }))}) - ${escapeHtml(finding?.evidence_summary || "")}</li>`;
          })
          .join("")
      : `<li>${escapeHtml(t("report.no_findings_for_run"))}</li>`;
    return `\n      <div class="history-insights-block">\n        <div class="history-insights-actions">\n          <button class="btn btn--primary" data-run-action="load-insights" ${loading ? "disabled" : ""}>${escapeHtml(loading ? t("history.loading_insights") : ctaLabel)}</button>\n          ${detail.insightsError ? `<span class="history-inline-error">${escapeHtml(detail.insightsError)}</span>` : ""}\n        </div>\n        ${detail.insights ? `<ul class="history-findings-list">${findingsMarkup}</ul>` : ""}\n      </div>\n    `;
  }

  function renderRunDetailsRow(run: Record<string, any>, detail: Record<string, any>): string {
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
      previewMarkup = `\n        <div class="history-details-preview">\n          ${renderPreviewHeatmap(summary)}\n          ${renderPreviewStats(summary)}\n        </div>\n      `;
    } else {
      previewMarkup = `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
    }
    return `\n      <tr class="history-details-row">\n        <td colspan="4">\n          <div class="history-details-card">\n            ${runSummary ? `<div class="history-run-summary">${escapeHtml(runSummary)}</div>` : ""}\n            ${previewMarkup}\n            ${renderInsightsBlock(detail)}\n          </div>\n        </td>\n      </tr>\n    `;
  }

  function renderHistoryTable(): void {
    if (els.deleteAllRunsBtn) {
      els.deleteAllRunsBtn.disabled = state.deleteAllRunsInFlight || state.runs.length === 0;
    }
    if (!state.runs.length) {
      if (els.historySummary) els.historySummary.textContent = t("history.none");
      if (els.historyTableBody) els.historyTableBody.innerHTML = `<tr><td colspan="4">${escapeHtml(t("history.none_found"))}</td></tr>`;
      collapseExpandedRun();
      return;
    }
    if (state.expandedRunId && !state.runs.some((row) => row.run_id === state.expandedRunId)) {
      collapseExpandedRun();
    }
    if (els.historySummary) els.historySummary.textContent = t("history.available_count", { count: state.runs.length });
    const rows: string[] = [];
    for (const run of state.runs) {
      const detail = ensureRunDetail(run.run_id);
      const pdfLabel = detail.pdfLoading ? t("history.generating_pdf") : t("history.generate_pdf");
      const rowError = detail.pdfError ? `<div class="history-inline-error">${escapeHtml(detail.pdfError)}</div>` : "";
      rows.push(`\n        <tr class="history-row${state.expandedRunId === run.run_id ? " history-row--expanded" : ""}" data-run-row="1" data-run="${escapeHtml(run.run_id)}">\n          <td>${escapeHtml(run.run_id)}</td>\n          <td>${fmtTs(run.start_time_utc)}</td>\n          <td class="numeric">${formatInt(run.sample_count)}</td>\n          <td>\n            <div class="table-actions">\n              <button class="btn btn--success" data-run-action="download-pdf" data-run="${escapeHtml(run.run_id)}" ${detail.pdfLoading ? "disabled" : ""}>${escapeHtml(pdfLabel)}</button>\n              <a class="btn btn--muted" href="${historyExportUrl(run.run_id)}" download="${escapeHtml(run.run_id)}.zip" data-run-action="download-raw" data-run="${escapeHtml(run.run_id)}">${escapeHtml(t("history.export"))}</a>\n              <button class="btn btn--danger" data-run-action="delete-run" data-run="${escapeHtml(run.run_id)}">${escapeHtml(t("history.delete"))}</button>\n            </div>\n            ${rowError}\n          </td>\n        </tr>`);
      if (state.expandedRunId === run.run_id) rows.push(renderRunDetailsRow(run, detail));
    }
    if (els.historyTableBody) els.historyTableBody.innerHTML = rows.join("");
  }

  async function refreshHistory(): Promise<void> {
    try {
      const payload = await getHistory() as Record<string, any>;
      state.runs = Array.isArray(payload.runs) ? payload.runs : [];
      renderHistoryTable();
    } catch (_err) {
      state.runs = [];
      renderHistoryTable();
    }
  }

  async function deleteRun(runId: string): Promise<void> {
    if (!runId) return;
    const ok = window.confirm(t("history.delete_confirm", { name: runId }));
    if (!ok) return;
    try {
      await deleteHistoryRunApi(runId);
    } catch (err) {
      window.alert(err?.message || t("history.delete_failed"));
      return;
    }
    if (state.expandedRunId === runId) collapseExpandedRun();
    await refreshHistory();
  }

  async function deleteAllRuns(): Promise<void> {
    const names = state.runs.map((row) => (row && typeof row.run_id === "string" ? row.run_id : "")).filter((name) => Boolean(name));
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
        if (state.expandedRunId === name) collapseExpandedRun();
      } catch (err) {
        failed += 1;
        if (!firstError) firstError = err?.message || t("history.delete_failed");
      }
    }
    state.deleteAllRunsInFlight = false;
    await refreshHistory();
    if (failed > 0) {
      const summary = t("history.delete_all_partial", { deleted, total: names.length, failed });
      window.alert(firstError ? `${summary}\n${firstError}` : summary);
    }
  }

  async function loadRunPreview(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) return;
    detail.previewLoading = true;
    detail.previewError = "";
    renderHistoryTable();
    try {
      detail.preview = await getHistoryInsights(runId, state.lang) as Record<string, any>;
    } catch (err) {
      detail.previewError = err?.message || t("report.unable_load_insights");
    } finally {
      detail.previewLoading = false;
      renderHistoryTable();
    }
  }

  async function loadRunInsights(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ensureRunDetail(runId);
    if (!force && detail.insightsLoading) return;
    detail.insightsLoading = true;
    detail.insightsError = "";
    renderHistoryTable();
    try {
      detail.insights = await getHistoryInsights(runId, state.lang) as Record<string, any>;
    } catch (err) {
      detail.insightsError = err?.message || t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
      renderHistoryTable();
    }
  }

  function filenameFromDisposition(headerValue: string | null, fallback: string): string {
    if (!headerValue) return fallback;
    const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) return decodeURIComponent(utf8Match[1]);
    const simpleMatch = headerValue.match(/filename="?([^";]+)"?/i);
    if (simpleMatch && simpleMatch[1]) return simpleMatch[1];
    return fallback;
  }

  async function downloadBlobFile(url: string, fallbackName: string): Promise<void> {
    const response = await fetch(url);
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (payload && typeof payload.detail === "string") detail = payload.detail;
      } catch (_err) { /* ignore */ }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const fileName = filenameFromDisposition(response.headers.get("content-disposition"), fallbackName || "download.bin");
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), DOWNLOAD_REVOKE_DELAY_MS);
  }

  async function downloadReportPdfForRun(runId: string): Promise<void> {
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

  function toggleRunDetails(runId: string): void {
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

  async function onHistoryTableAction(action: string, runId: string): Promise<void> {
    if (!action || !runId) return;
    if (action === "download-pdf") return downloadReportPdfForRun(runId);
    if (action === "delete-run") return deleteRun(runId);
    if (action === "load-insights") await loadRunInsights(runId, true);
  }

  function reloadExpandedRunOnLanguageChange(): void {
    if (!state.expandedRunId) return;
    const runId = state.expandedRunId;
    const detail = state.runDetailsById?.[runId];
    const shouldReloadInsights = Boolean(detail?.insights);
    delete state.runDetailsById[runId];
    void loadRunPreview(runId, true).then(() => {
      if (shouldReloadInsights) void loadRunInsights(runId, true);
    });
  }

  return { renderHistoryTable, refreshHistory, deleteAllRuns, onHistoryTableAction, toggleRunDetails, reloadExpandedRunOnLanguageChange };
}
