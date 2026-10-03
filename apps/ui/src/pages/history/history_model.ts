import type {
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import { HISTORY_HEATMAP_POSITIONS } from "../../config";

/** Pure view models for the History page: run rows and the expanded diagnosis. */

export type Translate = (key: string, vars?: Record<string, unknown>) => string;

export interface Formatters {
  t: Translate;
  fmt: (value: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}

/** Per-run loading state for the diagnosis preview, full insights, and PDF. */
export interface RunDetail {
  preview: HistoryInsightsPayload | null;
  previewLoading: boolean;
  previewError: string;
  insights: HistoryInsightsPayload | null;
  insightsLoading: boolean;
  insightsError: string;
  pdfLoading: boolean;
  pdfError: string;
}

export const EMPTY_RUN_DETAIL: RunDetail = {
  preview: null,
  previewLoading: false,
  previewError: "",
  insights: null,
  insightsLoading: false,
  insightsError: "",
  pdfLoading: false,
  pdfError: "",
};

type Finding = HistoryInsightsPayload["findings"][number];
export type Tone = "success" | "warn" | "neutral";
type ChipTone = "ok" | "warn" | "bad" | "muted";

export interface RowModel {
  runId: string;
  isExpanded: boolean;
  carName: string;
  chips: Array<{ key: string; text: string; tone: ChipTone }>;
  headline: string | null;
  meta: string | null;
  toggleLabel: string;
  toggleTitle: string;
  startedAt: string;
  sampleCount: string;
  /** Shown instead of the PDF button while the report is not ready. */
  reportPendingHint: string | null;
  pdfLabel: string;
  pdfLoading: boolean;
  pdfError: string | null;
}

export interface SecondaryFinding {
  source: string;
  confidence: string;
  tone: Tone;
  signature: string;
  location: string;
  speedBand: string;
  evidence: string;
}

export interface PrimaryFinding {
  eyebrow: string;
  headline: string;
  signature: string;
  confidence: string;
  tone: Tone;
  explanation: string;
  chips: Array<{ label: string; value: string }>;
  nextStepLabel: string | null;
  nextStep: string | null;
}

export type InsightsModel =
  | { kind: "state"; message: string }
  | { kind: "empty"; message: string }
  | {
      kind: "findings";
      primary: PrimaryFinding | null;
      secondaryTitle: string | null;
      visibleSecondary: SecondaryFinding[];
      hiddenSecondary: SecondaryFinding[];
      showMoreLabel: string | null;
    };

export interface HeatmapZone {
  key: string;
  label: string;
  gridArea: string;
  valueLabel: string;
  strongest: boolean;
  /** Null when the location has no measurement. */
  accent: { color: string; fillPercent: number } | null;
}

export type HeatmapModel =
  | { kind: "state"; message: string; tone: "subtle" | "error" }
  | { kind: "zones"; zones: HeatmapZone[]; extras: string[] };

export interface DetailsModel {
  title: string;
  runSummary: string | null;
  reloadLabel: string | null;
  reloadDisabled: boolean;
  loadingStatus: string | null;
  insightsError: string | null;
  warnings: Array<{ severity: string; title: string; detail: string | null }>;
  insights: InsightsModel;
  heatmap: HeatmapModel;
}

const VISIBLE_FINDING_LIMIT = 5;
const SOURCE_LABEL_KEYS = new Set([
  "wheel_tire",
  "driveline",
  "engine",
  "body_resonance",
  "transient_impact",
  "baseline_noise",
  "unknown_resonance",
]);

function findings(summary: HistoryInsightsPayload | null): Finding[] {
  return summary?.findings?.slice(0, VISIBLE_FINDING_LIMIT) ?? [];
}

function sourceKey(source: unknown): string {
  return String(source ?? "")
    .trim()
    .toLowerCase();
}

export function sourceLabel(source: unknown, t: Translate): string {
  const raw = String(source ?? "").trim();
  const key = sourceKey(source);
  if (!key) {
    return t("report.missing");
  }
  if (SOURCE_LABEL_KEYS.has(key)) {
    return t(`history.source.${key}`);
  }
  if (!/^[a-z0-9_-]+$/.test(raw)) {
    return raw;
  }
  return key
    .split(/[_-]+/g)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function inconclusive(finding: Finding | null): boolean {
  const key = sourceKey(finding?.suspected_source);
  return (
    finding !== null &&
    (key === "" || key === "unknown_resonance" || key === "baseline_noise")
  );
}

function confidenceText(
  finding: Finding,
  f: Pick<Formatters, "fmt" | "t">,
): string {
  const value =
    typeof finding.confidence_pct === "string" && finding.confidence_pct.trim()
      ? finding.confidence_pct
      : typeof finding.confidence === "number" &&
          Number.isFinite(finding.confidence)
        ? f.fmt(finding.confidence, 2)
        : "--";
  return f.t("report.confidence", { value });
}

function findingTone(finding: Finding | null): Tone {
  const tone = String(finding?.confidence_tone ?? "").toLowerCase();
  return tone === "success" || tone === "warn" ? tone : "neutral";
}

function signatureText(finding: Finding, fmt: Formatters["fmt"]): string {
  const raw = finding.frequency_hz_or_order;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return `${fmt(raw, 1)} Hz`;
  }
  return String(raw ?? "").trim() || "--";
}

function locationText(
  finding: Finding,
  summary: HistoryInsightsPayload,
  t: Translate,
): string {
  return (
    finding.strongest_location ||
    summary.most_likely_origin?.location ||
    t("report.missing")
  );
}

function speedBandText(
  finding: Finding,
  summary: HistoryInsightsPayload,
  t: Translate,
): string {
  return (
    finding.strongest_speed_band ||
    summary.most_likely_origin?.speed_band ||
    t("report.missing")
  );
}

export function postAnalysisReady(run: HistoryEntry): boolean {
  return (
    run.lifecycle?.post_analysis === "ready" ||
    (run.lifecycle == null && run.status === "complete")
  );
}

function reportReady(run: HistoryEntry): boolean {
  return (
    run.lifecycle?.report === "ready" ||
    (run.lifecycle == null && run.status === "complete")
  );
}

function rowSummary(detail: RunDetail): HistoryInsightsPayload | null {
  return detail.insights ?? detail.preview;
}

function statusBadge(
  run: HistoryEntry,
  detail: RunDetail,
  t: Translate,
): { text: string; tone: ChipTone } {
  const analyzing = () =>
    rowSummary(detail) !== null
      ? { text: t("history.row_status.preview_ready"), tone: "ok" as const }
      : { text: t("history.row_status.analyzing"), tone: "warn" as const };
  switch (run.lifecycle?.stage) {
    case "recording":
      return { text: t("history.row_status.recording"), tone: "warn" };
    case "post_analysis_pending":
    case "post_analysis_running":
      return analyzing();
    case "post_analysis_ready":
      return { text: t("history.row_status.complete"), tone: "ok" };
    case "post_analysis_degraded":
      return { text: t("history.row_status.error"), tone: "bad" };
  }
  switch (run.status) {
    case "complete":
      return { text: t("history.row_status.complete"), tone: "ok" };
    case "analyzing":
      return analyzing();
    case "recording":
      return { text: t("history.row_status.recording"), tone: "warn" };
    case "error":
      return { text: t("history.row_status.error"), tone: "bad" };
    default:
      return { text: run.status || t("report.missing"), tone: "muted" };
  }
}

function durationSeconds(run: HistoryEntry, detail: RunDetail): number | null {
  const summary = rowSummary(detail);
  const fromSummary = Number(summary?.duration_s);
  if (Number.isFinite(fromSummary) && fromSummary >= 0) {
    return fromSummary;
  }
  const startMs = Date.parse(run.start_time_utc);
  const endIso = run.end_time_utc ?? summary?.end_time_utc ?? null;
  const endMs = endIso ? Date.parse(endIso) : Number.NaN;
  return Number.isFinite(startMs) && Number.isFinite(endMs) && endMs >= startMs
    ? (endMs - startMs) / 1000
    : null;
}

function carName(run: HistoryEntry, t: Translate): string {
  const name = typeof run.car_name === "string" ? run.car_name.trim() : "";
  return name || t("history.car_missing");
}

function failed(run: HistoryEntry): boolean {
  return (
    run.lifecycle?.stage === "post_analysis_degraded" || run.status === "error"
  );
}

export function buildRow(
  run: HistoryEntry,
  detail: RunDetail,
  isExpanded: boolean,
  f: Formatters,
): RowModel {
  const { t, fmt, formatInt } = f;
  const summary = rowSummary(detail);
  const primary = findings(summary)[0] ?? null;
  const badge = statusBadge(run, detail, t);
  const chips: RowModel["chips"] = [{ key: "status", ...badge }];
  if (failed(run) && run.error_message) {
    chips.push({
      key: "error-message",
      text: run.error_message,
      tone: "muted",
    });
  }

  const source =
    summary?.most_likely_origin?.suspected_source ||
    primary?.suspected_source ||
    "";
  const label =
    primary && inconclusive(primary)
      ? t("history.row_source_inconclusive")
      : source
        ? sourceLabel(source, t)
        : "";
  const ready = postAnalysisReady(run);
  const headline =
    label ||
    (ready && (detail.previewLoading || detail.insightsLoading || !summary)
      ? t("history.row_summary_loading")
      : ready && summary
        ? t("history.row_no_findings")
        : badge.text);
  const meta: string[] = [];
  if (primary) {
    meta.push(confidenceText(primary, f));
  }
  const duration = durationSeconds(run, detail);
  if (duration !== null) {
    meta.push(`${t("history.summary_size")}: ${fmt(duration, 1)} s`);
  }
  const sensors = Number(summary?.sensor_count_used);
  if (Number.isFinite(sensors) && sensors > 0) {
    meta.push(`${t("history.summary_sensor_count")}: ${formatInt(sensors)}`);
  }
  if (meta.length === 0 && run.status === "error" && run.error_message) {
    meta.push(run.error_message);
  }

  return {
    runId: run.run_id,
    isExpanded,
    carName: carName(run, t),
    chips,
    headline,
    meta: meta.length ? meta.join(" · ") : null,
    toggleLabel: t(
      isExpanded ? "history.close_diagnosis" : "history.open_diagnosis",
    ),
    toggleTitle: t(
      isExpanded
        ? "history.close_diagnosis_for_run"
        : "history.open_diagnosis_for_run",
      { runId: run.run_id },
    ),
    startedAt: f.fmtTs(run.start_time_utc),
    sampleCount: formatInt(run.sample_count),
    reportPendingHint: reportReady(run)
      ? null
      : t("history.quick_report_pending"),
    pdfLabel: t(
      detail.pdfLoading ? "history.generating_pdf" : "history.generate_pdf",
    ),
    pdfLoading: detail.pdfLoading,
    pdfError: detail.pdfError || null,
  };
}

function secondaryFinding(
  finding: Finding,
  summary: HistoryInsightsPayload,
  f: Formatters,
): SecondaryFinding {
  return {
    source: sourceLabel(finding.suspected_source, f.t),
    confidence: confidenceText(finding, f),
    tone: findingTone(finding),
    signature: signatureText(finding, f.fmt),
    location: locationText(finding, summary, f.t),
    speedBand: speedBandText(finding, summary, f.t),
    evidence: String(finding.evidence_summary ?? ""),
  };
}

function primaryFinding(
  summary: HistoryInsightsPayload,
  primary: Finding,
  f: Formatters,
): PrimaryFinding {
  const { t } = f;
  const unclear = inconclusive(primary);
  const location = locationText(primary, summary, t);
  const signature = signatureText(primary, f.fmt);
  const confident =
    findingTone(primary) === "success" ||
    (typeof primary.confidence === "number" &&
      Number.isFinite(primary.confidence) &&
      primary.confidence >= 0.85);
  const nextStep = unclear
    ? t("history.inconclusive_next_step")
    : confident && location !== t("report.missing")
      ? t("history.findings_next_step", { location })
      : null;
  return {
    eyebrow: t(
      unclear ? "history.capture_verdict" : "history.primary_diagnosis",
    ),
    headline: unclear
      ? t("history.inconclusive_title")
      : sourceLabel(primary.suspected_source, t),
    signature,
    confidence: confidenceText(primary, f),
    tone: findingTone(primary),
    explanation: String(
      primary.evidence_summary ??
        summary.most_likely_origin?.explanation ??
        (unclear ? t("history.inconclusive_body") : ""),
    ),
    chips: [
      { label: t("history.findings_location"), value: location },
      {
        label: t("history.findings_speed_band"),
        value: speedBandText(primary, summary, t),
      },
      { label: t("history.findings_signature"), value: signature },
    ],
    nextStepLabel: nextStep
      ? t(
          unclear
            ? "history.inconclusive_next_step_label"
            : "history.findings_next_step_label",
        )
      : null,
    nextStep,
  };
}

function insightsModel(detail: RunDetail, f: Formatters): InsightsModel {
  const { t } = f;
  const summary = rowSummary(detail);
  if (summary === null) {
    const loading = detail.insightsLoading || detail.previewLoading;
    return {
      kind: "state",
      message: t(
        loading ? "history.loading_insights" : "history.findings_pending",
      ),
    };
  }
  const list = findings(summary);
  if (!list.length) {
    return { kind: "empty", message: t("report.no_findings_for_run") };
  }
  const secondary = list
    .slice(1)
    .map((finding) => secondaryFinding(finding, summary, f));
  const hidden = secondary.slice(2);
  return {
    kind: "findings",
    primary: primaryFinding(summary, list[0], f),
    secondaryTitle: secondary.length
      ? t("history.secondary_candidates_title")
      : null,
    visibleSecondary: secondary.slice(0, 2),
    hiddenSecondary: hidden,
    showMoreLabel: hidden.length
      ? t("history.show_more_findings", { count: hidden.length })
      : null,
  };
}

function rawCaptureWarnings(
  run: HistoryEntry,
  t: Translate,
): DetailsModel["warnings"] {
  const state =
    run.lifecycle?.raw_capture ??
    run.artifact_availability?.raw_capture ??
    "not_recorded";
  if (state === "missing") {
    return [
      {
        severity: "warn",
        title: t("history.raw_capture_missing_title"),
        detail: t("history.raw_capture_missing_detail"),
      },
    ];
  }
  const finalize = run.raw_capture_finalize;
  const status = finalize?.status;
  if (
    state !== "degraded" ||
    !finalize ||
    (status !== "enqueue_timeout" &&
      status !== "timeout" &&
      status !== "failed")
  ) {
    return [];
  }
  return [
    {
      severity: "warn",
      title: t("history.raw_capture_degraded_title"),
      detail: t(`history.raw_capture_degraded_${status}_detail`, {
        queueDepth: finalize.queue_depth ?? "unknown",
        errorSummary: finalize.error_summary ?? t("history.not_reported"),
      }),
    },
  ];
}

function insightWarnings(detail: RunDetail): DetailsModel["warnings"] {
  const all: HistoryInsightWarningPayload[] = [
    ...(detail.preview?.warnings ?? []),
    ...(detail.insights?.warnings ?? []),
  ];
  return all
    .filter(
      (warning, index) =>
        all.findIndex((candidate) => candidate.code === warning.code) === index,
    )
    .map((warning) => ({
      severity: String(warning.severity),
      title: String(warning.title),
      detail: warning.detail ? String(warning.detail) : null,
    }));
}

/** Folds free-text location names onto the fixed car-diagram positions. */
export function heatmapLocationKey(location: unknown): string {
  const raw = String(location || "")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const has = (...words: string[]) => words.every((word) => raw.includes(word));
  if (has("front left", "wheel")) return "front-left wheel";
  if (has("front right", "wheel")) return "front-right wheel";
  if (has("rear left", "wheel")) return "rear-left wheel";
  if (has("rear right", "wheel")) return "rear-right wheel";
  if (has("engine")) return "engine bay";
  if (has("drive", "tunnel")) return "driveshaft tunnel";
  if (has("driver", "seat")) return "driver seat";
  if (has("trunk")) return "trunk";
  return raw;
}

function titleCase(key: string): string {
  return key
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** 0..1 within [min, max]; a single value sits mid-range (or at 0 when zero). */
export function normalizeUnit(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return 0;
  if (max <= min) return min > 0 ? 0.5 : 0;
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

/** Blue (cold) to red (hot) for a 0..1 intensity. */
export function heatColor(norm: number): string {
  return `hsl(${Math.round(212 - norm * 190)} 76% 48%)`;
}

export function buildHeatmap(
  summary: HistoryInsightsPayload,
  f: Pick<Formatters, "fmt" | "t">,
): HeatmapModel {
  const metric = new Map<string, number>();
  const labels = new Map<string, string>();
  for (const row of summary.sensor_intensity_by_location ?? []) {
    const key = heatmapLocationKey(row.location);
    const value = Number(
      row.p95_intensity_db ?? row.mean_intensity_db ?? row.max_intensity_db,
    );
    if (key && Number.isFinite(value)) {
      metric.set(key, value);
    }
    const label = String(row.location ?? "").trim();
    if (key && label) {
      labels.set(key, label);
    }
  }
  const values = [...metric.values()];
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const zones = HISTORY_HEATMAP_POSITIONS.map((point) => {
    const value = metric.get(point.key);
    const label = labels.get(point.key) || titleCase(point.key);
    if (value === undefined || min === null || max === null) {
      return {
        key: point.key,
        label,
        gridArea: point.area,
        valueLabel: f.t("report.missing"),
        strongest: false,
        accent: null,
      };
    }
    const norm = normalizeUnit(value, min, max);
    return {
      key: point.key,
      label,
      gridArea: point.area,
      valueLabel: `${f.fmt(value, 1)} dB`,
      strongest: value === max,
      accent: { color: heatColor(norm), fillPercent: Math.round(norm * 100) },
    };
  });
  const known = new Set<string>(
    HISTORY_HEATMAP_POSITIONS.map((point) => point.key),
  );
  const extras = [...metric.entries()]
    .filter(([key]) => !known.has(key))
    .map(
      ([key, value]) =>
        `${labels.get(key) || titleCase(key)} · ${f.fmt(value, 1)} dB`,
    );
  return { kind: "zones", zones, extras };
}

export function buildDetails(
  run: HistoryEntry,
  detail: RunDetail,
  f: Formatters,
): DetailsModel {
  const { t, fmt, fmtTs, formatInt } = f;
  const summary = rowSummary(detail);
  const showReload = summary !== null || Boolean(detail.insightsError);
  const name = carName(run, t);
  return {
    title: name === t("history.car_missing") ? run.run_id : name,
    runSummary: summary
      ? [
          `${t("report.run_id")}: ${run.run_id}`,
          `${t("history.summary_created")}: ${fmtTs(summary.start_time_utc ?? "")}`,
          `${t("history.summary_updated")}: ${fmtTs(run.end_time_utc ?? "")}`,
          `${t("history.summary_size")}: ${fmt(summary.duration_s, 1)} s`,
          `${t("history.summary_sensor_count")}: ${formatInt(summary.sensor_count_used)}`,
        ].join(" · ")
      : null,
    reloadLabel: showReload
      ? t(
          detail.insightsLoading
            ? "history.loading_insights"
            : summary
              ? "history.reload_insights"
              : "history.load_insights",
        )
      : null,
    reloadDisabled: detail.insightsLoading,
    loadingStatus:
      !showReload && (detail.insightsLoading || detail.previewLoading)
        ? t("history.loading_insights")
        : null,
    insightsError: detail.insightsError || null,
    warnings: [...rawCaptureWarnings(run, t), ...insightWarnings(detail)],
    insights: insightsModel(detail, f),
    heatmap: detail.previewLoading
      ? { kind: "state", message: t("history.loading_preview"), tone: "subtle" }
      : detail.previewError
        ? { kind: "state", message: detail.previewError, tone: "error" }
        : summary
          ? buildHeatmap(summary, f)
          : {
              kind: "state",
              message: t("history.preview_unavailable"),
              tone: "subtle",
            },
  };
}
