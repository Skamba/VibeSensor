import { describe, expect, test } from "vitest";
import { fmtTs, formatEpochTimestamp } from "../src/format";

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
