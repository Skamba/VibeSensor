import type { SettingsState } from "./ui_app_state";

export interface SpeedSourceStateSource {
  speedSource: SettingsState["speedSource"];
  manualSpeedKph: SettingsState["manualSpeedKph"];
  resolvedSpeedSource: SettingsState["resolvedSpeedSource"];
}

export type DisplayedSpeedSourceMode = "gps" | "manual" | "obd2";
export type SpeedReadoutLabelKey = "speed.gps" | "speed.override" | "speed.obd2";

export function isManualLikeSpeedSource(source: string | null | undefined): boolean {
  return source === "manual" || source === "fallback_manual";
}

export function deriveDisplayedSpeedSourceMode(
  settings: SpeedSourceStateSource,
): DisplayedSpeedSourceMode {
  const effectiveSource = resolveEffectiveSpeedSource(settings);
  if (effectiveSource === "obd2") {
    return "obd2";
  }
  if (isManualLikeSpeedSource(effectiveSource)) {
    return "manual";
  }
  return settings.speedSource;
}

export function resolveEffectiveSpeedSource(
  settings: SpeedSourceStateSource,
  runtimeSpeedSource?: string | null,
): string | null {
  if (settings.resolvedSpeedSource) {
    return settings.resolvedSpeedSource;
  }
  if (runtimeSpeedSource) {
    return runtimeSpeedSource;
  }
  return settings.speedSource;
}

export function isManualEffectiveSpeedSource(
  settings: SpeedSourceStateSource,
  runtimeSpeedSource?: string | null,
): boolean {
  return isManualLikeSpeedSource(resolveEffectiveSpeedSource(settings, runtimeSpeedSource));
}

export function deriveSpeedReadoutLabelKey(
  settings: SpeedSourceStateSource,
  runtimeSpeedSource?: string | null,
): SpeedReadoutLabelKey {
  const effectiveSource = resolveEffectiveSpeedSource(settings, runtimeSpeedSource);
  if (effectiveSource === "obd2") {
    return "speed.obd2";
  }
  return isManualLikeSpeedSource(effectiveSource) ? "speed.override" : "speed.gps";
}
