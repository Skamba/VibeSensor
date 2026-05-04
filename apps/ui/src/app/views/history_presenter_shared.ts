import type {
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import type { RunDetail } from "../history_state";
import type {
  HistoryFindingTone,
  HistorySummaryChipTone,
} from "./history_table_models";
import type { HistoryTableViewParams } from "./history_table_view";

export type PresenterParams = Pick<
  HistoryTableViewParams,
  | "expandedRunId"
  | "fmt"
  | "fmtTs"
  | "formatInt"
  | "runDetailsById"
  | "runs"
  | "t"
>;

export type HistoryFindingPayload = HistoryInsightsPayload["findings"][number];

export type HistoryRowStatusBadge = {
  label: string;
  tone: Extract<HistorySummaryChipTone, "ok" | "warn" | "bad" | "muted">;
};

export type HistoryRowSummary = {
  headline: string | null;
  meta: string | null;
};

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

export function summarizeFindings(
  summary: HistoryInsightsPayload | null,
): HistoryFindingPayload[] {
  return summary?.findings?.slice(0, VISIBLE_FINDING_LIMIT) ?? [];
}

export function summarizeWarnings(
  payload: HistoryInsightsPayload | null,
): HistoryInsightWarningPayload[] {
  return payload?.warnings ?? [];
}

function normalizedSourceKey(source: unknown): string {
  return String(source ?? "")
    .trim()
    .toLowerCase();
}

function humanizeSourceFallback(sourceKey: string): string {
  return sourceKey
    .split(/[_-]+/g)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function formatSourceLabel(
  source: unknown,
  t: PresenterParams["t"],
): string {
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

export function isInconclusiveFinding(
  finding: HistoryFindingPayload | null,
): boolean {
  return finding !== null && isInconclusiveSource(finding.suspected_source);
}

export function confidenceText(
  finding: HistoryFindingPayload,
  params: Pick<PresenterParams, "fmt" | "t">,
): string {
  const { fmt, t } = params;
  const value =
    typeof finding.confidence_pct === "string" && finding.confidence_pct.trim()
      ? finding.confidence_pct
      : typeof finding.confidence === "number" &&
          Number.isFinite(finding.confidence)
        ? fmt(finding.confidence, 2)
        : "--";
  return t("report.confidence", { value });
}

export function findingTone(
  finding: HistoryFindingPayload | null,
): HistoryFindingTone {
  const tone = String(finding?.confidence_tone ?? "").toLowerCase();
  if (tone === "success" || tone === "warn") {
    return tone;
  }
  return "neutral";
}

export function findingSignatureText(
  finding: HistoryFindingPayload,
  params: Pick<PresenterParams, "fmt">,
): string {
  const raw = finding.frequency_hz_or_order;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return `${params.fmt(raw, 1)} Hz`;
  }
  const text = String(raw ?? "").trim();
  return text || "--";
}

export function findingLocationText(
  finding: HistoryFindingPayload,
  summary: HistoryInsightsPayload | null,
  t: PresenterParams["t"],
): string {
  return (
    finding.strongest_location ||
    summary?.most_likely_origin?.location ||
    t("report.missing")
  );
}

export function findingSpeedBandText(
  finding: HistoryFindingPayload,
  summary: HistoryInsightsPayload | null,
  t: PresenterParams["t"],
): string {
  return (
    finding.strongest_speed_band ||
    summary?.most_likely_origin?.speed_band ||
    t("report.missing")
  );
}

export function historyRowSummary(
  detail: RunDetail,
): HistoryInsightsPayload | null {
  return detail.insights ?? detail.preview;
}

export function historyPostAnalysisReady(run: HistoryEntry): boolean {
  return (
    run.lifecycle?.post_analysis === "ready" ||
    (run.lifecycle == null && run.status === "complete")
  );
}

export function historyReportReady(run: HistoryEntry): boolean {
  return (
    run.lifecycle?.report === "ready" ||
    (run.lifecycle == null && run.status === "complete")
  );
}

export function historyRawCaptureState(run: HistoryEntry): string {
  return (
    run.lifecycle?.raw_capture ??
    run.artifact_availability?.raw_capture ??
    "not_recorded"
  );
}

export function historyRowStatusBadge(
  run: HistoryEntry,
  detail: RunDetail,
  t: PresenterParams["t"],
): HistoryRowStatusBadge {
  const summary = historyRowSummary(detail);
  switch (run.lifecycle?.stage) {
    case "recording":
      return { label: t("history.row_status.recording"), tone: "warn" };
    case "post_analysis_pending":
    case "post_analysis_running":
      return summary !== null
        ? { label: t("history.row_status.preview_ready"), tone: "ok" }
        : { label: t("history.row_status.analyzing"), tone: "warn" };
    case "post_analysis_ready":
      return { label: t("history.row_status.complete"), tone: "ok" };
    case "post_analysis_degraded":
      return { label: t("history.row_status.error"), tone: "bad" };
  }
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

export function historyRowDurationSeconds(
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

export function historyRowCarName(
  run: HistoryEntry,
  t: PresenterParams["t"],
): string {
  const value = typeof run.car_name === "string" ? run.car_name.trim() : "";
  return value || t("history.car_missing");
}

export function historyRunDisplayTitle(
  run: HistoryEntry,
  t: PresenterParams["t"],
): string {
  const carName = historyRowCarName(run, t);
  return carName === t("history.car_missing") ? run.run_id : carName;
}
