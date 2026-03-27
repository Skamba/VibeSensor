import { expect, test } from "@playwright/test";

import {
  deriveDisplayedSpeedSourceMode,
  isManualEffectiveSpeedSource,
  resolveEffectiveSpeedSource,
} from "../src/app/speed_source_state";

test.describe("speed source state helpers", () => {
  test("prefers the resolved fallback-manual source over gps configuration", () => {
    const settings = {
      speedSource: "gps" as const,
      manualSpeedKph: 80,
      resolvedSpeedSource: "fallback_manual" as const,
    };

    expect(deriveDisplayedSpeedSourceMode(settings)).toBe("manual");
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
    expect(resolveEffectiveSpeedSource(settings)).toBe("none");
    expect(isManualEffectiveSpeedSource(settings)).toBe(false);
  });
});
