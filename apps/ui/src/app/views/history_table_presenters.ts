import type {
  FindingPayload,
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import { HISTORY_HEATMAP_POSITIONS } from "../../config";
import type { RunDetail } from "../ui_app_state";
import { heatColor, normalizeUnit } from "../features/heat_utils";
import type {
  HistoryCollapsedActionViewModel,
  HistoryDetailsViewModel,
  HistoryFindingTone,
  HistoryHeatmapViewModel,
  HistoryHeatmapZoneViewModel,
  HistoryInsightsViewModel,
  HistoryPrimaryFindingViewModel,
  HistoryRowViewModel,
  HistorySecondaryFindingViewModel,
  HistorySummaryChipTone,
  HistorySummaryChipViewModel,
  HistoryWarningBannerViewModel,
} from "./history_table_models";
import type { HistoryTableViewParams } from "./history_table_view";

type LocationIntensityRow = HistoryInsightsPayload["sensor_intensity_by_location"][number];
type PresenterParams = Pick<
  HistoryTableViewParams,
  "expandedRunId" | "fmt" | "fmtTs" | "formatInt" | "runDetailsById" | "runs" | "t"
>;

const VISIBLE_FINDING_LIMIT = 5;
const SOURCE_LABEL_KEYS: Record<string, string> = {
  wheel_tire: "history.source.wheel_tire",
  driveline: "history.source.driveline",
  engine: "history.source.engine",
  body_resonance: "history.source.body_resonance",
  transient_impact: "history.source.transient_impact",
  baseline_noise: "history.source.baseline_noise",
  unknown_resonance: "history.source.unknown_resonance",
};

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

type HistoryRowStatusBadge = {
  label: string;
  tone: Extract<HistorySummaryChipTone, "ok" | "warn" | "bad" | "muted">;
};

type HistoryRowSummary = {
  headline: string | null;
  meta: string | null;
};

function summarizeFindings(summary: HistoryInsightsPayload | null): FindingPayload[] {
  return summary?.findings?.slice(0, VISIBLE_FINDING_LIMIT) ?? [];
}

function summarizeWarnings(payload: HistoryInsightsPayload | null): HistoryInsightWarningPayload[] {
  return payload?.warnings ?? [];
}

function normalizedSourceKey(source: unknown): string {
  return String(source ?? "").trim().toLowerCase();
}

function humanizeSourceFallback(sourceKey: string): string {
  return sourceKey
    .split(/[_-]+/g)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatSourceLabel(source: unknown, t: PresenterParams["t"]): string {
  const raw = String(source ?? "").trim();
  const key = normalizedSourceKey(source);
  if (!key) {
    return t("report.missing");
  }
  const labelKey = SOURCE_LABEL_KEYS[key];
  if (labelKey) {
    return t(labelKey);
  }
  return /^[a-z0-9_-]+$/.test(raw) ? humanizeSourceFallback(key) : raw;
}

function isInconclusiveSource(source: unknown): boolean {
  const key = normalizedSourceKey(source);
  return key === "" || key === "unknown_resonance" || key === "baseline_noise";
}

function isInconclusiveFinding(finding: FindingPayload | null): boolean {
  return finding !== null && isInconclusiveSource(finding.suspected_source);
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

function confidenceText(
  finding: FindingPayload,
  params: Pick<PresenterParams, "fmt" | "t">,
): string {
  const { fmt, t } = params;
  const value =
    typeof finding.confidence_pct === "string" && finding.confidence_pct.trim()
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
  params: Pick<PresenterParams, "fmt">,
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
  if (isInconclusiveFinding(finding)) {
    return false;
  }
  if (findingTone(finding) === "success") {
    return true;
  }
  return (
    typeof finding.confidence === "number"
    && Number.isFinite(finding.confidence)
    && finding.confidence >= 0.85
  );
}

function findingLocationText(
  finding: FindingPayload,
  summary: HistoryInsightsPayload | null,
  t: PresenterParams["t"],
): string {
  return finding.strongest_location || summary?.most_likely_origin?.location || t("report.missing");
}

function findingSpeedBandText(
  finding: FindingPayload,
  summary: HistoryInsightsPayload | null,
  t: PresenterParams["t"],
): string {
  return (
    finding.strongest_speed_band
    || summary?.most_likely_origin?.speed_band
    || t("report.missing")
  );
}

function historyRowSummary(detail: RunDetail): HistoryInsightsPayload | null {
  return detail.insights ?? detail.preview;
}

function historyRowStatusBadge(
  run: HistoryEntry,
  detail: RunDetail,
  t: PresenterParams["t"],
): HistoryRowStatusBadge {
  const summary = historyRowSummary(detail);
  switch (run.status) {
    case "complete":
      return { label: t("history.row_status.complete"), tone: "ok" };
    case "analyzing":
      return summary !== null
        ? { label: t("history.row_status.preview_ready"), tone: "ok" }
        : { label: t("history.row_status.analyzing"), tone: "warn" };
    case "recording":
      return { label: t("history.row_status.recording"), tone: "warn" };
    case "error":
      return { label: t("history.row_status.error"), tone: "bad" };
    default:
      return { label: run.status || t("report.missing"), tone: "muted" };
  }
}

function historyRowDurationSeconds(run: HistoryEntry, detail: RunDetail): number | null {
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

function historyRowCarName(run: HistoryEntry, t: PresenterParams["t"]): string {
  const value = typeof run.car_name === "string" ? run.car_name.trim() : "";
  return value || t("history.car_missing");
}

function historyRunDisplayTitle(run: HistoryEntry, t: PresenterParams["t"]): string {
  const carName = historyRowCarName(run, t);
  return carName === t("history.car_missing") ? run.run_id : carName;
}

function buildSummaryChips(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<PresenterParams, "t">,
): HistorySummaryChipViewModel[] {
  const { t } = params;
  const statusBadge = historyRowStatusBadge(run, detail, t);
  const chips: HistorySummaryChipViewModel[] = [
    { text: statusBadge.label, tone: statusBadge.tone },
  ];
  if (run.status === "error" && run.error_message) {
    chips.push({ text: run.error_message, tone: "muted" });
  }
  return chips;
}

function buildRowSummary(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<PresenterParams, "fmt" | "formatInt" | "t">,
): HistoryRowSummary {
  const { fmt, formatInt, t } = params;
  const summary = historyRowSummary(detail);
  const primaryFinding = summarizeFindings(summary)[0] ?? null;
  const source = summary?.most_likely_origin?.suspected_source || primaryFinding?.suspected_source || "";
  const sourceLabel =
    primaryFinding && isInconclusiveFinding(primaryFinding)
      ? t("history.row_source_inconclusive")
      : source
        ? formatSourceLabel(source, t)
        : "";
  const headline = sourceLabel
    || (run.status === "complete" && (detail.previewLoading || detail.insightsLoading || summary === null)
      ? t("history.row_summary_loading")
      : run.status === "complete" && summary
        ? t("history.row_no_findings")
        : historyRowStatusBadge(run, detail, t).label);
  const metaParts: string[] = [];
  if (primaryFinding) {
    metaParts.push(confidenceText(primaryFinding, params));
  }
  const durationSeconds = historyRowDurationSeconds(run, detail);
  if (durationSeconds !== null) {
    metaParts.push(`${t("history.summary_size")}: ${fmt(durationSeconds, 1)} s`);
  }
  const sensorCount = Number(summary?.sensor_count_used);
  if (Number.isFinite(sensorCount) && sensorCount > 0) {
    metaParts.push(`${t("history.summary_sensor_count")}: ${formatInt(sensorCount)}`);
  }
  if (metaParts.length === 0 && run.status === "error" && run.error_message) {
    metaParts.push(run.error_message);
  }
  return {
    headline,
    meta: metaParts.length ? metaParts.join(" · ") : null,
  };
}

function buildCollapsedAction(
  run: HistoryEntry,
  detail: RunDetail,
  t: PresenterParams["t"],
): HistoryCollapsedActionViewModel {
  const reportReady = run.status === "complete";
  if (!reportReady) {
    return {
      hintText: t("history.quick_report_pending"),
      pdfLabel: null,
      pdfLoading: false,
    };
  }
  return {
    hintText: null,
    pdfLabel: detail.pdfLoading ? t("history.generating_pdf") : t("history.generate_pdf"),
    pdfLoading: detail.pdfLoading,
  };
}

function buildHeatmap(
  summary: HistoryInsightsPayload | null,
  params: Pick<PresenterParams, "fmt" | "t">,
  options: {
    stateMessage?: string | null;
    stateTone?: "subtle" | "error" | null;
  } = {},
): HistoryHeatmapViewModel {
  const { fmt, t } = params;
  const { stateMessage = null, stateTone = null } = options;
  const title = t("history.preview_heatmap_title");
  if (summary === null) {
    return {
      title,
      stateMessage,
      stateTone,
      zones: [],
      extras: [],
    };
  }
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
  const zones: HistoryHeatmapZoneViewModel[] = HISTORY_HEATMAP_POSITIONS.map((point) => {
    const value = metricByLocation[point.key];
    const label = labelByLocation[point.key] || humanizeHeatmapLocationKey(point.key);
    const hasValue = typeof value === "number" && Number.isFinite(value);
    if (!hasValue || min === null || max === null) {
      return {
        key: point.key,
        label,
        gridArea: point.area,
        valueLabel: t("report.missing"),
        strongest: false,
        accentColor: null,
        fillPercent: null,
      };
    }
    const norm = normalizeUnit(value, min, max);
    return {
      key: point.key,
      label,
      gridArea: point.area,
      valueLabel: `${fmt(value, 1)} dB`,
      strongest: strongestValue !== null && value === strongestValue,
      accentColor: heatColor(norm),
      fillPercent: Math.round(norm * 100),
    };
  });
  const extras = Object.keys(metricByLocation)
    .filter((key) => !knownPositionKeys.has(key))
    .map((key) => {
      const label = labelByLocation[key] || humanizeHeatmapLocationKey(key);
      return `${label} · ${fmt(metricByLocation[key] ?? 0, 1)} dB`;
    });
  return {
    title,
    stateMessage: null,
    stateTone: null,
    zones,
    extras,
  };
}

function buildPrimaryFinding(
  summary: HistoryInsightsPayload,
  params: Pick<PresenterParams, "fmt" | "t">,
): HistoryPrimaryFindingViewModel | null {
  const { t } = params;
  const findings = summarizeFindings(summary);
  const primary = findings[0];
  if (!primary) {
    return null;
  }
  const inconclusive = isInconclusiveFinding(primary);
  const location = findingLocationText(primary, summary, t);
  const signature = findingSignatureText(primary, params);
  const nextStep =
    inconclusive
      ? t("history.inconclusive_next_step")
      : shouldShowNextStep(primary) && location !== t("report.missing")
        ? t("history.findings_next_step", { location })
        : null;
  return {
    eyebrow: inconclusive ? t("history.capture_verdict") : t("history.primary_diagnosis"),
    headline: inconclusive
      ? t("history.inconclusive_title")
      : formatSourceLabel(primary.suspected_source, t),
    signature,
    confidence: confidenceText(primary, params),
    tone: findingTone(primary),
    explanation: String(
      primary.evidence_summary
        ?? summary.most_likely_origin?.explanation
        ?? (inconclusive ? t("history.inconclusive_body") : ""),
    ),
    chips: [
      { label: t("history.findings_location"), value: location },
      {
        label: t("history.findings_speed_band"),
        value: findingSpeedBandText(primary, summary, t),
      },
      { label: t("history.findings_signature"), value: signature },
    ],
    nextStepLabel: nextStep
      ? inconclusive
        ? t("history.inconclusive_next_step_label")
        : t("history.findings_next_step_label")
      : null,
    nextStep,
  };
}

function buildSecondaryFinding(
  finding: FindingPayload,
  summary: HistoryInsightsPayload,
  params: Pick<PresenterParams, "fmt" | "t">,
): HistorySecondaryFindingViewModel {
  const { t } = params;
  return {
    source: formatSourceLabel(finding.suspected_source, t),
    confidence: confidenceText(finding, params),
    tone: findingTone(finding),
    signature: findingSignatureText(finding, params),
    locationLabel: t("history.findings_location"),
    location: findingLocationText(finding, summary, t),
    speedBandLabel: t("history.findings_speed_band"),
    speedBand: findingSpeedBandText(finding, summary, t),
    evidenceSummary: String(finding.evidence_summary ?? ""),
  };
}

function buildInsights(
  detail: RunDetail,
  params: Pick<PresenterParams, "fmt" | "t">,
): HistoryInsightsViewModel {
  const { t } = params;
  const loadedInsights = detail.insights ?? detail.preview;
  const loading = detail.insightsLoading || (detail.previewLoading && loadedInsights === null);
  if (loadedInsights === null) {
    return {
      headerEyebrow: t("history.findings_title"),
      stateMessage: loading ? t("history.loading_insights") : t("history.findings_pending"),
      primary: null,
      secondaryTitle: null,
      visibleSecondary: [],
      hiddenSecondary: [],
      showMoreLabel: null,
      emptyMessage: null,
    };
  }
  const findings = summarizeFindings(loadedInsights);
  if (!findings.length) {
    return {
      headerEyebrow: t("history.findings_title"),
      stateMessage: null,
      primary: null,
      secondaryTitle: null,
      visibleSecondary: [],
      hiddenSecondary: [],
      showMoreLabel: null,
      emptyMessage: t("report.no_findings_for_run"),
    };
  }
  const secondaryFindings = findings.slice(1);
  const hiddenSecondary = secondaryFindings.slice(2).map((finding) =>
    buildSecondaryFinding(finding, loadedInsights, params),
  );
  return {
    headerEyebrow: t("history.findings_title"),
    stateMessage: null,
    primary: buildPrimaryFinding(loadedInsights, params),
    secondaryTitle: secondaryFindings.length ? t("history.secondary_candidates_title") : null,
    visibleSecondary: secondaryFindings
      .slice(0, 2)
      .map((finding) => buildSecondaryFinding(finding, loadedInsights, params)),
    hiddenSecondary,
    showMoreLabel: hiddenSecondary.length
      ? t("history.show_more_findings", { count: hiddenSecondary.length })
      : null,
    emptyMessage: null,
  };
}

function buildWarnings(detail: RunDetail): HistoryWarningBannerViewModel[] {
  const warnings = summarizeWarnings(detail.preview).concat(summarizeWarnings(detail.insights));
  return warnings
    .filter((warning, index) => warnings.findIndex((candidate) => candidate.code === warning.code) === index)
    .map((warning) => ({
      severity: String(warning.severity),
      title: String(warning.title),
      detail: warning.detail ? String(warning.detail) : null,
    }));
}

function buildDetails(
  run: HistoryEntry,
  detail: RunDetail,
  params: Pick<PresenterParams, "fmt" | "fmtTs" | "formatInt" | "t">,
): HistoryDetailsViewModel {
  const { fmt, fmtTs, formatInt, t } = params;
  const summary = detail.insights ?? detail.preview;
  const hasDiagnosis = Boolean(detail.insights || detail.preview);
  const showReloadAction = hasDiagnosis || Boolean(detail.insightsError);
  const showLoadingStatus = detail.insightsLoading || (detail.previewLoading && !hasDiagnosis);
  const runSummary = summary
    ? [
        `${t("report.run_id")}: ${run.run_id}`,
        `${t("history.summary_created")}: ${fmtTs(summary.start_time_utc as string)}`,
        `${t("history.summary_updated")}: ${fmtTs(run.end_time_utc ?? "")}`,
        `${t("history.summary_size")}: ${fmt(summary.duration_s as number, 1)} s`,
        `${t("history.summary_sensor_count")}: ${formatInt(summary.sensor_count_used as number)}`,
      ].join(" · ")
    : null;
  const heatmap = detail.previewLoading
    ? buildHeatmap(null, params, {
        stateMessage: t("history.loading_preview"),
        stateTone: "subtle",
      })
    : detail.previewError
      ? buildHeatmap(null, params, {
          stateMessage: detail.previewError,
          stateTone: "error",
        })
      : summary
        ? buildHeatmap(summary, params)
        : buildHeatmap(null, params, {
            stateMessage: t("history.preview_unavailable"),
            stateTone: "subtle",
          });
  return {
    titleEyebrow: t("history.details_title"),
    title: historyRunDisplayTitle(run, t),
    runSummary,
    reloadActionLabel: showReloadAction
      ? detail.insightsLoading
        ? t("history.loading_insights")
        : hasDiagnosis
          ? t("history.reload_insights")
          : t("history.load_insights")
      : null,
    reloadActionDisabled: detail.insightsLoading,
    loadingStatusText: showReloadAction
      ? null
      : showLoadingStatus
        ? t("history.loading_insights")
        : null,
    insightsError: detail.insightsError || null,
    warnings: buildWarnings(detail),
    insights: buildInsights(detail, params),
    heatmap,
    footerEyebrow: t("history.run_actions_title"),
    footerBody: t("history.run_actions_body"),
    exportLabel: t("history.export"),
    deleteLabel: t("history.delete"),
  };
}

function buildRowViewModel(run: HistoryEntry, detail: RunDetail, params: PresenterParams): HistoryRowViewModel {
  const { expandedRunId, formatInt, fmtTs, t } = params;
  const isExpanded = expandedRunId === run.run_id;
  const rowSummary = buildRowSummary(run, detail, params);
  return {
    runId: run.run_id,
    isExpanded,
    carLabel: t("history.car_label"),
    carName: historyRowCarName(run, t),
    summaryChips: buildSummaryChips(run, detail, params),
    summaryHeadline: rowSummary.headline,
    summaryMeta: rowSummary.meta,
    toggleLabel: isExpanded ? t("history.close_diagnosis") : t("history.open_diagnosis"),
    toggleTitle: isExpanded
      ? t("history.close_diagnosis_for_run", { runId: run.run_id })
      : t("history.open_diagnosis_for_run", { runId: run.run_id }),
    startedLabel: t("history.table.updated"),
    startedAtText: fmtTs(run.start_time_utc),
    sizeLabel: t("history.table.size"),
    sampleCountText: formatInt(run.sample_count),
    quickReportLabel: t("history.quick_report"),
    collapsedAction: buildCollapsedAction(run, detail, t),
    pdfError: detail.pdfError || null,
    details: isExpanded ? buildDetails(run, detail, params) : null,
  };
}

export function buildHistoryTableRowsViewModel(params: PresenterParams): HistoryRowViewModel[] {
  return params.runs.map((run) => buildRowViewModel(run, params.runDetailsById[run.run_id] ?? EMPTY_RUN_DETAIL, params));
}
