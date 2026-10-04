import type { SpeedSourceKind, SpeedSourceStatusPayload } from "./api/types";

/** Pure speed-source derivations shared by the dashboard and the speed page. */

export interface SpeedSourceSnapshot {
  speedSource: SpeedSourceKind;
  manualSpeedKph: number | null;
  resolvedSpeedSource: SpeedSourceStatusPayload["speed_source"] | null;
}

export type SpeedReadoutLabelKey =
  | "speed.gps"
  | "speed.override"
  | "speed.obd2"
  | "speed.fallback";

export function isManualLikeSpeedSource(
  source: string | null | undefined,
): boolean {
  return source === "manual" || source === "fallback_manual";
}

/** The source the server reports in use, else the live runtime, else the setting. */
export function resolveEffectiveSpeedSource(
  settings: SpeedSourceSnapshot,
  runtimeSpeedSource?: string | null,
): string | null {
  return (
    settings.resolvedSpeedSource || runtimeSpeedSource || settings.speedSource
  );
}

export function isManualEffectiveSpeedSource(
  settings: SpeedSourceSnapshot,
  runtimeSpeedSource?: string | null,
): boolean {
  return isManualLikeSpeedSource(
    resolveEffectiveSpeedSource(settings, runtimeSpeedSource),
  );
}

export function deriveSpeedReadoutLabelKey(
  settings: SpeedSourceSnapshot,
  runtimeSpeedSource?: string | null,
): SpeedReadoutLabelKey {
  const effective = resolveEffectiveSpeedSource(settings, runtimeSpeedSource);
  if (effective === "obd2") {
    return "speed.obd2";
  }
  if (effective === "fallback_manual") {
    return "speed.fallback";
  }
  return effective === "manual" ? "speed.override" : "speed.gps";
}

/**
 * Why the typed-in fallback speed stands in for the chosen live source (GPS
 * without a receiver or a fix, or OBD-II without live speed); null when the
 * chosen source is in effect.
 */
export function fallbackReasonKey(
  settings: SpeedSourceSnapshot,
  status: SpeedSourceStatusPayload | null,
  runtimeSpeedSource?: string | null,
): string | null {
  if (
    resolveEffectiveSpeedSource(settings, runtimeSpeedSource) !==
    "fallback_manual"
  ) {
    return null;
  }
  if (settings.speedSource === "obd2") {
    return "speed.fallback_reason.obd2";
  }
  return gpsReceiverMissing(settings.speedSource, status)
    ? "speed.gps_no_receiver.title"
    : "speed.fallback_reason.gps_no_fix";
}

/**
 * GPS is the chosen source but gpsd has never reported a receiver: no device
 * and no reading. The Pi has no built-in GPS, so a USB receiver is required.
 */
export function gpsReceiverMissing(
  source: SpeedSourceKind,
  status: SpeedSourceStatusPayload | null,
): boolean {
  return (
    source === "gps" &&
    status !== null &&
    status.gps_enabled &&
    status.device === null &&
    status.last_update_age_s === null
  );
}
