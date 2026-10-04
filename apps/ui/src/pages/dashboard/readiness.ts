import type { LoggingStatusPayload } from "../../api/types";
import {
  CAPABILITY_FAMILIES,
  type Capabilities,
  type CapabilityFamily,
  type CapabilityMark,
  capabilityMark,
  capabilityNoteKey,
} from "../../capabilities";
import { formatSpeed, type SpeedUnit } from "../../format";

/** Text for the server's capture-readiness checks. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;
type FormatInt = (value: number) => string;

export type Readiness = NonNullable<LoggingStatusPayload["capture_readiness"]>;
export type ReadinessCheck = Readiness["checks"][number];

export interface ChecklistItem {
  checkKey: string;
  state: ReadinessCheck["state"];
  label: string;
  stateText: string;
  detail: string;
}

const CHECK_ORDER = [
  "sensors_ready",
  "reference_ready",
  "speed_stable",
] as const;

/** Reason keys each check has its own message for; anything else reads as ready. */
const KNOWN_REASONS: Record<string, readonly string[]> = {
  sensors_ready: [
    "no_live_sensors",
    "sensor_locations_missing",
    "recent_integrity_events",
    "sensor_timing_unreliable",
    "limited_sensor_coverage",
  ],
  reference_ready: [
    "active_car_missing",
    "speed_source_missing",
    "speed_source_not_live",
    "speed_source_fallback_active",
    "speed_sample_stale",
    "speed_sample_missing",
    "obd_rpm_missing",
    "obd_rpm_stale",
  ],
  speed_stable: [
    "speed_sample_missing",
    "speed_too_low",
    "speed_stabilizing",
    "speed_variation_high",
  ],
  capture_ready: ["capture_blocked", "ready_with_warnings"],
};

export function findCheck(
  readiness: Readiness | null,
  checkKey: string,
): ReadinessCheck | null {
  return (
    readiness?.checks.find((check) => check.check_key === checkKey) ?? null
  );
}

function detailCount(check: ReadinessCheck, key: string, fallback = 0): number {
  const value = check.details?.[key];
  return Math.max(
    0,
    Math.ceil(
      typeof value === "number" && Number.isFinite(value) ? value : fallback,
    ),
  );
}

export function checkDetail(
  check: ReadinessCheck,
  t: Translate,
  formatInt: FormatInt,
  unit: SpeedUnit,
): string {
  const key = check.check_key;
  const group = key in KNOWN_REASONS ? key : "capture_ready";
  const reason = KNOWN_REASONS[group].includes(check.reason_key ?? "")
    ? (check.reason_key ?? "")
    : "ready";
  let vars: Record<string, string> | undefined;
  if (key === "sensors_ready") {
    if (reason === "sensor_locations_missing") {
      vars = {
        count: formatInt(detailCount(check, "unassigned_sensor_count")),
      };
    } else if (reason === "sensor_timing_unreliable") {
      vars = {
        count: formatInt(detailCount(check, "timing_unreliable_sensor_count")),
      };
    } else if (reason === "recent_integrity_events") {
      vars = {
        seconds: formatInt(detailCount(check, "quiet_period_remaining_s")),
      };
    } else if (reason !== "no_live_sensors") {
      vars = { count: formatInt(detailCount(check, "live_sensor_count")) };
    }
  } else if (key === "speed_stable") {
    if (reason === "speed_too_low") {
      vars = {
        minimumSpeed: formatSpeed(
          detailCount(check, "minimum_speed_kmh", 20),
          unit,
          t,
          0,
        ),
      };
    } else if (reason === "speed_stabilizing") {
      vars = { seconds: formatInt(detailCount(check, "dwell_remaining_s")) };
    }
  }
  return t(`dashboard.capture_readiness.${group}.${reason}`, vars);
}

/** The most relevant problem (or warning, when ready) as one sentence. */
export function readinessSummary(
  readiness: Readiness | null,
  t: Translate,
  formatInt: FormatInt,
  unit: SpeedUnit,
): string {
  if (!readiness) {
    return "";
  }
  const wanted = readiness.is_ready ? "warn" : "fail";
  const primary = readiness.checks.find(
    (check) => check.state === wanted && check.check_key !== "capture_ready",
  );
  if (primary) {
    return checkDetail(primary, t, formatInt, unit);
  }
  if (readiness.is_ready) {
    return "";
  }
  const overall = findCheck(readiness, "capture_ready");
  return overall ? checkDetail(overall, t, formatInt, unit) : "";
}

/** Checks to list; while setting up only the ones still failing. */
export function checklist(
  readiness: Readiness | null,
  setupMode: boolean,
  t: Translate,
  formatInt: FormatInt,
  unit: SpeedUnit,
): ChecklistItem[] {
  return CHECK_ORDER.map((key) => findCheck(readiness, key))
    .filter(
      (check): check is ReadinessCheck =>
        check !== null && (!setupMode || check.state !== "pass"),
    )
    .map((check) => ({
      checkKey: check.check_key,
      state: check.state,
      label: t(`dashboard.capture_readiness.${check.check_key}.label`),
      // A steady speed is advice for the guided hold step; it never blocks.
      stateText: t(
        `dashboard.capture_readiness.state.${
          check.check_key === "speed_stable" && check.state === "warn"
            ? "advice"
            : check.state
        }`,
      ),
      detail: checkDetail(check, t, formatInt, unit),
    }));
}

// --- "This run can test" -------------------------------------------------------

export interface CapabilityItem {
  family: CapabilityFamily;
  label: string;
  mark: CapabilityMark;
  note: string | null;
  /** Where the user can fix it, with the button text. */
  fix: { target: "cars" | "speed_source"; label: string } | null;
}

export interface CapabilityModel {
  items: CapabilityItem[];
  /** The typed-in speed caveat (chosen, or standing in for a lost live source); fixed on the speed-source tab. */
  manualNote: string | null;
}

const CAPABILITY_FIX: Record<string, "cars" | "speed_source"> = {
  missing_tire: "cars",
  missing_final_drive: "cars",
  estimated_final_drive: "cars",
  estimated_ratios: "cars",
  missing_top_gear: "cars",
  missing_ratios: "cars",
  estimated_top_gear: "speed_source",
};

/**
 * What the run can test with the active car's references and the speed
 * source (docs/user_journeys.md §5.1). Never blocks the start.
 */
export function capabilityModel(
  capabilities: Capabilities | null,
  manualSpeedText: string,
  fallbackReason: string | null,
  t: Translate,
): CapabilityModel | null {
  if (!capabilities) {
    return null;
  }
  const items = CAPABILITY_FAMILIES.map((family): CapabilityItem => {
    const value = capabilities[family];
    const fix = CAPABILITY_FIX[value];
    const noteKey = capabilityNoteKey(family, value);
    return {
      family,
      label: t(`capabilities.family.${family}`),
      mark: capabilityMark(value),
      note: noteKey ? t(noteKey) : null,
      fix: fix
        ? {
            target: fix,
            label: t(`dashboard.capabilities.fix.${family}.${value}`),
          }
        : null,
    };
  });
  return {
    items,
    manualNote: CAPABILITY_FAMILIES.some(
      (family) => capabilities[family] === "manual_speed",
    )
      ? fallbackReason
        ? t("dashboard.capabilities.fallback_note", {
            reason: fallbackReason,
            speed: manualSpeedText,
          })
        : t("dashboard.capabilities.manual_note", { speed: manualSpeedText })
      : null,
  };
}
