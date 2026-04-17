import type { LoggingStatusPayload } from "../../api/types";

export type CaptureReadinessPayload = NonNullable<LoggingStatusPayload["capture_readiness"]>;
export type CaptureReadinessCheckPayload = CaptureReadinessPayload["checks"][number];

export interface RealtimeCaptureReadinessChecklistItemModel {
  checkKey: CaptureReadinessCheckPayload["check_key"];
  state: CaptureReadinessCheckPayload["state"];
  labelText: string;
  stateText: string;
  detailText: string;
}

export interface RealtimeCaptureReadinessChecklistModel {
  titleText: string;
  items: readonly RealtimeCaptureReadinessChecklistItemModel[];
}

export interface CaptureReadinessTextDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  formatInt: (value: number) => string;
}

const CAPTURE_READINESS_ORDER = [
  "sensors_ready",
  "reference_ready",
  "speed_stable",
  "capture_ready",
] as const;

export function captureReadinessCheck(
  readiness: CaptureReadinessPayload | null,
  checkKey: CaptureReadinessCheckPayload["check_key"],
): CaptureReadinessCheckPayload | null {
  return readiness?.checks.find((check) => check.check_key === checkKey) ?? null;
}

function captureReadinessDetailNumber(
  check: CaptureReadinessCheckPayload | null,
  key: string,
): number | null {
  const value = check?.details?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function captureReadinessStateText(
  state: CaptureReadinessCheckPayload["state"],
  deps: CaptureReadinessTextDeps,
): string {
  return deps.t(`dashboard.capture_readiness.state.${state}`);
}

function captureReadinessCheckLabel(
  checkKey: CaptureReadinessCheckPayload["check_key"],
  deps: CaptureReadinessTextDeps,
): string {
  return deps.t(`dashboard.capture_readiness.${checkKey}.label`);
}

export function captureReadinessDetailText(
  check: CaptureReadinessCheckPayload,
  deps: CaptureReadinessTextDeps,
): string {
  const { t, formatInt } = deps;
  if (check.check_key === "sensors_ready") {
    const liveSensorCount = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "live_sensor_count") ?? 0),
    );
    const unassignedSensorCount = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "unassigned_sensor_count") ?? 0),
    );
    const quietPeriodRemaining = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "quiet_period_remaining_s") ?? 0),
    );
    if (check.reason_key === "no_live_sensors") {
      return t("dashboard.capture_readiness.sensors_ready.no_live_sensors");
    }
    if (check.reason_key === "sensor_locations_missing") {
      return t("dashboard.capture_readiness.sensors_ready.sensor_locations_missing", {
        count: formatInt(unassignedSensorCount),
      });
    }
    if (check.reason_key === "recent_integrity_events") {
      return t("dashboard.capture_readiness.sensors_ready.recent_integrity_events", {
        seconds: formatInt(quietPeriodRemaining),
      });
    }
    if (check.reason_key === "limited_sensor_coverage") {
      return t("dashboard.capture_readiness.sensors_ready.limited_sensor_coverage", {
        count: formatInt(liveSensorCount),
      });
    }
    return t("dashboard.capture_readiness.sensors_ready.ready", {
      count: formatInt(liveSensorCount),
    });
  }

  if (check.check_key === "reference_ready") {
    if (check.reason_key === "active_car_missing") {
      return t("dashboard.capture_readiness.reference_ready.active_car_missing");
    }
    if (check.reason_key === "order_reference_incomplete") {
      return t("dashboard.capture_readiness.reference_ready.order_reference_incomplete");
    }
    if (check.reason_key === "speed_source_missing") {
      return t("dashboard.capture_readiness.reference_ready.speed_source_missing");
    }
    if (check.reason_key === "speed_source_not_live") {
      return t("dashboard.capture_readiness.reference_ready.speed_source_not_live");
    }
    if (check.reason_key === "speed_source_fallback_active") {
      return t("dashboard.capture_readiness.reference_ready.speed_source_fallback_active");
    }
    if (check.reason_key === "speed_sample_stale") {
      return t("dashboard.capture_readiness.reference_ready.speed_sample_stale");
    }
    if (check.reason_key === "speed_sample_missing") {
      return t("dashboard.capture_readiness.reference_ready.speed_sample_missing");
    }
    if (check.reason_key === "obd_rpm_missing") {
      return t("dashboard.capture_readiness.reference_ready.obd_rpm_missing");
    }
    if (check.reason_key === "obd_rpm_stale") {
      return t("dashboard.capture_readiness.reference_ready.obd_rpm_stale");
    }
    return t("dashboard.capture_readiness.reference_ready.ready");
  }

  if (check.check_key === "speed_stable") {
    const dwellRemaining = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "dwell_remaining_s") ?? 0),
    );
    const minimumSpeed = Math.max(
      0,
      Math.ceil(captureReadinessDetailNumber(check, "minimum_speed_kmh") ?? 20),
    );
    if (check.reason_key === "speed_sample_missing") {
      return t("dashboard.capture_readiness.speed_stable.speed_sample_missing");
    }
    if (check.reason_key === "speed_too_low") {
      return t("dashboard.capture_readiness.speed_stable.speed_too_low", {
        minimumSpeed: formatInt(minimumSpeed),
      });
    }
    if (check.reason_key === "speed_stabilizing") {
      return t("dashboard.capture_readiness.speed_stable.speed_stabilizing", {
        seconds: formatInt(dwellRemaining),
      });
    }
    if (check.reason_key === "speed_variation_high") {
      return t("dashboard.capture_readiness.speed_stable.speed_variation_high");
    }
    return t("dashboard.capture_readiness.speed_stable.ready");
  }

  if (check.reason_key === "capture_blocked") {
    return t("dashboard.capture_readiness.capture_ready.capture_blocked");
  }
  if (check.reason_key === "ready_with_warnings") {
    return t("dashboard.capture_readiness.capture_ready.ready_with_warnings");
  }
  return t("dashboard.capture_readiness.capture_ready.ready");
}

export function captureReadinessSummaryText(
  readiness: CaptureReadinessPayload | null,
  deps: CaptureReadinessTextDeps,
): string {
  if (!readiness) {
    return "";
  }
  const primaryCheck = readiness.is_ready
    ? readiness.checks.find((check) => check.state === "warn" && check.check_key !== "capture_ready")
    : readiness.checks.find((check) => check.state === "fail" && check.check_key !== "capture_ready");
  if (primaryCheck) {
    return captureReadinessDetailText(primaryCheck, deps);
  }
  if (readiness.is_ready) {
    return "";
  }
  const overallCheck = captureReadinessCheck(readiness, "capture_ready");
  return overallCheck ? captureReadinessDetailText(overallCheck, deps) : "";
}

export function buildRealtimeCaptureReadinessChecklistModel(
  readiness: CaptureReadinessPayload | null,
  params: CaptureReadinessTextDeps & { setupMode: boolean },
): RealtimeCaptureReadinessChecklistModel | null {
  if (!readiness) {
    return null;
  }
  const items = CAPTURE_READINESS_ORDER
    .filter((checkKey) => checkKey !== "capture_ready")
    .map((checkKey) => captureReadinessCheck(readiness, checkKey))
    .filter((check): check is CaptureReadinessCheckPayload => (
      check !== null && (!params.setupMode || check.state !== "pass")
    ))
    .map((check) => ({
      checkKey: check.check_key,
      state: check.state,
      labelText: captureReadinessCheckLabel(check.check_key, params),
      stateText: captureReadinessStateText(check.state, params),
      detailText: captureReadinessDetailText(check, params),
    }));
  if (!items.length) {
    return null;
  }
  return {
    titleText: params.t("dashboard.capture_readiness.title"),
    items,
  };
}
