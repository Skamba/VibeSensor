import { describe, expect, test } from "vitest";
import {
  fmtTs,
  formatEpochTimestamp,
  formatSpeed,
  formatSpeedRange,
} from "../src/format";

describe("timestamp formatting helpers", () => {
  test("formats valid timestamps through locale path and falls back for invalid values", () => {
    const iso = "2024-01-02T03:04:05Z";
    const expected = new Date(iso).toLocaleString();

    expect(fmtTs(iso)).toBe(expected);
    expect(formatEpochTimestamp(Date.parse(iso) / 1000)).toBe(expected);

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
