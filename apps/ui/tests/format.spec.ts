import { afterEach, describe, expect, test } from "vitest";
import {
  fmt,
  fmtTs,
  formatEpochTimestamp,
  formatSpeed,
  formatSpeedRange,
} from "../src/format";
import { setLanguage } from "../src/i18n";

afterEach(async () => {
  await setLanguage("en");
});

describe("number formatting", () => {
  test("uses the active language's decimal separator, without grouping", async () => {
    expect(fmt(3.0812, 2)).toBe("3.08");
    expect(fmt(2.01, 3)).toBe("2.010");
    expect(fmt(2350.25, 1)).toBe("2350.3");
    expect(fmt(Number.NaN, 1)).toBe("--");
    await setLanguage("nl");
    // "2.010" would read as two thousand and ten in Dutch.
    expect(fmt(2.01, 3)).toBe("2,010");
    expect(fmt(3.0812, 2)).toBe("3,08");
    expect(fmt(2350.25, 1)).toBe("2350,3");
  });
});

describe("timestamp formatting helpers", () => {
  test("formats local time as the PDF does, in every language, and falls back for invalid values", async () => {
    // Local 2024-01-02 03:04:05, whatever the test machine's zone.
    const local = new Date(2024, 0, 2, 3, 4, 5);
    const iso = local.toISOString();

    expect(fmtTs(iso)).toBe("2024-01-02 03:04:05");
    expect(formatEpochTimestamp(local.getTime() / 1000)).toBe(
      "2024-01-02 03:04:05",
    );
    await setLanguage("nl");
    expect(fmtTs(new Date(2026, 9, 6, 14, 21, 50).toISOString())).toBe(
      "2026-10-06 14:21:50",
    );

    expect(fmtTs("")).toBe("--");
    expect(fmtTs("not-a-date")).toBe("--");
    expect(formatEpochTimestamp(null)).toBe("—");
    expect(formatEpochTimestamp(Number.NaN)).toBe("—");
    expect(formatEpochTimestamp(Number.POSITIVE_INFINITY)).toBe("—");
    expect(formatEpochTimestamp(-1)).toBe("—");
    expect(formatEpochTimestamp(Number.MAX_VALUE)).toBe("—");
  });
});

describe("speed formatting helpers", () => {
  const t = (key: string) => (key === "speed.unit.mps" ? "m/s" : "km/h");

  test("shows a km/h speed in the display unit", () => {
    expect(formatSpeed(36, "kmh", t, 1)).toBe("36.0 km/h");
    expect(formatSpeed(36, "mps", t, 1)).toBe("10.0 m/s");
    expect(formatSpeed(85, "mps", t, 0)).toBe("24 m/s");
    expect(formatSpeed(null, "kmh", t, 1)).toBe("--");
    expect(formatSpeed(undefined, "mps", t, 0)).toBe("--");
    expect(formatSpeed(Number.NaN, "kmh", t, 0)).toBe("--");
  });

  test("shows a km/h range in the display unit, or null when an end is unknown", () => {
    expect(formatSpeedRange(60, 110, "kmh", t)).toBe("60–110 km/h");
    expect(formatSpeedRange(36, 108, "mps", t)).toBe("10–30 m/s");
    expect(formatSpeedRange(50, 50, "kmh", t)).toBe("50 km/h");
    expect(formatSpeedRange(49.8, 50.2, "kmh", t)).toBe("50 km/h");
    expect(formatSpeedRange(null, 110, "kmh", t)).toBeNull();
    expect(formatSpeedRange(60, undefined, "mps", t)).toBeNull();
    expect(formatSpeedRange(60, Number.POSITIVE_INFINITY, "kmh", t)).toBeNull();
  });
});
