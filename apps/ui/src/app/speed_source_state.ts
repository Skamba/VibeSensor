import type { SpeedSourceKind, SpeedSourceStatusPayload } from "../api/types";
import { computed, type ReadonlySignal } from "./ui_signals";

export interface SpeedSourceStateSnapshot {
  speedSource: SpeedSourceKind;
  manualSpeedKph: number | null;
  resolvedSpeedSource: SpeedSourceStatusPayload["speed_source"] | null;
}

export interface SpeedSourceStateSource {
  speedSource: ReadonlySignal<SpeedSourceKind>;
  manualSpeedKph: ReadonlySignal<number | null>;
  resolvedSpeedSource: ReadonlySignal<SpeedSourceStatusPayload["speed_source"] | null>;
}

export type DisplayedSpeedSourceMode = "gps" | "manual" | "obd2";
export type SpeedReadoutLabelKey = "speed.gps" | "speed.override" | "speed.obd2";

export interface SpeedSourceDerivedState {
  displayedMode: ReadonlySignal<DisplayedSpeedSourceMode>;
  effectiveSource: ReadonlySignal<string | null>;
  isManualEffective: ReadonlySignal<boolean>;
  speedReadoutLabelKey: ReadonlySignal<SpeedReadoutLabelKey>;
}

export function isManualLikeSpeedSource(source: string | null | undefined): boolean {
  return source === "manual" || source === "fallback_manual";
}

export function deriveDisplayedSpeedSourceMode(
  settings: SpeedSourceStateSnapshot,
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
  settings: SpeedSourceStateSnapshot,
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
  settings: SpeedSourceStateSnapshot,
  runtimeSpeedSource?: string | null,
): boolean {
  return isManualLikeSpeedSource(resolveEffectiveSpeedSource(settings, runtimeSpeedSource));
}

export function deriveSpeedReadoutLabelKey(
  settings: SpeedSourceStateSnapshot,
  runtimeSpeedSource?: string | null,
): SpeedReadoutLabelKey {
  const effectiveSource = resolveEffectiveSpeedSource(settings, runtimeSpeedSource);
  if (effectiveSource === "obd2") {
    return "speed.obd2";
  }
  return isManualLikeSpeedSource(effectiveSource) ? "speed.override" : "speed.gps";
}

export function createSpeedSourceDerivedState(
  settings: SpeedSourceStateSource,
  runtimeSpeedSource?: ReadonlySignal<string | null>,
): SpeedSourceDerivedState {
  const snapshot = (): SpeedSourceStateSnapshot => ({
    speedSource: settings.speedSource.value,
    manualSpeedKph: settings.manualSpeedKph.value,
    resolvedSpeedSource: settings.resolvedSpeedSource.value,
  });
  const effectiveSource = computed(() =>
    resolveEffectiveSpeedSource(snapshot(), runtimeSpeedSource?.value)
  );
  const displayedMode = computed<DisplayedSpeedSourceMode>(() => {
    const resolvedSource = effectiveSource.value;
    if (resolvedSource === "obd2") {
      return "obd2";
    }
    if (isManualLikeSpeedSource(resolvedSource)) {
      return "manual";
    }
    return settings.speedSource.value;
  });
  const isManualEffective = computed(() =>
    isManualLikeSpeedSource(effectiveSource.value),
  );
  const speedReadoutLabelKey = computed<SpeedReadoutLabelKey>(() => {
    const resolvedSource = effectiveSource.value;
    if (resolvedSource === "obd2") {
      return "speed.obd2";
    }
    return isManualLikeSpeedSource(resolvedSource)
      ? "speed.override"
      : "speed.gps";
  });

  return {
    displayedMode,
    effectiveSource,
    isManualEffective,
    speedReadoutLabelKey,
  };
}
