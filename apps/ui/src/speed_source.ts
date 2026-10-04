import type { SpeedSourceKind, SpeedSourceStatusPayload } from "./api/types";

/** Pure speed-source derivations shared by the dashboard and the speed page. */

export interface SpeedSourceSnapshot {
  speedSource: SpeedSourceKind;
  manualSpeedKph: number | null;
  resolvedSpeedSource: SpeedSourceStatusPayload["speed_source"] | null;
}

export type DisplayedSpeedSourceMode = "gps" | "manual" | "obd2";
export type SpeedReadoutLabelKey =
  | "speed.gps"
  | "speed.override"
  | "speed.obd2";

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

/** Which choice card reads as active: a manual fallback shows as Manual. */
export function deriveDisplayedSpeedSourceMode(
  settings: SpeedSourceSnapshot,
  runtimeSpeedSource?: string | null,
): DisplayedSpeedSourceMode {
  const effective = resolveEffectiveSpeedSource(settings, runtimeSpeedSource);
  if (effective === "obd2") {
    return "obd2";
  }
  return isManualLikeSpeedSource(effective) ? "manual" : settings.speedSource;
}

export function deriveSpeedReadoutLabelKey(
  settings: SpeedSourceSnapshot,
  runtimeSpeedSource?: string | null,
): SpeedReadoutLabelKey {
  const effective = resolveEffectiveSpeedSource(settings, runtimeSpeedSource);
  if (effective === "obd2") {
    return "speed.obd2";
  }
  return isManualLikeSpeedSource(effective) ? "speed.override" : "speed.gps";
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
