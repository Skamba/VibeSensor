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

type HistoryFindingTone = "success" | "warn" | "neutral";

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

function findingTone(finding: FindingPayload | null): HistoryFindingTone {
  const tone = String(finding?.confidence_tone ?? "").toLowerCase();
  if (tone === "success" || tone === "warn") {
    return tone;
  }
  return "neutral";
}

function findingSignatureText(
  finding: FindingPayload,
  params: Pick<HistoryTableViewParams, "fmt">,
): string {
  const raw = finding.frequency_hz_or_order;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return `${params.fmt(raw, 1)} Hz`;
  }
  const text = String(raw ?? "").trim();
  return text || "--";
}

function shouldShowNextStep(finding: FindingPayload | null): boolean {
  if (!finding) {
    return false;
  }
  if (findingTone(finding) === "success") {
    return true;
  }
  return typeof finding.confidence === "number" && Number.isFinite(finding.confidence) && finding.confidence >= 0.85;
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
  const { escapeHtml, t } = params;
  const findings = summarizeFindings(summary);
  const primary = findings[0];
  if (!primary) {
    return "";
  }
  const headline = primary.suspected_source || t("report.missing");
  const explanation = String(primary.evidence_summary ?? summary.most_likely_origin?.explanation ?? "");
  const location = findingLocationText(primary, summary, t);
  const speedBand = findingSpeedBandText(primary, summary, t);
  const signature = findingSignatureText(primary, params);
  const confidence = confidenceText(primary, params);
  const tone = findingTone(primary);
  const nextStep = shouldShowNextStep(primary) && location !== t("report.missing")
    ? t("history.findings_next_step", { location })
    : "";
  return `
      <div class="history-findings-overview">
        <div class="history-findings-overview__header">
          <div class="history-findings-overview__eyebrow">${escapeHtml(t("history.primary_diagnosis"))}</div>
        </div>
        <div class="history-diagnosis-card history-diagnosis-card--${tone}">
          <div class="history-diagnosis-card__header">
            <div class="history-diagnosis-card__copy">
              <div class="history-findings-overview__headline">${escapeHtml(headline)}</div>
              <div class="history-diagnosis-card__signature">${escapeHtml(signature)}</div>
            </div>
            <span class="history-diagnosis-card__confidence history-diagnosis-card__confidence--${tone}">${escapeHtml(confidence)}</span>
          </div>
          ${explanation ? `<p class="history-findings-overview__explanation">${escapeHtml(explanation)}</p>` : ""}
          <div class="history-findings-overview__chips">
            <div class="history-findings-chip">
              <span class="history-findings-chip__label">${escapeHtml(t("history.findings_location"))}</span>
              <strong>${escapeHtml(location)}</strong>
            </div>
            <div class="history-findings-chip">
              <span class="history-findings-chip__label">${escapeHtml(t("history.findings_speed_band"))}</span>
              <strong>${escapeHtml(speedBand)}</strong>
            </div>
            <div class="history-findings-chip">
              <span class="history-findings-chip__label">${escapeHtml(t("history.findings_signature"))}</span>
              <strong>${escapeHtml(signature)}</strong>
            </div>
          </div>
          ${nextStep
    ? `<div class="history-diagnosis-card__next-step"><span class="history-diagnosis-card__next-step-label">${escapeHtml(t("history.findings_next_step_label"))}</span><strong>${escapeHtml(nextStep)}</strong></div>`
    : ""}
        </div>
      </div>
    `;
}

function renderInsightsBlock(
  detail: RunDetail,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, t } = params;
  const findings = summarizeFindings(detail.insights);
  const loading = detail.insightsLoading;
  const loadedInsights = detail.insights;
  const findingsMarkup = loadedInsights && findings.length
    ? renderInsightsOverview(loadedInsights, params)
    : `<ul class="history-findings-list history-findings-list--secondary"><li class="history-finding-card history-finding-card--empty">${escapeHtml(t("report.no_findings_for_run"))}</li></ul>`;
  return `
      <div class="history-insights-block">
        <div class="history-panel-header">
          <div class="history-panel-header__eyebrow">${escapeHtml(t("history.findings_title"))}</div>
          ${detail.insights ? `<div class="history-panel-header__subtitle">${escapeHtml(t("history.findings_ready"))}</div>` : ""}
        </div>
        ${detail.insights
    ? findingsMarkup
    : `<div class="history-panel-state">${escapeHtml(loading ? t("history.loading_insights") : t("history.findings_pending"))}</div>`}
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
  const insightsCtaLabel = detail.insights ? t("history.reload_insights") : t("history.load_insights");
  const insightsError = detail.insightsError
    ? `<span class="history-inline-error">${escapeHtml(detail.insightsError)}</span>`
    : "";
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
  if (detail.previewLoading) {
    heatmapMarkup = `
      <div class="mini-car-wrap">
        <div class="mini-car-title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        <p class="subtle">${escapeHtml(t("history.loading_preview"))}</p>
      </div>
    `;
  } else if (detail.previewError) {
    heatmapMarkup = `
      <div class="mini-car-wrap">
        <div class="mini-car-title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        <p class="history-inline-error">${escapeHtml(detail.previewError)}</p>
      </div>
    `;
  } else if (summary) {
    heatmapMarkup = renderPreviewHeatmap(summary, params);
  } else {
    heatmapMarkup = `
      <div class="mini-car-wrap">
        <div class="mini-car-title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        <p class="subtle">${escapeHtml(t("history.preview_unavailable"))}</p>
      </div>
    `;
  }
  return `
      <tr class="history-details-row">
        <td colspan="4">
          <div class="history-details-card">
            <div class="history-details-header">
              <div class="history-details-header__copy">
                <div class="history-details-header__eyebrow">${escapeHtml(t("history.details_title"))}</div>
                <div class="history-details-header__title">${escapeHtml(run.run_id)}</div>
                ${runSummary ? `<div class="history-run-summary">${escapeHtml(runSummary)}</div>` : ""}
              </div>
              <div class="history-details-header__actions">
                <button class="btn btn--primary" data-run-action="load-insights" ${detail.insightsLoading ? "disabled" : ""}>${escapeHtml(detail.insightsLoading ? t("history.loading_insights") : insightsCtaLabel)}</button>
                ${insightsError}
              </div>
            </div>
            ${renderWarningBanners(detail, params)}
            <div class="history-results-layout">
              ${renderInsightsBlock(detail, params)}
              <div class="history-evidence-column">
                <div class="history-evidence-panel">
                  ${heatmapMarkup}
                </div>
              </div>
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
                  <span class="history-row__toggle-copy">
                    <span class="history-row__toggle-title">${escapeHtml(toggleLabel)}</span>
                    <span class="history-row__toggle-hint">${escapeHtml(t("history.preview_available"))}</span>
                  </span>
                </button>
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
