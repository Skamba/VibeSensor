import type {
  HistoryEntry,
  HistoryInsightWarningPayload,
  HistoryInsightsPayload,
} from "../../api/types";
import { engineLabel } from "../../car_references";
import { HISTORY_HEATMAP_POSITIONS } from "../../config";
import { formatSpeed, formatSpeedRange, type SpeedUnit } from "../../format";
import { locationLabel } from "../../sensor_locations";

/** Pure view models for the History page: run rows and the opened diagnosis.
 *
 * The diagnosis opens with the PDF's page 1, which the server words in full
 * (`owner` in the insights payload); this module only adds layout around it. */

export type Translate = (key: string, vars?: Record<string, unknown>) => string;

export interface Formatters {
  t: Translate;
  fmt: (value: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  /** A short date and time for a run's title ("7 Oct 17:53"). */
  fmtShortTs: (iso: string) => string;
  formatInt: (value: number) => string;
  speedUnit: SpeedUnit;
}

/** Per-run state: the diagnosis (kept while a reload runs) and the PDF download. */
export interface RunDetail {
  summary: HistoryInsightsPayload | null;
  loading: boolean;
  error: string;
  pdfLoading: boolean;
  pdfError: string;
}

export const EMPTY_RUN_DETAIL: RunDetail = {
  summary: null,
  loading: false,
  error: "",
  pdfLoading: false,
  pdfError: "",
};

type Finding = HistoryInsightsPayload["findings"][number];
export type OwnerPage = HistoryInsightsPayload["owner"];
export type Tone = "success" | "warn" | "neutral";
type ChipTone = "warn" | "muted";

export interface RowModel {
  runId: string;
  isExpanded: boolean;
  /** Date and result: "7 Oct 17:53 · Front-left wheel · Moderate". */
  title: string;
  /** Car name and duration. */
  subtitle: string;
  chips: Array<{ key: string; text: string; tone: ChipTone }>;
  toggleTitle: string;
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

/** The diagnosed finding for the workshop: its signature, and the same
 * source's other orders at the same place (T2 next to T1), which are part of
 * it rather than other candidates. */
export interface PrimaryFinding {
  source: string;
  signature: string;
  confidence: string;
  tone: Tone;
  location: string;
  speedBand: string;
  alsoAt: string | null;
  evidence: string;
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

export interface FindingsModel {
  primary: PrimaryFinding | null;
  secondaryTitle: string | null;
  visibleSecondary: SecondaryFinding[];
  hiddenSecondary: SecondaryFinding[];
  showMoreLabel: string | null;
  checks: ChecksModel;
}

export interface HeatmapZone {
  key: string;
  label: string;
  gridArea: string;
  valueLabel: string;
  strongest: boolean;
  /** Null when the location has no measurement. */
  accent: { color: string; fillPercent: number } | null;
}

export interface HeatmapModel {
  zones: HeatmapZone[];
  extras: string[];
}

export interface DetailsModel {
  owner: OwnerPage | null;
  /** Shown while there is no diagnosis yet. */
  stateMessage: string | null;
  error: string | null;
  warnings: Array<{ severity: string; title: string; detail: string | null }>;
  /** The workshop detail behind "More details", once there is a diagnosis. */
  more: { findings: FindingsModel; heatmap: HeatmapModel } | null;
  /** Run metadata for the details footer: id, times, duration, sensors, samples. */
  facts: Array<{ label: string; value: string }>;
  reloadLabel: string;
  reloadDisabled: boolean;
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

const NON_FAULT_SOURCES = new Set(["baseline_noise", "transient_impact"]);
// Brake judder shows when braking firmly from speed (the report's recapture step).
const BRAKE_TEST_FROM_KMH = 100;

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
    // Not told apart without measured RPM: both orders sit at this frequency.
    const other = diagnosis.alternative?.order_code;
    parts.push(
      other ? `${diagnosis.order_code} / ${other}` : diagnosis.order_code,
    );
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

function electric(diagnosis: Diagnosis): boolean {
  return diagnosis.conditions.fuel_type === "EV";
}

/** An engined car without a propshaft (front-wheel drive, e-AWD hybrid). */
function noPropshaft(diagnosis: Diagnosis): boolean {
  return !electric(diagnosis) && diagnosis.conditions.propshaft === false;
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

function durationSeconds(run: HistoryEntry, detail: RunDetail): number | null {
  const summary = detail.summary;
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

/** The diagnosed source; with an order not told apart from another source's,
 * both (an engine order on the propshaft's rhythm without measured RPM). */
function diagnosedSource(diagnosis: Diagnosis, t: Translate): string {
  const source = carSourceLabel(diagnosis.source, diagnosis, t);
  const other = diagnosis.alternative?.source;
  if (!other) {
    return source;
  }
  return t("history.source_or", {
    source,
    other: carSourceLabel(other, diagnosis, t).toLowerCase(),
  });
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
  // A wheel or propshaft order the diagnosed engine order turns with in top gear.
  if (reason === "same_rhythm_as_candidate" && source !== "engine") {
    return `road_${reason}`;
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
  brakeTestSpeed: string,
): string {
  if (check.status === "candidate") {
    return t("history.checks.candidate");
  }
  if (check.status === "ruled_out_estimated" && check.reason) {
    return t(`history.checks.limited.${checkReasonKey(source, check.reason)}`, {
      speed: brakeTestSpeed,
    });
  }
  if (
    check.reason === "stayed_in_neutral" ||
    check.reason === "stopped_in_neutral" ||
    check.reason === "only_while_braking" ||
    check.reason === "faint_only"
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

/** The engine line, as on PDF page 2: the engine and the firing order the run
 * tested, or that only E1/E2 were. */
function engineText(conditions: Diagnosis["conditions"], t: Translate): string {
  const profile = conditions.engine_profile ?? null;
  const firing = conditions.engine_orders?.find((row) =>
    row.roles.includes("firing"),
  )?.code;
  return profile && firing
    ? t("history.references.engine_profile", {
        engine: engineLabel(profile, t),
        firing,
      })
    : t("history.references.engine_unknown");
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
      label: t("history.references.engine"),
      detail: engineText(conditions, t),
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
  f: Pick<Formatters, "fmt" | "t" | "speedUnit">,
): ChecksModel {
  const { t } = f;
  // The brake tips name the speed to brake from in the display unit.
  const brakeTestSpeed = formatSpeed(BRAKE_TEST_FROM_KMH, f.speedUnit, t, 0);
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
          { speed: brakeTestSpeed },
        ),
      });
    } else {
      checked.push({
        label,
        detail: checkedDetail(check, source, diagnosis, t, brakeTestSpeed),
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
  return { zones, extras };
}

/** The row's title after the date: the result, or where the run is. */
function rowResult(run: HistoryEntry, detail: RunDetail, t: Translate): string {
  const owner = detail.summary?.owner;
  if (owner) {
    return owner.verdict === "fault" && owner.level_word
      ? `${owner.result} · ${owner.level_word}`
      : owner.result;
  }
  if (failed(run)) {
    return t("history.row_status.error");
  }
  if (run.lifecycle?.stage === "recording" || run.status === "recording") {
    return t("history.row_status.recording");
  }
  if (!postAnalysisReady(run)) {
    return t("history.row_status.analyzing");
  }
  return detail.error && !detail.loading
    ? t("history.row_status.unavailable")
    : t("history.row_summary_loading");
}

/** Run length as m:ss. */
function durationText(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function shortRunTime(run: HistoryEntry, f: Formatters): string {
  return run.start_time_unverified
    ? f.t("history.date_unknown")
    : f.fmtShortTs(run.start_time_utc);
}

export function buildRow(
  run: HistoryEntry,
  detail: RunDetail,
  isExpanded: boolean,
  f: Formatters,
): RowModel {
  const { t } = f;
  const chips: RowModel["chips"] = [];
  if (run.interrupted) {
    chips.push({
      key: "interrupted",
      text: t("history.interrupted"),
      tone: "warn",
    });
  }
  if (failed(run) && run.error_message) {
    chips.push({
      key: "error-message",
      text: run.error_message,
      tone: "muted",
    });
  }
  const duration = durationSeconds(run, detail);
  const title = `${shortRunTime(run, f)} · ${rowResult(run, detail, t)}`;
  return {
    runId: run.run_id,
    isExpanded,
    title,
    subtitle: [
      carName(run, t),
      ...(duration === null ? [] : [durationText(duration)]),
    ].join(" · "),
    chips,
    toggleTitle: t(
      isExpanded
        ? "history.close_diagnosis_for_run"
        : "history.open_diagnosis_for_run",
      { run: title },
    ),
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

// The PDF's top-view car diagram (report/pdf.py `_car_diagram`), in its
// millimetres: a 62 x 112 box, the body 52% of its width, positions normalized
// from the front of the car (`_POSITIONS`, `_ZONE_RECTS`).
const DIAGRAM_POSITIONS: Record<string, [number, number]> = {
  front_left_wheel: [0.1, 0.2],
  front_right_wheel: [0.9, 0.2],
  rear_left_wheel: [0.1, 0.8],
  rear_right_wheel: [0.9, 0.8],
  engine_bay: [0.5, 0.13],
  front_subframe: [0.5, 0.25],
  transmission: [0.5, 0.34],
  driveshaft_tunnel: [0.5, 0.52],
  driver_seat: [0.32, 0.45],
  front_passenger_seat: [0.68, 0.45],
  rear_left_seat: [0.3, 0.64],
  rear_center_seat: [0.5, 0.66],
  rear_right_seat: [0.7, 0.64],
  rear_subframe: [0.5, 0.76],
  trunk: [0.5, 0.9],
};
const DIAGRAM_WHEELS = [
  "front_left_wheel",
  "front_right_wheel",
  "rear_left_wheel",
  "rear_right_wheel",
];
const DIAGRAM_ZONES: Record<string, [number, number, number, number]> = {
  engine_bay: [0.14, 0.04, 0.86, 0.27],
  driveshaft_tunnel: [0.42, 0.28, 0.58, 0.8],
  transmission: [0.36, 0.27, 0.64, 0.4],
  front_axle: [0.14, 0.16, 0.86, 0.24],
  rear_axle: [0.14, 0.76, 0.86, 0.84],
};
const ZONE_WHEELS: Record<string, string[]> = {
  front_axle: ["front_left_wheel", "front_right_wheel"],
  rear_axle: ["rear_left_wheel", "rear_right_wheel"],
  all_wheels: DIAGRAM_WHEELS,
};
const DIAGRAM_W = 62;
const DIAGRAM_H = 112;
const BODY_W = DIAGRAM_W * 0.52;
const BODY_H = DIAGRAM_H - 18;
const BODY_X = (DIAGRAM_W - BODY_W) / 2;
const BODY_Y = 9;

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The car diagram in the PDF's millimetres (y down), ready to draw as SVG. */
export interface DiagramModel {
  width: number;
  height: number;
  frontLabel: string;
  body: Box & { radius: number };
  windows: Box[];
  /** The highlighted area, when the zone is one. */
  zone: Box | null;
  wheels: Array<Box & { code: string; highlighted: boolean }>;
  /** One circle per sensor: its size follows the level, as on the PDF. */
  markers: Array<{
    code: string;
    label: string;
    value: string;
    cx: number;
    cy: number;
    r: number;
    strongest: boolean;
    /** The level label, in a column beside the car (see `diagramLabels`). */
    text: { x: number; y: number; anchor: "start" | "end" };
    /** A line from the marker to its label, unless the label sits at its wheel. */
    leader: { x1: number; y1: number; x2: number; y2: number } | null;
  }>;
}

function diagramPoint(nx: number, ny: number): [number, number] {
  return [BODY_X + nx * BODY_W, BODY_Y + ny * BODY_H];
}

function diagramBox(x0: number, y0: number, x1: number, y1: number): Box {
  const [px0, py0] = diagramPoint(x0, y0);
  const [px1, py1] = diagramPoint(x1, y1);
  return { x: px0, y: py0, width: px1 - px0, height: py1 - py0 };
}

// Label layout, as report/pdf.py `_diagram_labels` places the PDF's labels.
// The labels are drawn at this size (history-detail.css), in diagram mm.
const LABEL_FONT = 3.7;
const LABEL_PITCH = LABEL_FONT * 1.3;
const LABEL_PAD = 1.5;
const LEADER_CLEARANCE = 0.4;
const LEADER_GAP = 0.6;
const LABEL_SEARCH_ROWS = 6;
const LABEL_LOW = 7;
const LABEL_HIGH = DIAGRAM_H - 2;

type Side = "left" | "right";
type Circle = { cx: number; cy: number; r: number };
type Point = [number, number];
interface LabelSpot {
  x: number;
  y: number;
  side: Side;
  leader: boolean;
}

/** Centres as close to the sorted `desired` ones as allowed, `pitch` apart. */
function stackLabels(desired: number[]): number[] {
  const ys: number[] = [];
  for (const want of desired) {
    ys.push(
      Math.max(
        want,
        LABEL_LOW,
        ys.length ? ys[ys.length - 1] + LABEL_PITCH : LABEL_LOW,
      ),
    );
  }
  if (ys.length && ys[ys.length - 1] > LABEL_HIGH) {
    ys[ys.length - 1] = LABEL_HIGH;
    for (let index = ys.length - 2; index >= 0; index -= 1) {
      ys[index] = Math.min(ys[index], ys[index + 1] - LABEL_PITCH);
    }
  }
  return ys;
}

function keyBefore(a: number[], b: number[]): boolean {
  const index = a.findIndex((value, i) => value !== b[i]);
  return index >= 0 && a[index] < b[index];
}

/** Whether the segment `a`-`b` passes within the clearance of `circle`. */
function passesNear(a: Point, b: Point, circle: Circle): boolean {
  const [dx, dy] = [b[0] - a[0], b[1] - a[1]];
  const length2 = dx * dx + dy * dy;
  const t =
    length2 === 0
      ? 0
      : Math.max(
          0,
          Math.min(
            1,
            ((circle.cx - a[0]) * dx + (circle.cy - a[1]) * dy) / length2,
          ),
        );
  const px = a[0] + t * dx - circle.cx;
  const py = a[1] + t * dy - circle.cy;
  return px * px + py * py < (circle.r + LEADER_CLEARANCE) ** 2;
}

function segmentsCross(a: [Point, Point], b: [Point, Point]): boolean {
  const turn = (p: Point, q: Point, r: Point) =>
    (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  return (
    turn(b[0], b[1], a[0]) * turn(b[0], b[1], a[1]) < 0 &&
    turn(a[0], a[1], b[0]) * turn(a[0], a[1], b[1]) < 0
  );
}

/**
 * Each marker's label in a column beside the car, so no two overlap. A marker
 * on the left or right half gets its label on that side, at its own height
 * when free; one on the centre line gets the side, and the height nearest its
 * own, where its leader passes no other marker and crosses no other leader
 * (else the fewest), then the side with fewer labels.
 */
function diagramLabels(
  circles: ReadonlyMap<string, Circle>,
): Map<string, LabelSpot> {
  const edge = { left: BODY_X - LABEL_PAD, right: BODY_X + BODY_W + LABEL_PAD };
  const mid = BODY_X + BODY_W / 2;
  const columns: Record<Side, string[]> = { left: [], right: [] };
  const wanted = new Map<string, number>();
  const centre: string[] = [];
  for (const [code, circle] of circles) {
    wanted.set(code, circle.cy);
    if (Math.abs(circle.cx - mid) < 0.01) {
      centre.push(code);
    } else {
      columns[circle.cx < mid ? "left" : "right"].push(code);
    }
  }
  const byWanted = (a: string, b: string) =>
    (wanted.get(a) ?? 0) - (wanted.get(b) ?? 0) || (a < b ? -1 : a > b ? 1 : 0);
  const place = (side: Side, codes: string[]) => {
    const ordered = [...codes].sort(byWanted);
    const ys = stackLabels(ordered.map((code) => wanted.get(code) ?? 0));
    return new Map(
      ordered.map((code, index): [string, LabelSpot] => {
        const circle = circles.get(code) as Circle;
        return [
          code,
          {
            x: edge[side],
            y: ys[index],
            side,
            leader:
              !code.endsWith("_wheel") || Math.abs(ys[index] - circle.cy) > 0.3,
          },
        ];
      }),
    );
  };
  const clashes = (labels: Map<string, LabelSpot>) => {
    const leaders: Array<[string, [Point, Point]]> = [];
    for (const [code, label] of labels) {
      const circle = circles.get(code) as Circle;
      if (label.leader) {
        leaders.push([
          code,
          [
            [circle.cx, circle.cy],
            [label.x, label.y],
          ],
        ]);
      }
    }
    let count = 0;
    for (const [code, [a, b]] of leaders) {
      for (const [other, circle] of circles) {
        if (other !== code && passesNear(a, b, circle)) {
          count += 1;
        }
      }
    }
    leaders.forEach(([, a], index) => {
      for (const [, b] of leaders.slice(index + 1)) {
        if (segmentsCross(a, b)) {
          count += 1;
        }
      }
    });
    return count;
  };
  const centreOrder = [...centre].sort(
    (a, b) =>
      (circles.get(a)?.cy ?? 0) - (circles.get(b)?.cy ?? 0) ||
      (a < b ? -1 : a > b ? 1 : 0),
  );
  for (const code of centreOrder) {
    const cy = circles.get(code)?.cy ?? 0;
    // Fewest clashes, then nearest its own height, then the emptier side.
    let best: { key: number[]; side: Side; y: number } | null = null;
    for (const side of ["left", "right"] as const) {
      for (
        let rows = -LABEL_SEARCH_ROWS;
        rows <= LABEL_SEARCH_ROWS;
        rows += 1
      ) {
        const y = cy + rows * LABEL_PITCH;
        wanted.set(code, y);
        const key = [
          clashes(place(side, [...columns[side], code])),
          Math.abs(rows),
          columns[side].length,
          side === "left" ? 0 : 1,
          y,
        ];
        if (!best || keyBefore(key, best.key)) {
          best = { key, side, y };
        }
      }
    }
    const { side, y } = best as { side: Side; y: number };
    wanted.set(code, y);
    columns[side].push(code);
  }
  return new Map([
    ...place("left", columns.left),
    ...place("right", columns.right),
  ]);
}

export function ownerDiagram(diagram: OwnerPage["diagram"]): DiagramModel {
  const zone = diagram.zone ?? "";
  const highlighted = new Set(ZONE_WHEELS[zone] ?? [zone]);
  const zoneRect = DIAGRAM_ZONES[zone];
  const placed = diagram.markers.filter(
    (marker) => DIAGRAM_POSITIONS[marker.code],
  );
  const circles = new Map(
    placed.map((marker): [string, Circle] => {
      const [cx, cy] = diagramPoint(...DIAGRAM_POSITIONS[marker.code]);
      const r = 1.6 + 2.4 * Math.max(0, Math.min(1, marker.ratio ?? 0));
      return [marker.code, { cx, cy, r }];
    }),
  );
  const labels = diagramLabels(circles);
  return {
    width: DIAGRAM_W,
    height: DIAGRAM_H,
    frontLabel: diagram.front_label,
    body: {
      x: BODY_X,
      y: BODY_Y,
      width: BODY_W,
      height: BODY_H,
      radius: BODY_W * 0.28,
    },
    windows: [
      diagramBox(0.18, 0.3, 0.82, 0.37),
      diagramBox(0.2, 0.74, 0.8, 0.79),
    ],
    zone: zoneRect ? diagramBox(...zoneRect) : null,
    wheels: DIAGRAM_WHEELS.map((code) => {
      const [cx, cy] = diagramPoint(...DIAGRAM_POSITIONS[code]);
      return {
        code,
        x: cx - 2.2,
        y: cy - 5,
        width: 4.4,
        height: 10,
        highlighted: highlighted.has(code),
      };
    }),
    markers: placed.map((marker) => {
      const circle = circles.get(marker.code) as Circle;
      const label = labels.get(marker.code) as LabelSpot;
      const left = label.side === "left";
      return {
        code: marker.code,
        label: marker.label,
        value: marker.value,
        ...circle,
        strongest: marker.strongest,
        // The digits' middle sits on the label's centre line.
        text: {
          x: label.x,
          y: label.y + LABEL_FONT * 0.35,
          anchor: left ? "end" : "start",
        },
        leader: label.leader
          ? {
              x1: circle.cx,
              y1: circle.cy,
              x2: label.x + (left ? LEADER_GAP : -LEADER_GAP),
              y2: label.y,
            }
          : null,
      };
    }),
  };
}

/** The diagnosis' other orders from the same source at the same place (the
 * wheel's T2 next to its T1): harmonics of the one fault, not other causes. */
function harmonics(diagnosis: Diagnosis): Diagnosis["order_findings"] {
  if (!diagnosis.source || !diagnosis.location) {
    return [];
  }
  return diagnosis.order_findings.filter(
    (row) =>
      row.finding_id !== diagnosis.finding_id &&
      row.source === diagnosis.source &&
      row.location === diagnosis.location,
  );
}

function primaryFinding(
  summary: HistoryInsightsPayload,
  f: Formatters,
): PrimaryFinding | null {
  const { diagnosis } = summary;
  if (diagnosis.verdict === "no_fault" || !diagnosis.source) {
    return null;
  }
  const { t } = f;
  const also = harmonics(diagnosis).map((row) =>
    row.frequency_hz == null
      ? row.order_code
      : `${row.order_code} (${f.fmt(row.frequency_hz, 1)} Hz)`,
  );
  const finding = summary.findings.find(
    (item) => item.finding_id === diagnosis.finding_id,
  );
  return {
    source: diagnosedSource(diagnosis, t),
    signature: diagnosisSignature(diagnosis, f),
    confidence: confidenceText(diagnosis.confidence_level, t),
    tone: levelTone(diagnosis.confidence_level),
    location: diagnosis.location
      ? locationLabel(diagnosis.location, t)
      : t("report.missing"),
    speedBand: speedRangeText(
      diagnosis.speed_min_kmh,
      diagnosis.speed_max_kmh,
      f,
    ),
    alsoAt: also.length
      ? t("history.also_at", { orders: also.join(", ") })
      : null,
    evidence: String(finding?.evidence_summary ?? ""),
  };
}

function findingsModel(
  summary: HistoryInsightsPayload,
  f: Formatters,
): FindingsModel {
  const { t } = f;
  const { diagnosis } = summary;
  const skip = new Set([
    diagnosis.finding_id,
    ...harmonics(diagnosis).map((row) => row.finding_id),
  ]);
  const secondary =
    diagnosis.verdict === "no_fault"
      ? []
      : findings(summary)
          .filter(
            (finding) =>
              !skip.has(finding.finding_id) &&
              !NON_FAULT_SOURCES.has(sourceKey(finding.suspected_source)),
          )
          .map((finding) => secondaryFinding(finding, summary, f));
  const hidden = secondary.slice(2);
  return {
    primary: primaryFinding(summary, f),
    secondaryTitle: secondary.length
      ? t("history.secondary_candidates_title")
      : null,
    visibleSecondary: secondary.slice(0, 2),
    hiddenSecondary: hidden,
    showMoreLabel: hidden.length
      ? t("history.show_more_findings", { count: hidden.length })
      : null,
    checks: checksModel(diagnosis, f),
  };
}

function insightWarnings(
  summary: HistoryInsightsPayload | null,
): DetailsModel["warnings"] {
  const all: HistoryInsightWarningPayload[] = summary?.warnings ?? [];
  return all.map((warning) => ({
    severity: String(warning.severity),
    title: String(warning.title),
    detail: warning.detail ? String(warning.detail) : null,
  }));
}

/** The details footer: the run's identity and size, said once. */
function runFacts(
  run: HistoryEntry,
  detail: RunDetail,
  f: Formatters,
): DetailsModel["facts"] {
  const { t } = f;
  const summary = detail.summary;
  const duration = durationSeconds(run, detail);
  const facts = [
    { label: t("report.run_id"), value: run.run_id },
    { label: t("history.started"), value: runTime(run, run.start_time_utc, f) },
  ];
  if (run.end_time_utc) {
    facts.push({
      label: t("history.ended"),
      value: runTime(run, run.end_time_utc, f),
    });
  }
  if (duration !== null) {
    facts.push({
      label: t("history.summary_size"),
      value: `${f.fmt(duration, 1)} s`,
    });
  }
  if (summary) {
    facts.push({
      label: t("history.summary_sensor_count"),
      value: f.formatInt(summary.sensor_count_used),
    });
  }
  facts.push({
    label: t("history.raw_samples"),
    value:
      run.raw_sample_count == null ? "--" : f.formatInt(run.raw_sample_count),
  });
  return facts;
}

export function buildDetails(
  run: HistoryEntry,
  detail: RunDetail,
  f: Formatters,
): DetailsModel {
  const { t } = f;
  const summary = detail.summary;
  return {
    owner: summary?.owner ?? null,
    stateMessage: summary
      ? null
      : t(
          detail.loading
            ? "history.loading_insights"
            : postAnalysisReady(run)
              ? "history.diagnosis_unavailable"
              : "history.findings_pending",
        ),
    error: detail.error || null,
    warnings: [...rawCaptureWarnings(run, t), ...insightWarnings(summary)],
    more: summary
      ? {
          findings: findingsModel(summary, f),
          heatmap: buildHeatmap(summary, f),
        }
      : null,
    facts: runFacts(run, detail, f),
    reloadLabel: t(
      detail.loading
        ? "history.loading_insights"
        : summary
          ? "history.reload_insights"
          : "history.load_insights",
    ),
    reloadDisabled: detail.loading,
  };
}
