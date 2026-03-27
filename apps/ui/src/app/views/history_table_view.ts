import type {
  FindingPayload,
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import { HISTORY_HEATMAP_POSITIONS } from "../../config";
import type { RunDetail } from "../ui_app_state";
import { heatColor, normalizeUnit } from "../features/heat_utils";
import { closestFromTarget, renderTableEmptyRow } from "./dom_helpers";

type LocationIntensityRow = HistoryInsightsPayload["sensor_intensity_by_location"][number];

const EMPTY_RUN_DETAIL: RunDetail = {
  preview: null,
  previewLoading: false,
  previewError: "",
  insights: null,
  insightsLoading: false,
  insightsError: "",
  pdfLoading: false,
  pdfError: "",
};

export interface HistoryTableViewParams {
  runs: HistoryEntry[];
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  historyExportUrl: (runId: string) => string;
}

export interface HistoryTableAction {
  action: string;
  runId: string | null;
}

function summarizeFindings(summary: HistoryInsightsPayload | null): FindingPayload[] {
  return summary?.findings?.slice(0, 3) ?? [];
}

function summarizeWarnings(payload: HistoryInsightsPayload | null): HistoryInsightWarningPayload[] {
  return payload?.warnings ?? [];
}

function normalizeLogLocationKey(location: unknown): string {
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

function sensorIntensityRows(summary: HistoryInsightsPayload | null): LocationIntensityRow[] {
  return summary?.sensor_intensity_by_location ?? [];
}

function metricFromLocationStat(row: LocationIntensityRow): number | null {
  const value = Number(row.p95_intensity_db ?? row.mean_intensity_db ?? row.max_intensity_db);
  return Number.isFinite(value) ? value : null;
}

function renderPreviewHeatmap(
  summary: HistoryInsightsPayload,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, fmt, t } = params;
  const statsRows = sensorIntensityRows(summary);
  const metricByLocation: Record<string, number> = {};
  for (const row of statsRows) {
    const key = normalizeLogLocationKey(row.location);
    const metric = metricFromLocationStat(row);
    if (key && typeof metric === "number" && Number.isFinite(metric)) {
      metricByLocation[key] = metric;
    }
  }
  const values = Object.values(metricByLocation).filter((value) => typeof value === "number");
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const knownPositionKeys = new Set<string>(HISTORY_HEATMAP_POSITIONS.map((point) => point.key));
  const unmappedLocationKeys = Object.keys(metricByLocation).filter((key) => !knownPositionKeys.has(key));
  const dots = HISTORY_HEATMAP_POSITIONS
    .map((point) => {
      const value = metricByLocation[point.key];
      const hasValue = typeof value === "number" && Number.isFinite(value);
      if (!hasValue || min === null || max === null) return "";
      const norm = normalizeUnit(value, min, max);
      const fill = heatColor(norm);
      const valueLabel = `${fmt(value, 1)} dB`;
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

function renderPreviewStats(
  summary: HistoryInsightsPayload,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "formatInt" | "t">,
): string {
  const { escapeHtml, fmt, formatInt, t } = params;
  const rows = sensorIntensityRows(summary);
  if (!rows.length) {
    return `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
  }
  const body = rows
    .map((row) => {
      const dropped = row.dropped_frames_delta;
      const overflow = row.queue_overflow_drops_delta;
      return `
          <tr>
            <td>${escapeHtml(row.location || "--")}</td>
            <td class="numeric">${fmt(Number(row.p50_intensity_db), 1)}</td>
            <td class="numeric">${fmt(Number(row.p95_intensity_db), 1)}</td>
            <td class="numeric">${fmt(Number(row.max_intensity_db), 1)}</td>
            <td class="numeric">${typeof dropped === "number" ? formatInt(dropped) : "--"}</td>
            <td class="numeric">${typeof overflow === "number" ? formatInt(overflow) : "--"}</td>
            <td class="numeric">${formatInt(Number(row.sample_count))}</td>
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
              <th class="numeric">${escapeHtml(t("history.table.p50_db"))}</th>
              <th class="numeric">${escapeHtml(t("history.table.p95_db"))}</th>
              <th class="numeric">${escapeHtml(t("history.table.max_db"))}</th>
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

function renderInsightsBlock(
  detail: RunDetail,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, fmt, t } = params;
  const findings = summarizeFindings(detail.insights);
  const ctaLabel = detail.insights ? t("history.reload_insights") : t("history.load_insights");
  const loading = detail.insightsLoading;
  const findingsMarkup = findings.length
    ? findings
        .map((finding) => {
          const source = finding.suspected_source || t("report.missing");
          const confidence = typeof finding.confidence === "number" ? fmt(finding.confidence, 2) : "--";
          const evidenceSummary = String(finding.evidence_summary ?? "");
          return `<li><strong>${escapeHtml(source)}</strong> (${escapeHtml(t("report.confidence", { value: confidence }))}) - ${escapeHtml(evidenceSummary)}</li>`;
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

function renderWarningBanners(
  detail: RunDetail,
  params: Pick<HistoryTableViewParams, "escapeHtml">,
): string {
  const { escapeHtml } = params;
  const warnings = summarizeWarnings(detail.preview).concat(summarizeWarnings(detail.insights));
  const uniqueWarnings = warnings.filter(
    (warning, index) => warnings.findIndex((candidate) => candidate.code === warning.code) === index,
  );
  if (!uniqueWarnings.length) return "";
  return `
      <div class="history-warning-list">
        ${uniqueWarnings
          .map((warning) => {
            const detailText = warning.detail
              ? `<div class="history-warning-banner__detail">${escapeHtml(warning.detail)}</div>`
              : "";
            return `<div class="history-warning-banner history-warning-banner--${escapeHtml(warning.severity)}"><strong>${escapeHtml(warning.title)}</strong>${detailText}</div>`;
          })
          .join("")}
      </div>
    `;
}

function renderRunDetailsRow(
  run: HistoryEntry,
  detail: RunDetail,
  params: HistoryTableViewParams,
): string {
  const { escapeHtml, fmt, fmtTs, formatInt, t } = params;
  const summary = detail.preview;
  const runSummary = summary
    ? [
        `${t("report.run_id")}: ${run.run_id}`,
        `${t("history.summary_created")}: ${fmtTs(summary.start_time_utc as string)}`,
        `${t("history.summary_updated")}: ${fmtTs(run.end_time_utc ?? "")}`,
        `${t("history.summary_size")}: ${fmt(summary.duration_s as number, 1)} s`,
        `${t("history.summary_sensor_count")}: ${formatInt(summary.sensor_count_used as number)}`,
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
          ${renderPreviewHeatmap(summary, params)}
          ${renderPreviewStats(summary, params)}
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
            ${renderWarningBanners(detail, params)}
            ${renderInsightsBlock(detail, params)}
          </div>
        </td>
      </tr>
    `;
}

export function renderHistoryEmptyState(
  container: HTMLElement,
  text: string,
): void {
  container.innerHTML = renderTableEmptyRow(text, 4);
}

export function renderHistoryTable(
  container: HTMLElement,
  params: HistoryTableViewParams,
): void {
  const { runs, expandedRunId, runDetailsById, escapeHtml, fmtTs, formatInt, t, historyExportUrl } = params;
  const rows: string[] = [];
  for (const run of runs) {
    const detail = runDetailsById[run.run_id] ?? EMPTY_RUN_DETAIL;
    const pdfLabel = detail.pdfLoading ? t("history.generating_pdf") : t("history.generate_pdf");
    const rowError = detail.pdfError ? `<div class="history-inline-error">${escapeHtml(detail.pdfError)}</div>` : "";
    const isExpanded = expandedRunId === run.run_id;
    const toggleLabel = isExpanded ? t("history.collapse_details") : t("history.expand_details");
    const toggleTitle = isExpanded
      ? t("history.collapse_details_for_run", { runId: run.run_id })
      : t("history.expand_details_for_run", { runId: run.run_id });
    rows.push(`
        <tr class="history-row${isExpanded ? " history-row--expanded" : ""}" data-run-row="1" data-run="${escapeHtml(run.run_id)}">
          <td>
            <div class="history-row__run">
              <div class="history-row__run-id">${escapeHtml(run.run_id)}</div>
              <div class="history-row__detail-affordance">
                <button
                  type="button"
                  class="history-row__toggle${isExpanded ? " history-row__toggle--expanded" : ""}"
                  data-run-toggle="details"
                  data-run="${escapeHtml(run.run_id)}"
                  aria-expanded="${isExpanded ? "true" : "false"}"
                  aria-label="${escapeHtml(toggleTitle)}"
                  title="${escapeHtml(toggleTitle)}"
                >
                  <span class="history-row__toggle-icon" aria-hidden="true"></span>
                  <span>${escapeHtml(toggleLabel)}</span>
                </button>
                <span class="history-row__hint">${escapeHtml(t("history.preview_available"))}</span>
              </div>
            </div>
          </td>
          <td>${fmtTs(run.start_time_utc)}</td>
          <td class="numeric">${formatInt(run.sample_count)}</td>
          <td>
            <div class="table-actions">
              <button class="btn btn--success" data-run-action="download-pdf" data-run="${escapeHtml(run.run_id)}" ${detail.pdfLoading ? "disabled" : ""}>${escapeHtml(pdfLabel)}</button>
              <a class="btn btn--muted" href="${historyExportUrl(run.run_id)}" download="${escapeHtml(run.run_id)}.zip" data-run-action="download-raw" data-run="${escapeHtml(run.run_id)}">${escapeHtml(t("history.export"))}</a>
              <button class="btn btn--danger" data-run-action="delete-run" data-run="${escapeHtml(run.run_id)}">${escapeHtml(t("history.delete"))}</button>
            </div>
            ${rowError}
          </td>
        </tr>`);
    if (isExpanded) {
      rows.push(renderRunDetailsRow(run, detail, params));
    }
  }
  container.innerHTML = rows.join("");
}

export function getHistoryTableAction(
  target: EventTarget | null,
): HistoryTableAction | null {
  const actionElement = closestFromTarget<HTMLElement>(target, "[data-run-action]");
  if (!actionElement) {
    return null;
  }
  return {
    action: actionElement.getAttribute("data-run-action") ?? "",
    runId: actionElement.getAttribute("data-run"),
  };
}

export function getHistoryTableRowRunId(target: EventTarget | null): string | null {
  return closestFromTarget<HTMLElement>(target, 'tr[data-run-row="1"]')
    ?.getAttribute("data-run") ?? null;
}
