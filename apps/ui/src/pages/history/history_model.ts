import type {
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import {
  GUIDED_SWEEP_FROM_KMH,
  GUIDED_SWEEP_TO_KMH,
  HISTORY_HEATMAP_POSITIONS,
} from "../../config";
import {
  formatSpeed,
  formatSpeedRange,
  kmhInUnit,
  type SpeedUnit,
  speedUnitKey,
} from "../../format";
import { locationLabel } from "../../sensor_locations";

/** Pure view models for the History page: run rows and the expanded diagnosis. */

export type Translate = (key: string, vars?: Record<string, unknown>) => string;

export interface Formatters {
  t: Translate;
  fmt: (value: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  speedUnit: SpeedUnit;
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
  /** Accelerometer samples in the raw capture; "--" when none was kept. */
  rawSampleCount: string;
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

export interface CheckLine {
  label: string;
  detail: string;
}

/** What this run could check, what it couldn't, and the car references it
 * used with their provenance, in the PDF's wording. */
export interface ChecksModel {
  checkedTitle: string;
  checked: CheckLine[];
  notCheckedTitle: string;
  notChecked: CheckLine[];
  /** Sources this car does not have (an EV's engine): neither checked nor missed. */
  notApplicableTitle: string;
  notApplicable: CheckLine[];
  referencesTitle: string;
  references: CheckLine[];
}

export type InsightsModel =
  | { kind: "state"; message: string }
  | {
      kind: "findings";
      primary: PrimaryFinding | null;
      checks: ChecksModel;
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
  "brakes",
  "body_resonance",
  "transient_impact",
  "baseline_noise",
  "unknown_resonance",
]);

type Diagnosis = HistoryInsightsPayload["diagnosis"];
type ConfidenceLevel = NonNullable<Diagnosis["confidence_level"]>;

const ZONE_KEYS = new Set([
  "front_left_wheel",
  "front_right_wheel",
  "rear_left_wheel",
  "rear_right_wheel",
  "front_axle",
  "rear_axle",
  "all_wheels",
  "engine_bay",
  "driveshaft_tunnel",
  "transmission",
]);
const WHEEL_ZONE_KEYS = new Set([
  "front_left_wheel",
  "front_right_wheel",
  "rear_left_wheel",
  "rear_right_wheel",
  "front_axle",
  "rear_axle",
  "all_wheels",
]);
const NON_FAULT_SOURCES = new Set(["baseline_noise", "transient_impact"]);
// Brake judder shows when braking firmly from speed (the report's recapture step).
const BRAKE_TEST_FROM_KMH = 100;
const BRAKE_TEST_TO_KMH = 40;

function findings(summary: HistoryInsightsPayload | null): Finding[] {
  return summary?.findings?.slice(0, VISIBLE_FINDING_LIMIT) ?? [];
}

function sourceKey(source: unknown): string {
  return String(source ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s/]+/g, "_");
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
  if (!/^[a-z0-9_-]+$/.test(key)) {
    return raw;
  }
  return key
    .split(/[_-]+/g)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function levelTone(level: ConfidenceLevel | null | undefined): Tone {
  return level === "strong"
    ? "success"
    : level === "moderate"
      ? "warn"
      : "neutral";
}

/** The one confidence expression: a level word, never a percentage. */
function confidenceText(
  level: ConfidenceLevel | null | undefined,
  t: Translate,
): string {
  return level
    ? t("history.confidence", { level: t(`history.confidence_level.${level}`) })
    : "";
}

function signatureText(finding: Finding, fmt: Formatters["fmt"]): string {
  const raw = finding.frequency_hz_or_order;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return `${fmt(raw, 1)} Hz`;
  }
  return String(raw ?? "").trim() || "--";
}

function diagnosisSignature(
  diagnosis: Diagnosis,
  f: Pick<Formatters, "fmt" | "t" | "speedUnit">,
): string {
  const parts: string[] = [];
  if (diagnosis.order_code) {
    parts.push(diagnosis.order_code);
  }
  if (diagnosis.frequency_hz != null) {
    const at =
      diagnosis.reference_speed_kmh != null
        ? ` @ ${formatSpeed(diagnosis.reference_speed_kmh, f.speedUnit, f.t, 0)}`
        : "";
    parts.push(`${f.fmt(diagnosis.frequency_hz, 1)} Hz${at}`);
  }
  return parts.join(" · ") || "--";
}

/** A wheel/tire fault felt strongest away from the wheels: no wheel can be named. */
function unlocatedWheel(diagnosis: Diagnosis): boolean {
  return (
    diagnosis.source === "wheel/tire" &&
    !WHEEL_ZONE_KEYS.has(diagnosis.zone ?? "")
  );
}

function electric(diagnosis: Diagnosis): boolean {
  return diagnosis.conditions.fuel_type === "EV";
}

/** An engined car without a propshaft (front-wheel drive, e-AWD hybrid). */
function noPropshaft(diagnosis: Diagnosis): boolean {
  return !electric(diagnosis) && diagnosis.conditions.propshaft === false;
}

function zoneText(diagnosis: Diagnosis, t: Translate): string {
  if (
    diagnosis.source === "brakes" &&
    (diagnosis.zone === "front_axle" || diagnosis.zone === "rear_axle")
  ) {
    // Brake judder: the discs on that axle, not its wheels.
    return t(`history.zone.brake_discs_${diagnosis.zone}`);
  }
  if (diagnosis.zone === "driveshaft_tunnel" && electric(diagnosis)) {
    // An EV has no propshaft: a motor order no axle dominates is the drive unit.
    return t("history.zone.drive_unit_ev");
  }
  if (diagnosis.zone === "driveshaft_tunnel" && noPropshaft(diagnosis)) {
    // No propshaft runs through the tunnel of a front-wheel-drive car.
    return t("history.zone.centre_tunnel");
  }
  if (diagnosis.zone && ZONE_KEYS.has(diagnosis.zone)) {
    return t(`history.zone.${diagnosis.zone}`);
  }
  return diagnosis.location
    ? locationLabel(diagnosis.location, t)
    : t("report.missing");
}

function speedRangeText(
  low: number | null | undefined,
  high: number | null | undefined,
  f: Pick<Formatters, "t" | "speedUnit">,
): string {
  return formatSpeedRange(low, high, f.speedUnit, f.t) ?? f.t("report.missing");
}

/** The analysis labels speed bands "80-90 km/h" (or "80 km/h"). */
const KMH_BAND_RE = /^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))? km\/h$/;

/** A server speed-band label in the display unit; unknown shapes pass through. */
export function speedBandLabel(
  label: string,
  f: Pick<Formatters, "t" | "speedUnit">,
): string {
  const match = KMH_BAND_RE.exec(label.trim());
  if (!match) {
    return label;
  }
  const low = Number(match[1]);
  return match[2] === undefined
    ? formatSpeed(low, f.speedUnit, f.t, 0)
    : (formatSpeedRange(low, Number(match[2]), f.speedUnit, f.t) ?? label);
}

function locationText(
  finding: Finding,
  summary: HistoryInsightsPayload,
  t: Translate,
): string {
  const location =
    finding.strongest_location || summary.most_likely_origin?.location;
  return location ? locationLabel(location, t) : t("report.missing");
}

function speedBandText(
  finding: Finding,
  summary: HistoryInsightsPayload,
  f: Pick<Formatters, "t" | "speedUnit">,
): string {
  const band =
    finding.strongest_speed_band || summary.most_likely_origin?.speed_band;
  return band ? speedBandLabel(band, f) : f.t("report.missing");
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

/** A run started before the Pi clock was set has wrong wall times; say so instead. */
function runTime(run: HistoryEntry, iso: string, f: Formatters): string {
  return run.start_time_unverified ? f.t("history.time_unknown") : f.fmtTs(iso);
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
  const diagnosis = summary?.diagnosis ?? null;
  const badge = statusBadge(run, detail, t);
  const chips: RowModel["chips"] = [{ key: "status", ...badge }];
  if (failed(run) && run.error_message) {
    chips.push({
      key: "error-message",
      text: run.error_message,
      tone: "muted",
    });
  }

  const label = diagnosis ? verdictHeadline(diagnosis, t) : "";
  const ready = postAnalysisReady(run);
  const headline =
    label ||
    (ready && (detail.previewLoading || detail.insightsLoading || !summary)
      ? t("history.row_summary_loading")
      : badge.text);
  const meta: string[] = [];
  if (diagnosis?.confidence_level) {
    meta.push(confidenceText(diagnosis.confidence_level, t));
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
    startedAt: runTime(run, run.start_time_utc, f),
    rawSampleCount:
      run.raw_sample_count == null ? "--" : formatInt(run.raw_sample_count),
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

/** An EV's motor turns at the driveline order, so that source is its motor. */
function carSourceLabel(
  source: unknown,
  diagnosis: Diagnosis,
  t: Translate,
): string {
  return electric(diagnosis) && sourceKey(source) === "driveline"
    ? t("history.source.motor")
    : sourceLabel(source, t);
}

function verdictHeadline(diagnosis: Diagnosis, t: Translate): string {
  if (diagnosis.verdict === "no_fault") {
    return noFaultHeadline(diagnosis, t);
  }
  if (diagnosis.verdict === "weak_evidence") {
    return t("history.verdict.weak_evidence");
  }
  return carSourceLabel(diagnosis.source, diagnosis, t);
}

function secondaryFinding(
  finding: Finding,
  summary: HistoryInsightsPayload,
  f: Formatters,
): SecondaryFinding {
  return {
    source: carSourceLabel(finding.suspected_source, summary.diagnosis, f.t),
    confidence: confidenceText(finding.confidence_level, f.t),
    tone: levelTone(finding.confidence_level),
    signature: signatureText(finding, f.fmt),
    location: locationText(finding, summary, f.t),
    speedBand: speedBandText(finding, summary, f),
    evidence: String(finding.evidence_summary ?? ""),
  };
}

type SourceCheck = Diagnosis["source_checks"][number];
type CheckReason = NonNullable<SourceCheck["reason"]>;

/** Source families in the analysis' `source_checks`, keyed for catalog lookups. */
const CHECK_SOURCE_KEYS: Record<string, string> = {
  "wheel/tire": "wheel_tire",
  driveline: "driveline",
  engine: "engine",
  brakes: "brakes",
};

const EV_CHECK_SOURCE_KEYS: Record<string, string> = {
  driveline: "motor",
  engine: "combustion_engine",
};

/** The catalog key of a checked source: an EV's driveline is its motor, and
 * the engine it lacks is named the combustion engine. */
function checkSourceKey(check: SourceCheck, diagnosis: Diagnosis): string {
  const source = CHECK_SOURCE_KEYS[check.source];
  return (electric(diagnosis) && EV_CHECK_SOURCE_KEYS[source]) || source;
}
/** The engine's own wording (measured RPM needs no tire size or ratios; an
 * estimated RPM always assumes top gear), as on page 1 of the PDF. */
const ENGINE_CHECK_REASONS = new Set<CheckReason>([
  "no_tire_reference",
  "no_drive_reference",
  "estimated_final_drive",
]);

/** An EV's motor wording names its reduction ratio instead of the final drive. */
const MOTOR_CHECK_REASONS = new Set<CheckReason>([
  "no_drive_reference",
  "estimated_final_drive",
]);

function checkReasonKey(source: string, reason: CheckReason): string {
  if (source === "engine" && ENGINE_CHECK_REASONS.has(reason)) {
    return `engine_${reason}`;
  }
  return source === "motor" && MOTOR_CHECK_REASONS.has(reason)
    ? `motor_${reason}`
    : reason;
}

function checkedDetail(
  check: SourceCheck,
  source: string,
  diagnosis: Diagnosis,
  t: Translate,
): string {
  if (check.status === "candidate") {
    return t("history.checks.candidate");
  }
  if (check.status === "ruled_out_estimated" && check.reason) {
    return t(`history.checks.limited.${checkReasonKey(source, check.reason)}`);
  }
  if (
    check.reason === "stayed_in_neutral" ||
    check.reason === "stopped_in_neutral" ||
    check.reason === "only_while_braking"
  ) {
    return t(`history.checks.${check.reason}`);
  }
  return source === "driveline" && noPropshaft(diagnosis)
    ? t("history.checks.ruled_out.driveline_no_propshaft")
    : t(`history.checks.ruled_out.${source}`);
}

/** One car reference as on PDF page 2: the value and where it came from. */
function referenceText(
  value: string | null,
  provenance: Diagnosis["conditions"]["tire_provenance"],
  t: Translate,
): string {
  return value === null || provenance === "missing"
    ? t("history.provenance.missing")
    : t("history.references.with_provenance", {
        value,
        provenance: t(`history.provenance.${provenance}`),
      });
}

/** The powertrain line: what the run assumed and what that means for the engine. */
function powertrainKey(conditions: Diagnosis["conditions"]): string {
  switch (conditions.fuel_type) {
    case "EV":
      return "history.references.powertrain_ev";
    case "PHEV":
      return conditions.rpm_source === "measured"
        ? "history.references.powertrain_phev_measured"
        : "history.references.powertrain_phev_estimated";
    case "ICE":
      return "history.references.powertrain_ice";
    default:
      return "history.references.powertrain_unknown";
  }
}

/** The drive layout line, as on PDF page 2; an EV without one has none. */
function driveLayoutKey(conditions: Diagnosis["conditions"]): string | null {
  const layout = conditions.drive_layout ?? null;
  if (conditions.fuel_type === "EV") {
    return layout ? `history.references.drive_layout_ev_${layout}` : null;
  }
  if (layout === null) {
    return "history.references.drive_layout_unknown";
  }
  return layout === "AWD" && conditions.propshaft === false
    ? "history.references.drive_layout_AWD_no_propshaft"
    : `history.references.drive_layout_${layout}`;
}

function referenceLines(
  conditions: Diagnosis["conditions"],
  f: Pick<Formatters, "fmt" | "t">,
): CheckLine[] {
  const { t, fmt } = f;
  const ratio = (value: number | null) =>
    value === null ? null : fmt(value, 2);
  const tire = conditions.tire_circumference_m;
  const ev = conditions.fuel_type === "EV";
  const layoutKey = driveLayoutKey(conditions);
  const powertrain = [
    {
      label: t("history.references.powertrain"),
      detail: t(powertrainKey(conditions)),
    },
    ...(layoutKey
      ? [{ label: t("history.references.drive_layout"), detail: t(layoutKey) }]
      : []),
  ];
  const finalDrive = {
    label: t(
      ev
        ? "history.references.reduction_ratio"
        : "history.references.final_drive",
    ),
    detail: referenceText(
      ratio(conditions.final_drive_ratio),
      conditions.final_drive_provenance,
      t,
    ),
  };
  const tireLine = {
    label: t("history.references.tire"),
    detail: referenceText(
      tire === null
        ? null
        : t("history.references.circumference", {
            circumference: fmt(tire, 3),
          }),
      conditions.tire_provenance,
      t,
    ),
  };
  if (ev) {
    // No gearbox ratio and no engine RPM: an EV has neither.
    return [...powertrain, tireLine, finalDrive];
  }
  return [
    ...powertrain,
    tireLine,
    finalDrive,
    {
      label: t("history.references.top_gear"),
      detail: referenceText(
        ratio(conditions.gear_ratio),
        conditions.gear_ratio_provenance,
        t,
      ),
    },
    {
      label: t("history.references.rpm"),
      detail: t(`history.references.rpm_${conditions.rpm_source}`),
    },
  ];
}

/** The run's checked / couldn't-check lists, built only from `source_checks`,
 * and the references behind them. */
function checksModel(
  diagnosis: Diagnosis,
  f: Pick<Formatters, "fmt" | "t">,
): ChecksModel {
  const { t } = f;
  const checked: CheckLine[] = [];
  const notChecked: CheckLine[] = [];
  const notApplicable: CheckLine[] = [];
  for (const check of diagnosis.source_checks) {
    if (!CHECK_SOURCE_KEYS[check.source]) {
      continue;
    }
    const source = checkSourceKey(check, diagnosis);
    const label = t(`history.source.${source}`);
    if (check.status === "not_applicable") {
      notApplicable.push({
        label,
        detail: t(`history.checks.not_applicable.${check.reason}`),
      });
    } else if (check.status === "not_testable" && check.reason) {
      notChecked.push({
        label,
        detail: t(
          `history.checks.couldnt.${checkReasonKey(source, check.reason)}`,
        ),
      });
    } else {
      checked.push({
        label,
        detail: checkedDetail(check, source, diagnosis, t),
      });
    }
  }
  return {
    checkedTitle: t("history.checks.checked_title"),
    checked,
    notCheckedTitle: t("history.checks.not_checked_title"),
    notChecked,
    notApplicableTitle: t("history.checks.not_applicable_title"),
    notApplicable,
    referencesTitle: t("history.references.title"),
    references: referenceLines(diagnosis.conditions, f),
  };
}

function joinList(items: string[], t: Translate): string {
  return items.length < 2
    ? items.join("")
    : t("history.list_and", {
        items: items.slice(0, -1).join(", "),
        last: items[items.length - 1],
      });
}

/** The no-fault sentence: only what was checked (hedged when estimated) and
 * what was not, never "your car is fine". Same wording as the PDF. */
function noFaultExplanation(diagnosis: Diagnosis, t: Translate): string {
  const checked: string[] = [];
  const notChecked: string[] = [];
  for (const check of diagnosis.source_checks) {
    if (!CHECK_SOURCE_KEYS[check.source] || check.status === "not_applicable") {
      continue;
    }
    const source = checkSourceKey(check, diagnosis);
    const noun = t(`history.checks.noun.${source}`);
    if (check.status === "not_testable") {
      notChecked.push(noun);
    } else if (check.status === "ruled_out_estimated" && check.reason) {
      checked.push(
        t("history.checks.hedged", {
          source: noun,
          hedge: t(
            `history.checks.hedge.${checkReasonKey(source, check.reason)}`,
          ),
        }),
      );
    } else {
      checked.push(noun);
    }
  }
  const strongest = unexplainedLocation(diagnosis);
  let body: string;
  if (strongest !== null) {
    // A vibration was there; it just followed nothing the run could check.
    body = t("history.verdict.unexplained_body", {
      location: locationLabel(strongest, t),
    });
    if (checked.length) {
      body = `${body} ${t("history.verdict.unexplained_checked", { checked: joinList(checked, t) })}`;
    }
  } else if (checked.length === 0) {
    return t(
      electric(diagnosis)
        ? "history.verdict.no_fault_nothing_checked_ev"
        : "history.verdict.no_fault_nothing_checked",
    );
  } else {
    body = t("history.verdict.no_fault_body", {
      checked: joinList(checked, t),
    });
  }
  return notChecked.length
    ? `${body} ${t("history.verdict.no_fault_not_checked", { sources: joinList(notChecked, t) })}`
    : body;
}

/** Where a no-fault run still felt a significant vibration, strongest first. */
function unexplainedLocation(diagnosis: Diagnosis): string | null {
  if (diagnosis.verdict !== "no_fault" || !diagnosis.unexplained_vibration) {
    return null;
  }
  const row = diagnosis.location_amplitudes.find(
    (item) => item.amplitude_mg !== null,
  );
  return row ? row.location : null;
}

function noFaultHeadline(diagnosis: Diagnosis, t: Translate): string {
  return t(
    diagnosis.unexplained_vibration
      ? "history.verdict.unexplained"
      : "history.verdict.no_fault",
  );
}

function noFaultCard(
  summary: HistoryInsightsPayload,
  f: Formatters,
): PrimaryFinding {
  const { t } = f;
  const speeds = summary.speed_stats;
  return {
    eyebrow: t("history.verdict.eyebrow"),
    headline: noFaultHeadline(summary.diagnosis, t),
    signature: "",
    confidence: "",
    tone: summary.diagnosis.unexplained_vibration ? "warn" : "success",
    explanation: noFaultExplanation(summary.diagnosis, t),
    chips: [
      {
        label: t("history.covered_speeds"),
        value: speedRangeText(speeds.min_kmh, speeds.max_kmh, f),
      },
      {
        label: t("history.summary_sensor_count"),
        value: f.formatInt(summary.sensor_count_used),
      },
    ],
    nextStepLabel: null,
    nextStep: null,
  };
}

function diagnosisCard(
  summary: HistoryInsightsPayload,
  diagnosis: Diagnosis,
  f: Formatters,
): PrimaryFinding {
  const { t } = f;
  const weak = diagnosis.verdict === "weak_evidence";
  const level = diagnosis.confidence_level;
  const zone = zoneText(diagnosis, t);
  const source = carSourceLabel(diagnosis.source, diagnosis, t);
  const ev = electric(diagnosis);
  const unlocated = unlocatedWheel(diagnosis);
  const locateWheel = t("history.findings_next_step_locate_wheel");
  return {
    eyebrow: t(weak ? "history.verdict.eyebrow" : "history.primary_diagnosis"),
    headline: weak ? t("history.verdict.weak_evidence") : source,
    signature: diagnosisSignature(diagnosis, f),
    confidence: [
      confidenceText(level, t),
      level ? t(`history.confidence_meaning.${level}`) : "",
    ]
      .filter(Boolean)
      .join(" — "),
    tone: levelTone(level),
    explanation: weak
      ? t("history.verdict.weak_body", {
          source,
          location: unlocated
            ? t("history.zone.unlocated_wheel", { location: zone })
            : zone,
        })
      : String(
          summary.findings.find(
            (item) => item.finding_id === diagnosis.finding_id,
          )?.evidence_summary ?? "",
        ),
    chips: [
      { label: t("history.findings_location"), value: zone },
      {
        label: t("history.findings_speed_band"),
        value: speedRangeText(
          diagnosis.speed_min_kmh,
          diagnosis.speed_max_kmh,
          f,
        ),
      },
      {
        label: t("history.findings_signature"),
        value: diagnosisSignature(diagnosis, f),
      },
    ],
    nextStepLabel: t(
      weak ? "history.recapture_label" : "history.findings_next_step_label",
    ),
    nextStep: unlocated
      ? weak
        ? `${locateWheel} ${recaptureRecipe(f, ev, diagnosis)}`
        : locateWheel
      : weak
        ? recaptureRecipe(f, ev, diagnosis)
        : drivelineNextStep(diagnosis, zone, t),
  };
}

/** Where to look; a driveline fault on a car with a known layout also names
 * the parts to have checked, the axle the sensors point to first. Next to the
 * rear propshaft, the front drive is an all-wheel-drive car's front propshaft
 * and differential; alone it is a car without a propshaft, whose gearbox
 * output shaft turns at the order (its drive shafts turn at wheel speed). */
function drivelineNextStep(
  diagnosis: Diagnosis,
  zone: string,
  t: Translate,
): string {
  const named =
    diagnosis.source === "driveline" ? (diagnosis.driveline_parts ?? []) : [];
  const awd = named.includes("propshaft_rear");
  const parts = named.map((part) =>
    t(
      awd && part === "front_drive"
        ? "history.driveline_parts.front_drive_awd"
        : `history.driveline_parts.${part}`,
    ),
  );
  if (parts.length === 0) {
    return t("history.findings_next_step", { location: zone });
  }
  return parts.length === 1
    ? t("history.findings_next_step_driveline", {
        location: zone,
        parts: parts[0],
      })
    : t("history.findings_next_step_driveline_then", {
        location: zone,
        first: parts[0],
        second: parts[1],
      });
}

/** How to record again; an EV cannot coast in neutral, so it skips that step,
 * and brake judder needs firm braking from speed instead. */
function recaptureRecipe(
  f: Pick<Formatters, "fmt" | "t" | "speedUnit">,
  ev: boolean,
  diagnosis: Diagnosis,
): string {
  const speed = (kmh: number) => f.fmt(kmhInUnit(kmh, f.speedUnit), 0);
  if (diagnosis.source === "brakes") {
    return f.t("history.recapture_recipe_brakes", {
      from: speed(BRAKE_TEST_FROM_KMH),
      to: speed(BRAKE_TEST_TO_KMH),
      unit: f.t(speedUnitKey(f.speedUnit)),
    });
  }
  return f.t(ev ? "history.recapture_recipe_ev" : "history.recapture_recipe", {
    from: speed(GUIDED_SWEEP_FROM_KMH),
    to: speed(GUIDED_SWEEP_TO_KMH),
    unit: f.t(speedUnitKey(f.speedUnit)),
  });
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
  const diagnosis = summary.diagnosis;
  if (diagnosis.verdict === "no_fault") {
    return {
      kind: "findings",
      primary: noFaultCard(summary, f),
      checks: checksModel(diagnosis, f),
      secondaryTitle: null,
      visibleSecondary: [],
      hiddenSecondary: [],
      showMoreLabel: null,
    };
  }
  const secondary = findings(summary)
    .filter(
      (finding) =>
        finding.finding_id !== diagnosis.finding_id &&
        !NON_FAULT_SOURCES.has(sourceKey(finding.suspected_source)),
    )
    .map((finding) => secondaryFinding(finding, summary, f));
  const hidden = secondary.slice(2);
  return {
    kind: "findings",
    primary: diagnosisCard(summary, diagnosis, f),
    checks: checksModel(diagnosis, f),
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

/** Folds free-text location names onto location codes (the car-diagram positions use codes). */
export function heatmapLocationKey(location: unknown): string {
  const raw = String(location || "")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const has = (...words: string[]) => words.every((word) => raw.includes(word));
  if (has("front left", "wheel")) return "front_left_wheel";
  if (has("front right", "wheel")) return "front_right_wheel";
  if (has("rear left", "wheel")) return "rear_left_wheel";
  if (has("rear right", "wheel")) return "rear_right_wheel";
  if (has("engine")) return "engine_bay";
  if (has("drive", "tunnel")) return "driveshaft_tunnel";
  if (has("driver", "seat")) return "driver_seat";
  if (has("trunk")) return "trunk";
  return raw.replaceAll(" ", "_");
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

/** Heatmap keys of the locations a sensor was assigned to when the run started. */
function assignedLocationKeys(
  metadata: HistoryInsightsPayload["metadata"],
): Set<string> {
  const { sensor_snapshots: snapshots } = metadata;
  const keys = new Set<string>();
  for (const snapshot of Array.isArray(snapshots) ? snapshots : []) {
    if (
      typeof snapshot !== "object" ||
      snapshot === null ||
      Array.isArray(snapshot)
    ) {
      continue;
    }
    const { location_code: code } = snapshot;
    if (typeof code === "string" && code.trim()) {
      keys.add(heatmapLocationKey(code));
    }
  }
  return keys;
}

export function buildHeatmap(
  summary: HistoryInsightsPayload,
  f: Pick<Formatters, "fmt" | "t">,
): HeatmapModel {
  const assigned = assignedLocationKeys(summary.metadata);
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
      labels.set(key, locationLabel(label, f.t));
    }
  }
  const values = [...metric.values()];
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const zones = HISTORY_HEATMAP_POSITIONS.map((point) => {
    const value = metric.get(point.key);
    const label = locationLabel(point.key, f.t);
    if (value === undefined || min === null || max === null) {
      return {
        key: point.key,
        label,
        gridArea: point.area,
        // "missing" only when a sensor there sent nothing; most spots simply have none.
        valueLabel: f.t(
          assigned.has(point.key)
            ? "report.missing"
            : "history.heatmap_no_sensor",
        ),
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
        `${labels.get(key) ?? locationLabel(key, f.t)} · ${f.fmt(value, 1)} dB`,
    );
  return { kind: "zones", zones, extras };
}

export function buildDetails(
  run: HistoryEntry,
  detail: RunDetail,
  f: Formatters,
): DetailsModel {
  const { t, fmt, formatInt } = f;
  const summary = rowSummary(detail);
  const showReload = summary !== null || Boolean(detail.insightsError);
  const name = carName(run, t);
  return {
    title: name === t("history.car_missing") ? run.run_id : name,
    runSummary: summary
      ? [
          `${t("report.run_id")}: ${run.run_id}`,
          `${t("history.summary_created")}: ${runTime(run, summary.start_time_utc ?? "", f)}`,
          `${t("history.summary_updated")}: ${runTime(run, run.end_time_utc ?? "", f)}`,
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
