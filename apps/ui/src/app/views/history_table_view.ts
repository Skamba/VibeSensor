import type {
  FindingPayload,
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import { HISTORY_HEATMAP_POSITIONS } from "../../config";
import type { RunDetail } from "../ui_app_state";
import { heatColor, normalizeUnit } from "../features/heat_utils";
import {
  closestFromTarget,
  renderInlineStatePanel,
  renderTableEmptyRow,
} from "./dom_helpers";

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

function humanizeHeatmapLocationKey(key: string): string {
  return key
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function renderPreviewHeatmap(
  summary: HistoryInsightsPayload,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, fmt, t } = params;
  const statsRows = sensorIntensityRows(summary);
  const metricByLocation: Record<string, number> = {};
  const labelByLocation: Record<string, string> = {};
  for (const row of statsRows) {
    const key = normalizeLogLocationKey(row.location);
    const metric = metricFromLocationStat(row);
    const label = String(row.location ?? "").trim();
    if (key && typeof metric === "number" && Number.isFinite(metric)) {
      metricByLocation[key] = metric;
    }
    if (key && label) {
      labelByLocation[key] = label;
    }
  }
  const values = Object.values(metricByLocation).filter((value) => typeof value === "number");
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const knownPositionKeys = new Set<string>(HISTORY_HEATMAP_POSITIONS.map((point) => point.key));
  const strongestValue = values.length ? Math.max(...values) : null;
  const zones = HISTORY_HEATMAP_POSITIONS
    .map((point) => {
      const value = metricByLocation[point.key];
      const label = labelByLocation[point.key] || humanizeHeatmapLocationKey(point.key);
      const hasValue = typeof value === "number" && Number.isFinite(value);
      if (!hasValue || min === null || max === null) {
        return `
          <div
            class="history-heatmap__zone history-heatmap__zone--empty"
            data-location-key="${escapeHtml(point.key)}"
            style="grid-area:${point.area}"
            title="${escapeHtml(label)}"
          >
            <div class="history-heatmap__zone-label">${escapeHtml(label)}</div>
            <div class="history-heatmap__zone-value history-heatmap__zone-value--empty">${escapeHtml(t("report.missing"))}</div>
            <div class="history-heatmap__zone-meter" aria-hidden="true"></div>
          </div>
        `;
      }
      const norm = normalizeUnit(value, min, max);
      const fill = heatColor(norm);
      const valueLabel = `${fmt(value, 1)} dB`;
      const isStrongest = strongestValue !== null && value === strongestValue;
      return `
        <div
          class="history-heatmap__zone${isStrongest ? " history-heatmap__zone--strongest" : ""}"
          data-location-key="${escapeHtml(point.key)}"
          style="grid-area:${point.area};--history-heatmap-accent:${fill};--history-heatmap-fill:${Math.round(norm * 100)}%;"
          title="${escapeHtml(label)}: ${escapeHtml(valueLabel)}"
        >
          <div class="history-heatmap__zone-label">${escapeHtml(label)}</div>
          <div class="history-heatmap__zone-value">${escapeHtml(valueLabel)}</div>
          <div class="history-heatmap__zone-meter" aria-hidden="true">
            <span class="history-heatmap__zone-meter-fill"></span>
          </div>
        </div>
      `;
    })
    .join("");
  const unmappedSummary = Object.keys(metricByLocation)
    .filter((key) => !knownPositionKeys.has(key))
    .map((key) => {
      const label = labelByLocation[key] || humanizeHeatmapLocationKey(key);
      const value = metricByLocation[key];
      return `<div class="history-heatmap__extra-chip">${escapeHtml(label)} · ${escapeHtml(`${fmt(value, 1)} dB`)}</div>`;
    })
    .join("");
  const extrasMarkup = unmappedSummary
    ? `<div class="history-heatmap__extras">${unmappedSummary}</div>`
    : "";
  return `
      <div class="history-heatmap">
        <div class="history-heatmap__header">
          <div class="history-heatmap__title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        </div>
        <div class="history-heatmap__grid">${zones}</div>
        ${extrasMarkup}
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

function historyRowCarName(
  run: HistoryEntry,
  t: HistoryTableViewParams["t"],
): string {
  const value = typeof run.car_name === "string" ? run.car_name.trim() : "";
  return value || t("history.car_missing");
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
  return `<div class="history-row__summary-chips">${chips.join("")}</div>`;
}

function renderCollapsedRowActions(
  runId: string,
  detail: RunDetail,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "t">,
): string {
  const { escapeHtml, t } = params;
  const pdfLabel = detail.pdfLoading ? t("history.generating_pdf") : t("history.generate_pdf");
  return `
      <div class="table-actions history-row__actions">
        <button class="btn" data-run-action="download-pdf" data-run="${escapeHtml(runId)}" ${detail.pdfLoading ? "disabled" : ""}>${escapeHtml(pdfLabel)}</button>
      </div>
    `;
}

function renderDetailManagementFooter(
  runId: string,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "historyExportUrl" | "t">,
): string {
  const { escapeHtml, historyExportUrl, t } = params;
  return `
      <div class="history-details-footer">
        <div class="history-details-footer__copy">
          <div class="history-details-footer__eyebrow">${escapeHtml(t("history.run_actions_title"))}</div>
          <div class="history-details-footer__body">${escapeHtml(t("history.run_actions_body"))}</div>
        </div>
        <div class="history-details-footer__actions">
          <a class="btn btn--muted" href="${historyExportUrl(runId)}" download="${escapeHtml(runId)}.zip" data-run-action="download-raw" data-run="${escapeHtml(runId)}">${escapeHtml(t("history.export"))}</a>
          <button class="btn btn--danger-quiet" data-run-action="delete-run" data-run="${escapeHtml(runId)}">${escapeHtml(t("history.delete"))}</button>
        </div>
      </div>
    `;
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
  const findingCount = summary.findings?.length ?? findings.length;
  const nextStep = shouldShowNextStep(primary) && location !== t("report.missing")
    ? t("history.findings_next_step", { location })
    : "";
  return `
      <div class="history-findings-overview">
        <div class="history-findings-overview__header">
          <div class="history-findings-overview__eyebrow">${escapeHtml(t("history.primary_diagnosis"))}</div>
          <div class="history-findings-overview__count">${escapeHtml(t("history.findings_loaded", { count: findingCount }))}</div>
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

function renderSecondaryFindingCard(
  finding: FindingPayload,
  summary: HistoryInsightsPayload,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, t } = params;
  const source = finding.suspected_source || t("report.missing");
  const confidence = confidenceText(finding, params);
  const location = findingLocationText(finding, summary, t);
  const speedBand = findingSpeedBandText(finding, summary, t);
  const signature = findingSignatureText(finding, params);
  const evidenceSummary = String(finding.evidence_summary ?? "");
  const tone = findingTone(finding);
  return `
      <li class="history-finding-card history-finding-card--secondary history-finding-card--${tone}">
        <div class="history-finding-card__header">
          <div class="history-finding-card__title-group">
            <strong class="history-finding-card__title">${escapeHtml(source)}</strong>
            <span class="history-finding-card__signal">${escapeHtml(signature)}</span>
          </div>
          <span class="history-finding-card__confidence history-finding-card__confidence--${tone}">${escapeHtml(confidence)}</span>
        </div>
        <div class="history-finding-card__meta">
          <div class="history-finding-card__meta-item">
            <span class="history-finding-card__label">${escapeHtml(t("history.findings_location"))}</span>
            <strong>${escapeHtml(location)}</strong>
          </div>
          <div class="history-finding-card__meta-item">
            <span class="history-finding-card__label">${escapeHtml(t("history.findings_speed_band"))}</span>
            <strong>${escapeHtml(speedBand)}</strong>
          </div>
        </div>
        <p class="history-finding-card__summary">${escapeHtml(evidenceSummary)}</p>
      </li>`;
}

function renderInsightsBlock(
  detail: RunDetail,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "fmt" | "t">,
): string {
  const { escapeHtml, t } = params;
  const findings = summarizeFindings(detail.insights);
  const loading = detail.insightsLoading;
  const loadedInsights = detail.insights;
  const secondaryFindings = loadedInsights ? findings.slice(1) : [];
  const visibleSecondaryFindings = secondaryFindings.slice(0, 2);
  const hiddenSecondaryFindings = secondaryFindings.slice(2);
  const findingsMarkup = loadedInsights && findings.length
    ? `
        ${renderInsightsOverview(loadedInsights, params)}
        ${secondaryFindings.length
      ? `
            <div class="history-secondary-findings">
              <div class="history-secondary-findings__title">${escapeHtml(t("history.secondary_candidates_title"))}</div>
              <ul class="history-findings-list history-findings-list--secondary">
                ${visibleSecondaryFindings.map((finding) => renderSecondaryFindingCard(finding, loadedInsights, params)).join("")}
              </ul>
              ${hiddenSecondaryFindings.length
        ? `
                  <details class="history-secondary-findings__more">
                    <summary>${escapeHtml(t("history.show_more_findings", { count: hiddenSecondaryFindings.length }))}</summary>
                    <ul class="history-findings-list history-findings-list--secondary">
                      ${hiddenSecondaryFindings.map((finding) => renderSecondaryFindingCard(finding, loadedInsights, params)).join("")}
                    </ul>
                  </details>
                `
        : ""}
            </div>
          `
      : ""}
      `
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
      <div class="history-heatmap">
        <div class="history-heatmap__header">
          <div class="history-heatmap__title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        </div>
        <p class="subtle">${escapeHtml(t("history.loading_preview"))}</p>
      </div>
    `;
  } else if (detail.previewError) {
    heatmapMarkup = `
      <div class="history-heatmap">
        <div class="history-heatmap__header">
          <div class="history-heatmap__title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        </div>
        <p class="history-inline-error">${escapeHtml(detail.previewError)}</p>
      </div>
    `;
  } else if (summary) {
    heatmapMarkup = renderPreviewHeatmap(summary, params);
  } else {
    heatmapMarkup = `
      <div class="history-heatmap">
        <div class="history-heatmap__header">
          <div class="history-heatmap__title">${escapeHtml(t("history.preview_heatmap_title"))}</div>
        </div>
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
            ${renderDetailManagementFooter(run.run_id, params)}
          </div>
        </td>
      </tr>
    `;
}

export function renderHistoryEmptyState(
  container: HTMLElement,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "t">,
): void {
  const { escapeHtml, t } = params;
  container.innerHTML = renderTableEmptyRow(
    renderInlineStatePanel({
      titleHtml: escapeHtml(t("history.empty.title")),
      bodyHtml: escapeHtml(t("history.empty.body")),
      detailHtml: escapeHtml(t("history.empty.detail")),
      action: {
        action: "open-live",
        labelHtml: escapeHtml(t("history.empty.action")),
      },
    }),
    4,
  );
}

export function renderHistoryTable(
  container: HTMLElement,
  params: HistoryTableViewParams,
): void {
  const { runs, expandedRunId, runDetailsById, escapeHtml, fmtTs, formatInt, t } = params;
  const rows: string[] = [];
  for (const run of runs) {
    const detail = runDetailsById[run.run_id] ?? EMPTY_RUN_DETAIL;
    const rowError = detail.pdfError ? `<div class="history-inline-error">${escapeHtml(detail.pdfError)}</div>` : "";
    const isExpanded = expandedRunId === run.run_id;
    const toggleLabel = isExpanded ? t("history.close_diagnosis") : t("history.open_diagnosis");
    const toggleTitle = isExpanded
      ? t("history.close_diagnosis_for_run", { runId: run.run_id })
      : t("history.open_diagnosis_for_run", { runId: run.run_id });
    const startedAtText = fmtTs(run.start_time_utc);
    const carName = historyRowCarName(run, t);
    rows.push(`
        <tr class="history-row${isExpanded ? " history-row--expanded" : ""}" data-run-row="1" data-run="${escapeHtml(run.run_id)}">
          <td class="history-row__primary-cell">
            <div class="history-row__run">
              <div class="history-row__run-heading">
                <div class="history-row__car-context">
                  <span class="history-row__car-label">${escapeHtml(t("history.car_label"))}</span>
                  <span class="history-row__car-name">${escapeHtml(carName)}</span>
                </div>
                <div class="history-row__run-id">${escapeHtml(run.run_id)}</div>
              </div>
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
          <td class="history-row__meta-cell history-row__meta-cell--started">
            <span class="history-row__meta-label">${escapeHtml(t("history.table.updated"))}</span>
            <span class="history-row__meta-value">${escapeHtml(startedAtText)}</span>
          </td>
          <td class="history-row__meta-cell history-row__meta-cell--samples numeric">
            <span class="history-row__meta-label">${escapeHtml(t("history.table.size"))}</span>
            <span class="history-row__meta-value">${escapeHtml(formatInt(run.sample_count))}</span>
          </td>
          <td class="history-row__meta-cell history-row__meta-cell--actions">
            <span class="history-row__meta-label">${escapeHtml(t("history.quick_report"))}</span>
            ${renderCollapsedRowActions(run.run_id, detail, params)}
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
