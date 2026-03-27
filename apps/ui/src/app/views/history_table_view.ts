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

const VISIBLE_FINDING_LIMIT = 5;

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

type HistoryRowStatusBadge = {
  label: string;
  variant: "ok" | "warn" | "bad" | "muted";
};

function summarizeFindings(summary: HistoryInsightsPayload | null): FindingPayload[] {
  return summary?.findings?.slice(0, VISIBLE_FINDING_LIMIT) ?? [];
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

function confidenceText(
  finding: FindingPayload,
  params: Pick<HistoryTableViewParams, "fmt" | "t">,
): string {
  const { fmt, t } = params;
  const value = typeof finding.confidence_pct === "string" && finding.confidence_pct.trim()
    ? finding.confidence_pct
    : typeof finding.confidence === "number" && Number.isFinite(finding.confidence)
      ? fmt(finding.confidence, 2)
      : "--";
  return t("report.confidence", { value });
}

function findingLocationText(
  finding: FindingPayload,
  summary: HistoryInsightsPayload | null,
  t: HistoryTableViewParams["t"],
): string {
  return finding.strongest_location
    || summary?.most_likely_origin?.location
    || t("report.missing");
}

function findingSpeedBandText(
  finding: FindingPayload,
  summary: HistoryInsightsPayload | null,
  t: HistoryTableViewParams["t"],
): string {
  return finding.strongest_speed_band
    || summary?.most_likely_origin?.speed_band
    || t("report.missing");
}

function historyRowSummary(detail: RunDetail): HistoryInsightsPayload | null {
  return detail.insights ?? detail.preview;
}

function historyRowStatusBadge(
  run: HistoryEntry,
  t: HistoryTableViewParams["t"],
): HistoryRowStatusBadge {
  switch (run.status) {
    case "complete":
      return { label: t("history.row_status.complete"), variant: "ok" };
    case "analyzing":
      return { label: t("history.row_status.analyzing"), variant: "warn" };
    case "recording":
      return { label: t("history.row_status.recording"), variant: "warn" };
    case "error":
      return { label: t("history.row_status.error"), variant: "bad" };
    default:
      return { label: run.status || t("report.missing"), variant: "muted" };
  }
}

function historyRowDurationSeconds(
  run: HistoryEntry,
  detail: RunDetail,
): number | null {
  const summary = historyRowSummary(detail);
  const summaryDuration = Number(summary?.duration_s);
  if (Number.isFinite(summaryDuration) && summaryDuration >= 0) {
    return summaryDuration;
  }
  const startMs = Date.parse(run.start_time_utc);
  const endIso = run.end_time_utc ?? summary?.end_time_utc ?? null;
  const endMs = endIso ? Date.parse(endIso) : Number.NaN;
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) {
    return null;
  }
  return (endMs - startMs) / 1000;
}

function renderCollapsedRowSummary(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "formatInt" | "t">,
): string {
  const { escapeHtml, fmt, formatInt, t } = params;
  const summary = historyRowSummary(detail);
  const primaryFinding = summarizeFindings(summary)[0] ?? null;
  const statusBadge = historyRowStatusBadge(run, t);
  const chips: string[] = [
    `<span class="history-row__summary-chip history-row__summary-chip--${statusBadge.variant}">${escapeHtml(statusBadge.label)}</span>`,
  ];
  const durationSeconds = historyRowDurationSeconds(run, detail);
  if (durationSeconds !== null) {
    chips.push(
      `<span class="history-row__summary-chip">${escapeHtml(t("history.summary_size"))}: ${escapeHtml(fmt(durationSeconds, 1))} s</span>`,
    );
  }
  const sensorCount = Number(summary?.sensor_count_used);
  if (Number.isFinite(sensorCount) && sensorCount > 0) {
    chips.push(
      `<span class="history-row__summary-chip">${escapeHtml(t("history.summary_sensor_count"))}: ${escapeHtml(formatInt(sensorCount))}</span>`,
    );
  }
  const source = summary?.most_likely_origin?.suspected_source || primaryFinding?.suspected_source || "";
  if (source) {
    chips.push(
      `<span class="history-row__summary-chip history-row__summary-chip--source">${escapeHtml(source)}</span>`,
    );
  }
  if (primaryFinding) {
    chips.push(`<span class="history-row__summary-chip">${escapeHtml(confidenceText(primaryFinding, params))}</span>`);
  } else if (run.status === "complete" && detail.previewLoading) {
    chips.push(
      `<span class="history-row__summary-chip history-row__summary-chip--muted">${escapeHtml(t("history.row_summary_loading"))}</span>`,
    );
  } else if (run.status === "complete" && summary) {
    chips.push(
      `<span class="history-row__summary-chip history-row__summary-chip--muted">${escapeHtml(t("history.row_no_findings"))}</span>`,
    );
  }
  if (run.status === "error" && run.error_message) {
    chips.push(
      `<span class="history-row__summary-chip history-row__summary-chip--muted">${escapeHtml(run.error_message)}</span>`,
    );
  }
  return `<div class="history-row__summary-chips">${chips.join("")}</div>`;
}

function renderInsightsOverview(
  summary: HistoryInsightsPayload,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, fmt, t } = params;
  const findings = summarizeFindings(summary);
  const primary = findings[0];
  const origin = summary.most_likely_origin;
  const headline = origin?.suspected_source || primary?.suspected_source || t("report.missing");
  const explanation = String(origin?.explanation ?? primary?.evidence_summary ?? "");
  const location = primary ? findingLocationText(primary, summary, t) : origin?.location || t("report.missing");
  const speedBand = primary ? findingSpeedBandText(primary, summary, t) : origin?.speed_band || t("report.missing");
  const confidence = primary
    ? confidenceText(primary, params)
    : t("report.confidence", { value: "--" });
  const findingCount = summary.findings?.length ?? findings.length;
  return `
      <div class="history-findings-overview">
        <div class="history-findings-overview__header">
          <div class="history-findings-overview__eyebrow">${escapeHtml(t("history.findings_title"))}</div>
          <div class="history-findings-overview__count">${escapeHtml(t("history.findings_loaded", { count: findingCount }))}</div>
        </div>
        <div class="history-findings-overview__headline">${escapeHtml(headline)}</div>
        ${explanation ? `<p class="history-findings-overview__explanation">${escapeHtml(explanation)}</p>` : ""}
        <div class="history-findings-overview__chips">
          <div class="history-findings-chip">
            <span class="history-findings-chip__label">${escapeHtml(t("history.findings_origin"))}</span>
            <strong>${escapeHtml(headline)}</strong>
          </div>
          <div class="history-findings-chip">
            <span class="history-findings-chip__label">${escapeHtml(t("history.findings_location"))}</span>
            <strong>${escapeHtml(location)}</strong>
          </div>
          <div class="history-findings-chip">
            <span class="history-findings-chip__label">${escapeHtml(t("history.findings_speed_band"))}</span>
            <strong>${escapeHtml(speedBand)}</strong>
          </div>
          <div class="history-findings-chip">
            <span class="history-findings-chip__label">${escapeHtml(t("history.findings_confidence"))}</span>
            <strong>${escapeHtml(confidence)}</strong>
          </div>
        </div>
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
          const confidence = confidenceText(finding, params);
          const location = findingLocationText(finding, detail.insights, t);
          const speedBand = findingSpeedBandText(finding, detail.insights, t);
          const evidenceSummary = String(finding.evidence_summary ?? "");
          return `
            <li class="history-finding-card">
              <div class="history-finding-card__header">
                <strong class="history-finding-card__title">${escapeHtml(source)}</strong>
                <span class="history-finding-card__confidence">${escapeHtml(confidence)}</span>
              </div>
              <div class="history-finding-card__meta">
                <span>${escapeHtml(t("history.findings_location"))}: ${escapeHtml(location)}</span>
                <span>${escapeHtml(t("history.findings_speed_band"))}: ${escapeHtml(speedBand)}</span>
              </div>
              <p class="history-finding-card__summary">${escapeHtml(evidenceSummary)}</p>
            </li>`;
        })
        .join("")
    : `<li class="history-finding-card history-finding-card--empty">${escapeHtml(t("report.no_findings_for_run"))}</li>`;
  return `
      <div class="history-insights-block">
        <div class="history-insights-actions">
          <div class="history-insights-actions__copy">
            <div class="history-insights-actions__title">${escapeHtml(t("history.findings_title"))}</div>
            <div class="history-insights-actions__subtitle">${escapeHtml(detail.insights ? t("history.findings_ready") : t("history.findings_pending"))}</div>
          </div>
          <button class="btn btn--primary" data-run-action="load-insights" ${loading ? "disabled" : ""}>${escapeHtml(loading ? t("history.loading_insights") : ctaLabel)}</button>
          ${detail.insightsError ? `<span class="history-inline-error">${escapeHtml(detail.insightsError)}</span>` : ""}
        </div>
        ${detail.insights ? renderInsightsOverview(detail.insights, params) : ""}
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
  let heatmapMarkup = "";
  let statsMarkup = "";
  if (detail.previewLoading) {
    heatmapMarkup = `<p class="subtle">${escapeHtml(t("history.loading_preview"))}</p>`;
    statsMarkup = `<p class="subtle">${escapeHtml(t("history.loading_preview"))}</p>`;
  } else if (detail.previewError) {
    heatmapMarkup = `<p class="history-inline-error">${escapeHtml(detail.previewError)}</p>`;
    statsMarkup = `<p class="history-inline-error">${escapeHtml(detail.previewError)}</p>`;
  } else if (summary) {
    heatmapMarkup = renderPreviewHeatmap(summary, params);
    statsMarkup = renderPreviewStats(summary, params);
  } else {
    heatmapMarkup = `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
    statsMarkup = `<p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>`;
  }
  return `
      <tr class="history-details-row">
        <td colspan="4">
          <div class="history-details-card">
            ${runSummary ? `<div class="history-run-summary">${escapeHtml(runSummary)}</div>` : ""}
            ${renderWarningBanners(detail, params)}
            <div class="history-results-layout">
              ${renderInsightsBlock(detail, params)}
              <div class="history-evidence-panel">
                ${heatmapMarkup}
              </div>
            </div>
            <div class="history-details-secondary">
              ${statsMarkup}
            </div>
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
              ${renderCollapsedRowSummary(run, detail, params)}
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
