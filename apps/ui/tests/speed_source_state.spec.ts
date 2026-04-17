import { expect, test } from "@playwright/test";

import {
  createSpeedSourceDerivedState,
  deriveDisplayedSpeedSourceMode,
  deriveSpeedReadoutLabelKey,
  isManualEffectiveSpeedSource,
  resolveEffectiveSpeedSource,
} from "../src/app/speed_source_state";
import { createAppState } from "../src/app/ui_app_state";
import { signal } from "../src/app/ui_signals";

test.describe("speed source state helpers", () => {
  test("prefers the resolved fallback-manual source over gps configuration", () => {
    const settings = {
      speedSource: "gps" as const,
      manualSpeedKph: 80,
      resolvedSpeedSource: "fallback_manual" as const,
    };

    expect(deriveDisplayedSpeedSourceMode(settings)).toBe("manual");
    expect(deriveSpeedReadoutLabelKey(settings)).toBe("speed.override");
    expect(resolveEffectiveSpeedSource(settings)).toBe("fallback_manual");
    expect(isManualEffectiveSpeedSource(settings)).toBe(true);
  });

  test("keeps gps selected when gps is the resolved effective source", () => {
    const settings = {
      speedSource: "gps" as const,
      manualSpeedKph: 80,
      resolvedSpeedSource: "gps" as const,
    };

    expect(deriveDisplayedSpeedSourceMode(settings)).toBe("gps");
    expect(deriveSpeedReadoutLabelKey(settings)).toBe("speed.gps");
    expect(resolveEffectiveSpeedSource(settings)).toBe("gps");
    expect(isManualEffectiveSpeedSource(settings)).toBe(false);
  });

  test("shows manual before live status arrives when manual is configured", () => {
    const settings = {
      speedSource: "manual" as const,
      manualSpeedKph: 45,
      resolvedSpeedSource: null,
    };

    expect(deriveDisplayedSpeedSourceMode(settings)).toBe("manual");
    expect(deriveSpeedReadoutLabelKey(settings)).toBe("speed.override");
    expect(resolveEffectiveSpeedSource(settings)).toBe("manual");
    expect(isManualEffectiveSpeedSource(settings)).toBe(true);
  });

  test("keeps gps selected for unavailable gps state without inventing manual mode", () => {
    const settings = {
      speedSource: "gps" as const,
      manualSpeedKph: null,
      resolvedSpeedSource: "none" as const,
    };

    expect(deriveDisplayedSpeedSourceMode(settings)).toBe("gps");
    expect(deriveSpeedReadoutLabelKey(settings)).toBe("speed.gps");
    expect(resolveEffectiveSpeedSource(settings)).toBe("none");
    expect(isManualEffectiveSpeedSource(settings)).toBe(false);
  });

  test("renders an OBD2 header label when OBD2 is the resolved effective source", () => {
    const settings = {
      speedSource: "obd2" as const,
      manualSpeedKph: null,
      resolvedSpeedSource: "obd2" as const,
    };

    expect(deriveDisplayedSpeedSourceMode(settings)).toBe("obd2");
    expect(deriveSpeedReadoutLabelKey(settings)).toBe("speed.obd2");
    expect(resolveEffectiveSpeedSource(settings)).toBe("obd2");
    expect(isManualEffectiveSpeedSource(settings)).toBe(false);
  });

  test("reactively updates derived signals when settings and runtime source change", () => {
    const state = createAppState();
    const runtimeSpeedSource = signal<string | null>(null);
    const derived = createSpeedSourceDerivedState(
      state.settings,
      runtimeSpeedSource,
    );

    expect(derived.displayedMode.value).toBe("gps");
    expect(derived.speedReadoutLabelKey.value).toBe("speed.gps");
    expect(derived.isManualEffective.value).toBe(false);

    runtimeSpeedSource.value = "fallback_manual";
    expect(derived.displayedMode.value).toBe("manual");
    expect(derived.speedReadoutLabelKey.value).toBe("speed.override");
    expect(derived.isManualEffective.value).toBe(true);

    state.settings.resolvedSpeedSource.value = "obd2";
    expect(derived.effectiveSource.value).toBe("obd2");
    expect(derived.displayedMode.value).toBe("obd2");
    expect(derived.speedReadoutLabelKey.value).toBe("speed.obd2");
  });
});
